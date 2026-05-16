import time
from datetime import datetime, timedelta
import pandas as pd

from data.fetcher import DataFetcher
from scheduler.mailer import Mailer

HOUR = 9
MINUTE = 0
LOOKBACK_DAYS = 90


def _sleep_until_next_trading_day(hour: int, minute: int):
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    while target.weekday() >= 5:
        target += timedelta(days=1)
    seconds = (target - now).total_seconds()
    print(
        f"下次执行: {target.strftime('%Y-%m-%d %H:%M:%S')} "
        f"(等待 {seconds / 60:.0f} 分钟)"
    )
    time.sleep(seconds)


def _build_email(signal, cfg: dict) -> tuple[str, str]:
    today = datetime.now().strftime('%Y-%m-%d')
    details = signal.details
    stock = f"{cfg['stock_name']}({cfg['stock_code']})"
    close = details['close']
    pct_chg = details.get('pct_chg', 0)
    data_date = details.get('date', today)
    user_holding = cfg.get('user_holding', False)
    B = details.get('B')
    S = details.get('S')

    action_map = {
        'buy': ('🟢 买入机会', '最低价跌破买入线，策略触发买入信号'),
        'sell': ('🔴 卖出信号', '最高价突破卖出线，策略触发卖出信号'),
        'volatile': ('🔄 双向触发', '日内振幅同时覆盖买卖线'),
        'near_buy': ('👀 接近买入', '收盘低于买入线但今日最低未触发'),
        'near_sell': ('⏰ 接近卖出', '收盘高于卖出线但今日最高未触发'),
        'hold': ('✅ 震荡持有', '价格在买卖区间内运行'),
    }
    title, desc = action_map.get(signal.action, ('❓ 未知', ''))

    action_detail = details.get('action_detail', '')

    if signal.action == 'buy':
        if user_holding:
            personal = '⚠️ 已持仓，无需重复买入'
            advice = '策略触发买入，但你已在车上，无需操作。'
        else:
            personal = '💡 入场机会'
            advice = '建议挂限价单买入。'
    elif signal.action == 'sell':
        if user_holding:
            personal = '⚠️ 建议离场'
            advice = '策略触发卖出，建议挂限价单卖出。'
        else:
            personal = '— 空仓中，不受影响'
            advice = '策略触发卖出，但你已空仓。'
    else:
        if user_holding:
            personal = '✅ 继续持有'
            advice = '价格在持有区间内，维持持仓。'
        else:
            personal = '⏳ 空仓观望'
            advice = '等待买入信号。'

    subject = (
        f"[{cfg.get('email_subject_prefix', '')}] {title} "
        f"{stock} - {today}"
    )

    param_line = ''
    if B and S:
        param_line = (
            f"<p><b>策略参数:</b> 买入线 ¥{B:.2f} / 卖出线 ¥{S:.2f}</p>"
        )

    recent_html = ''
    if 'recent' in details:
        recent = details['recent']
        recent_html = (
            "<table border='1' cellpadding='4' style='border-collapse:collapse'>"
            "<tr><th>日期</th><th>开盘</th><th>最高</th><th>最低</th>"
            "<th>收盘</th><th>涨跌幅</th></tr>"
        )
        for idx, row in recent.iterrows():
            chg = row.get('pct_chg', 0)
            chg_color = 'red' if chg >= 0 else 'green'
            recent_html += (
                f"<tr><td>{idx.strftime('%m-%d')}</td>"
                f"<td>{row['open']:.2f}</td>"
                f"<td>{row['high']:.2f}</td>"
                f"<td>{row['low']:.2f}</td>"
                f"<td>{row['close']:.2f}</td>"
                f"<td style='color:{chg_color}'>{chg:+.2f}%</td></tr>"
            )
        recent_html += "</table>"

    body = f"""
    <h2>{title}</h2>
    <p><b>股票:</b> {stock} | 数据日期: {data_date}</p>
    <p><b>收盘:</b> ¥{close:.2f}（{'涨' if pct_chg >= 0 else '跌'}{abs(pct_chg):.2f}%）</p>
    {param_line}
    <p><b>策略信号:</b> {desc}</p>
    <p>{action_detail}</p>
    <hr>
    <p><b>你的持仓:</b> {'已持仓' if user_holding else '空仓'}</p>
    <p><b>建议操作:</b> {personal}</p>
    <p>{advice}</p>
    <hr>
    <p><b>最近 10 个交易日:</b></p>
    {recent_html}
    <hr>
    <p style='color:#888;font-size:12px'>本邮件由量化策略自动生成，仅供参考，不构成投资建议。</p>
    """

    return subject, body


def _check_and_notify(
    cfg: dict, fetcher: DataFetcher, mailer: Mailer
):
    now = datetime.now()
    print(f"{now.strftime('%Y-%m-%d %H:%M:%S')} — 检查 {cfg['stock_name']}")

    end = now.strftime('%Y%m%d')
    start = (now - timedelta(days=LOOKBACK_DAYS)).strftime('%Y%m%d')

    try:
        df = fetcher.fetch(cfg['ts_code'], start, end)
    except Exception as e:
        print(f"  数据获取失败: {e}")
        return

    if df is None or df.empty:
        print(f"  数据为空")
        return

    strategy = cfg['strategy']
    params = cfg.get('strategy_params', {})

    try:
        signal = strategy.generate_signal(df, params)
    except Exception as e:
        print(f"  信号计算失败: {e}")
        return

    subject, body = _build_email(signal, cfg)
    print(f"  信号: {subject}")
    mailer.send(subject, body)


def run_daemon(
    stocks_config: list[dict],
    fetcher: DataFetcher,
    mailer: Mailer,
    hour: int = HOUR,
    minute: int = MINUTE,
):
    print(f"量化策略守护进程启动 (每交易日 {hour:02d}:{minute:02d})")
    print(f"监控股票: {', '.join(c['stock_name'] for c in stocks_config)}")
    print("按 Ctrl+C 停止\n")

    for cfg in stocks_config:
        _check_and_notify(cfg, fetcher, mailer)

    while True:
        try:
            _sleep_until_next_trading_day(hour, minute)
            for cfg in stocks_config:
                _check_and_notify(cfg, fetcher, mailer)
        except KeyboardInterrupt:
            print("\n已停止")
            break
        except Exception as e:
            print(f"异常: {e}, 60秒后重试")
            time.sleep(60)
