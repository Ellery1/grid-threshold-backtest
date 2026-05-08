import sys
import os
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import tushare as ts
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
import time
import warnings
from dotenv import load_dotenv

warnings.filterwarnings('ignore')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from email_config import EmailConfig

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
ts.set_token(os.getenv('TUSHARE_TOKEN'))
pro = ts.pro_api()

STOCK_CODE = '002281'
STOCK_NAME = '光迅科技'
TS_CODE = '002281.SZ'
N = 10
HOUR = 9
MINUTE = 0
USER_HOLDING = False  # 设为 True 表示你实际已持仓，脚本会据此调整建议


def fetch_data():
    end = datetime.now().strftime('%Y%m%d')
    start = (datetime.now() - timedelta(days=90)).strftime('%Y%m%d')
    raw = pro.daily(ts_code=TS_CODE, start_date=start, end_date=end, adj='qfq')
    if raw.empty:
        return None
    raw['trade_date'] = pd.to_datetime(raw['trade_date'])
    raw = raw.sort_values('trade_date').set_index('trade_date')
    return raw


def get_signal(df):
    close = df['close']
    ma = close.rolling(N).mean()

    latest = df.iloc[-1]
    latest_date = df.index[-1]
    latest_close = close.iloc[-1]
    latest_ma = ma.iloc[-1]

    prev_close = close.iloc[-2]
    prev_ma = ma.iloc[-2]

    above_ma = latest_close > latest_ma
    cross_up = above_ma and prev_close <= prev_ma
    cross_down = latest_close < latest_ma

    return {
        'date': latest_date,
        'close': latest_close,
        'ma': latest_ma,
        'above_ma': above_ma,
        'cross_up': cross_up,
        'cross_down': cross_down,
        'open': latest['open'],
        'high': latest['high'],
        'low': latest['low'],
        'pct_chg': latest.get('pct_chg', 0),
        'recent': df.tail(10)[['open', 'close', 'high', 'low', 'pct_chg']]
    }


def build_email(signal):
    today = datetime.now().strftime('%Y-%m-%d')
    data_date = signal['date'].strftime('%Y-%m-%d')
    gap = signal['close'] - signal['ma']

    strategy_action = ''
    personal_action = ''
    advice = ''

    if signal['cross_up']:
        strategy_action = '🟢 买入'
        if USER_HOLDING:
            personal_action = '⚠️ 已持仓（无需重复买入）'
            advice = '策略触发买入，但你已在车上了，无需操作。'
        else:
            personal_action = '💡 入场机会'
            advice = 'MA10 金叉确认，建议: 次日开盘买入上车。'
        detail = f"收盘 ¥{signal['close']:.2f} 站上 MA10 ¥{signal['ma']:.2f}（金叉）"
    elif signal['cross_down']:
        strategy_action = '🔴 卖出'
        if USER_HOLDING:
            personal_action = '⚠️ 建议离场'
            advice = '收盘跌破 MA10，建议: 次日开盘卖出。'
        else:
            personal_action = '— 空仓中，不受影响'
            advice = '策略触发卖出，但你已空仓，无需操作。'
        detail = f"收盘 ¥{signal['close']:.2f} 跌破 MA10 ¥{signal['ma']:.2f}"
    elif signal['above_ma']:
        strategy_action = '✅ 持仓'
        if USER_HOLDING:
            personal_action = '✅ 继续持有'
            advice = f'收盘在 MA10 上方（价差 {gap:+.2f}），稳稳拿着。'
        else:
            personal_action = '⏳ 空仓观望'
            advice = f'策略处于持仓状态，但你还没上车。收盘高出 MA10 {gap:+.2f}，追高性价比低，建议等下一次金叉。'
        detail = f"收盘 ¥{signal['close']:.2f}，MA10 ¥{signal['ma']:.2f}，价差 {gap:+.2f}"
    else:
        strategy_action = '⏳ 观望'
        personal_action = '⏳ 观望'
        advice = '收盘在 MA10 下方，等待金叉信号再考虑入场。'
        detail = f"收盘 ¥{signal['close']:.2f}，MA10 ¥{signal['ma']:.2f}，价差 {gap:+.2f}"

    subject = f"[{strategy_action}] {STOCK_NAME}({STOCK_CODE}) - {today}"

    recent_html = "<table border='1' cellpadding='4' style='border-collapse:collapse'><tr><th>日期</th><th>开盘</th><th>最高</th><th>最低</th><th>收盘</th><th>涨跌幅</th></tr>"
    for idx, row in signal['recent'].iterrows():
        chg = row.get('pct_chg', 0)
        chg_color = 'red' if chg >= 0 else 'green'
        recent_html += f"<tr><td>{idx.strftime('%m-%d')}</td><td>{row['open']:.2f}</td><td>{row['high']:.2f}</td><td>{row['low']:.2f}</td><td>{row['close']:.2f}</td><td style='color:{chg_color}'>{chg:+.2f}%</td></tr>"
    recent_html += "</table>"

    body = f"""
    <h2>{strategy_action}</h2>
    <p><b>股票:</b> {STOCK_NAME}({STOCK_CODE}) | 数据日期: {data_date}</p>
    <p><b>昨日收盘:</b> ¥{signal['close']:.2f}（{'涨' if signal['pct_chg'] >=0 else '跌'}{abs(signal['pct_chg']):.2f}%），MA10 ¥{signal['ma']:.2f}，价差 {gap:+.2f}</p>
    <hr>
    <p><b>你的状态:</b> {'已持仓' if USER_HOLDING else '空仓'}</p>
    <p><b>建议操作:</b> {personal_action}</p>
    <p>{advice}</p>
    <hr>
    <p><b>策略详情:</b> {strategy_action} — {detail}</p>
    <hr>
    <p><b>最近 10 个交易日:</b></p>
    {recent_html}
    <hr>
    <p style='color:#888;font-size:12px'>本邮件由量化策略自动生成，仅供参考，不构成投资建议。</p>
    """

    return subject, body


def send_email(subject, body):
    cfg = EmailConfig
    msg = MIMEMultipart('alternative')
    msg['From'] = cfg.SENDER_EMAIL
    msg['To'] = ','.join(cfg.RECEIVER_EMAILS)
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html', 'utf-8'))

    all_recipients = cfg.RECEIVER_EMAILS + cfg.BCC_EMAILS
    try:
        with smtplib.SMTP(cfg.SMTP_SERVER, cfg.SMTP_PORT, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(cfg.SENDER_EMAIL, cfg.SENDER_PASSWORD)
            smtp.sendmail(cfg.SENDER_EMAIL, all_recipients, msg.as_string())
        print(f"邮件发送成功 → {', '.join(all_recipients)}")
    except Exception as e:
        print(f"邮件发送失败: {e}")


def do_check():
    now = datetime.now()
    print(f"{now.strftime('%Y-%m-%d %H:%M:%S')} — 执行检查")
    df = fetch_data()
    if df is None or df.empty:
        print("数据获取失败")
        return
    signal = get_signal(df)
    subject, body = build_email(signal)
    print(f"信号: {subject}")
    send_email(subject, body)


def sleep_until_next():
    now = datetime.now()
    target = now.replace(hour=HOUR, minute=MINUTE, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    while target.weekday() >= 5:
        target += timedelta(days=1)
    seconds = (target - now).total_seconds()
    print(f"下次执行: {target.strftime('%Y-%m-%d %H:%M:%S')} (等待 {seconds/60:.0f} 分钟)")
    time.sleep(seconds)


if __name__ == '__main__':
    print(f"MA10 策略守护进程启动 (每交易日 {HOUR:02d}:{MINUTE:02d})")
    print("按 Ctrl+C 停止")
    do_check()
    while True:
        try:
            sleep_until_next()
            do_check()
        except KeyboardInterrupt:
            print("\n已停止")
            break
        except Exception as e:
            print(f"异常: {e}, 60秒后重试")
            time.sleep(60)
