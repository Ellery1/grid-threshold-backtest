import os
import sys
import re
import time
import random
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from data.fetcher import DataFetcher
import tushare as ts
from stocks.base import BaseStrategy
from reports.generator import ReportGenerator


def _ts():
    return time.strftime('%H:%M:%S')


def _classify(r):
    """四档评级：优秀/合格/观察/不适合"""
    t = r['trades']
    a = r['annual']
    if (t >= 15 and a >= 25) or (t >= 12 and a >= 30):
        return 'excellent'
    if t >= 12 and a >= 20:
        return 'good'
    if t >= 8 and a >= 15:
        return 'ok'
    return 'bad'


_CLASSIFY_TAG = {
    'excellent': '🌟 优秀',
    'good': '✅ 合格',
    'ok': '⚠️ 观察',
    'bad': '❌ 不适合',
}


SUBDIRS = ['qualified', 'disqualified', 'candidates']
_cached_names = {}

def _get_stock_name(code):
    if code in _cached_names:
        return _cached_names[code]
    root = os.path.dirname(os.path.abspath(__file__))
    md = os.path.join(root, 'A类股_网格搜索_原始个股名录.md')
    try:
        with open(md, encoding='utf-8') as f:
            for line in f:
                if code in line and line.strip().startswith('|'):
                    parts = [p.strip() for p in line.split('|')]
                    if len(parts) >= 4 and parts[2] == code:
                        _cached_names[code] = parts[3]
                        return parts[3]
    except Exception:
        pass
    _cached_names[code] = code
    return code

_cached_industries = {}

def _get_stock_industry(code):
    if code in _cached_industries:
        return _cached_industries[code]
    root = os.path.dirname(os.path.abspath(__file__))
    md = os.path.join(root, 'A类股_网格搜索_原始个股名录.md')
    try:
        with open(md, encoding='utf-8') as f:
            for line in f:
                if code in line and line.strip().startswith('|'):
                    parts = [p.strip() for p in line.split('|')]
                    if len(parts) >= 5 and parts[2] == code:
                        _cached_industries[code] = parts[4]
                        return parts[4]
    except Exception:
        pass
    _cached_industries[code] = ''
    return ''


def _import_stock(code):
    """导入股票模块（仅用于单线程场景：grid-report/daemon）"""
    for sub in SUBDIRS:
        try:
            return __import__(f'stocks.{sub}.{code}', fromlist=['strategy', 'config'])
        except ModuleNotFoundError:
            continue
    raise ModuleNotFoundError(f"股票 {code} 不在 qualified/disqualified/candidates 中")


def _stock_subdir(code):
    for sub in SUBDIRS:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stocks', sub, code)
        if os.path.isdir(p):
            return sub
    return 'candidates'


def _ensure_stock_dir(code, start, end):
    """创建股票配置目录（若不存在则放在 candidates/ 下）"""
    for sub in SUBDIRS:
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stocks', sub, code)
        if os.path.isdir(d):
            return
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stocks', 'candidates', code)
    os.makedirs(os.path.join(d, 'reports'), exist_ok=True)
    with open(os.path.join(d, '__init__.py'), 'w', encoding='utf-8'): pass
    with open(os.path.join(d, 'strategy.py'), 'w', encoding='utf-8') as f:
        f.write('from stocks.grid_strategy import GridThresholdStrategy\n')
    ts_code = f'{code}.SH' if code.startswith(('6', '9')) else f'{code}.SZ'
    name = _get_stock_name(code)
    with open(os.path.join(d, 'config.py'), 'w', encoding='utf-8') as f:
        f.write(f'STOCK_CODE="{code}"\nSTOCK_NAME="{name}"\nTS_CODE="{ts_code}"\n'
                f'INIT_CASH=100000\nCOMMISSION=0.001\n'
                f'BACKTEST_START="{start}"\nBACKTEST_END="{end}"\n'
                f'BEST_BUY=None\nBEST_SELL=None\n')


def _run_backtest(code, args, fetcher, force_step=None):
    """回测单只股票（线程安全，不依赖 importlib）"""
    from stocks.grid_strategy import GridThresholdStrategy

    ts_code = f'{code}.SH' if code.startswith(('6', '9')) else f'{code}.SZ'
    name = _get_stock_name(code)

    df = fetcher.fetch(ts_code, args.start, args.end)

    strategy = GridThresholdStrategy(
        stock_code=code,
        stock_name=name,
        init_cash=args.cash,
        commission=args.commission,
    )

    grid = strategy.param_grid(df, force_step=force_step)

    best_params, best_score, best_return, best_trades = strategy.optimize(df, grid)
    final_value, _, days = strategy.backtest(df, best_params)
    metrics = strategy.calc_metrics(final_value, best_trades, days)

    lo = float(df['low'].min())
    hi = float(df['high'].max())
    p50 = float(df['close'].median())

    step = grid[1]['B'] - grid[0]['B'] if len(grid) > 1 else 0.01
    if step == 0:
        for i in range(1, len(grid)):
            if grid[i]['B'] != grid[0]['B']:
                step = grid[i]['B'] - grid[0]['B']
                break

    complete = [t for t in best_trades if 'sell_date' in t]
    trade_count = len(complete)
    stability = 0.4 + 0.6 * min(trade_count / 10, 1.0)
    hd = [(t['sell_date'] - t['buy_date']).days for t in complete] if complete else []
    pro = [t.get('profit', 0) for t in complete]
    avg_profit = sum(pro) / len(pro) if pro else 0

    record = {
        'code': code,
        'name': name,
        'ts_code': ts_code,
        'B': best_params['B'],
        'S': best_params['S'],
        'spread_pct': round((best_params['S'] - best_params['B']) / best_params['B'] * 100, 1),
        'return': round(metrics['total_return'], 2),
        'annual': round(metrics['annual_return'], 0),
        'score': round(best_score, 2),
        'stability': round(stability, 2),
        'final_value': round(metrics['final_value'], 2),
        'trades': metrics['trade_count'],
        'win_rate': round(metrics['win_rate'], 0),
        'avg_hold': round(metrics['avg_hold_days'], 1),
        'max_hold': max(hd) if hd else 0,
        'avg_profit': round(avg_profit),
        'price_min': lo,
        'price_max': hi,
        'price_median': p50,
        'rows': len(df),
        'combos': len(grid),
        'step': step,
        'raw_trades': best_trades,
        'param_desc': strategy.describe_params(best_params),
        'param_grid_info': {
            'window_lo': round(lo, 2),
            'window_hi': round(hi, 2),
            'step': step,
            'combinations': len(grid),
        },
    }
    metrics['score'] = record['score']
    metrics['stability'] = record['stability']
    return record, metrics, best_trades, lo, hi, p50, step, strategy, df, grid, best_params


def cmd_backtest(args):
    token = os.getenv('TUSHARE_TOKEN')
    if not token:
        print("错误: 未设置 TUSHARE_TOKEN，请在 .env 中配置")
        sys.exit(1)

    ts.set_token(token)
    fetcher = DataFetcher()
    record, metrics, best_trades, lo, hi, p50, step, strategy, df, grid, best_params = \
        _run_backtest(args.code, args, fetcher)

    print(f"\n{'=' * 60}")
    print(f"{record['code']} {record['name']} — {args.strategy} 回测")
    print(f"{'=' * 60}")
    print(f"\n数据: {len(df)} 条, {df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"价格: {lo:.2f} ~ {hi:.2f}, 中位: {p50:.2f}, 步长: {step}")
    print(f"搜索空间: {len(grid)} 组")
    print(f"\n最优参数: {strategy.describe_params(best_params)}")
    print(f"收益率: {metrics['total_return']:.2f}%, 年化: {metrics['annual_return']:.0f}%")
    print(f"交易: {metrics['trade_count']} 轮, 胜率: {metrics['win_rate']:.0f}%, 均持: {metrics['avg_hold_days']:.1f} 天")

    if not args.no_report:
        output_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'stocks', _stock_subdir(args.code), args.code, 'reports',
        )
        report = ReportGenerator(output_dir)
        report.generate_backtest_report(
            stock_code=record['code'],
            stock_name=record['name'],
            strategy_name=args.strategy,
            params=best_params,
            param_desc=strategy.describe_params(best_params),
            param_grid_info=record['param_grid_info'],
            result=metrics,
            trades=best_trades,
            pricing_model_desc='限价条件单',
            start_date=args.start,
            end_date=args.end,
            trading_days=len(df),
        )


def cmd_compare(args):
    token = os.getenv('TUSHARE_TOKEN')
    if not token:
        print("错误: 未设置 TUSHARE_TOKEN，请在 .env 中配置")
        sys.exit(1)

    ts.set_token(token)

    fetcher = DataFetcher()
    today = datetime.now().strftime('%Y-%m-%d')

    start = args.start or '2025-01-01'
    end = args.end or today

    strategy_module = _import_stock(args.code)
    config = strategy_module.config
    strategy_cls = getattr(strategy_module.strategy, args.strategy)

    print(f"\n拉取数据: {config.TS_CODE} ({start} ~ {end})")
    df = fetcher.fetch(config.TS_CODE, start, end)
    print(f"数据: {len(df)} 条, 价格: ¥{df['close'].min():.2f} ~ ¥{df['close'].max():.2f}")

    strategy = strategy_cls(
        stock_code=config.STOCK_CODE,
        stock_name=config.STOCK_NAME,
        init_cash=args.cash,
        commission=args.commission,
    )

    scenarios = []
    for param_spec in args.params:
        parts = param_spec.split(',')
        label = parts[0]
        B = float(parts[1])
        S = float(parts[2])
        p = {'B': B, 'S': S}

        final_value, trades, days = strategy.backtest(df, p)
        metrics = strategy.calc_metrics(final_value, trades, days)

        scenarios.append({
            'label': label,
            'param_desc': strategy.describe_params(p),
            'period': f'{start} ~ {end}',
            'trading_days': len(df),
            'result': metrics,
            'trades': trades,
        })

    print(f"\n{'=' * 60}")
    print("参数对比")
    print(f"{'=' * 60}")
    for s in scenarios:
        print(
            f"  {s['label']}: {s['param_desc']} → "
            f"{s['result']['total_return']:.2f}% "
            f"({s['result']['trade_count']} 轮)"
        )

    output_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'stocks', _stock_subdir(args.code), args.code, 'reports',
    )
    report = ReportGenerator(output_dir)
    report.generate_comparison_report(
        stock_code=config.STOCK_CODE,
        stock_name=config.STOCK_NAME,
        scenarios=scenarios,
    )


def _run_all_batches(args):
    """从 A类股_网格搜索_原始个股名录.md 读取所有待回测股票，分批回测。"""
    root = os.path.dirname(os.path.abspath(__file__))
    candidates_md = os.path.join(root, 'A类股_网格搜索_原始个股名录.md')
    if not os.path.exists(candidates_md):
        print(f"错误: 找不到 {candidates_md}")
        sys.exit(1)

    with open(candidates_md, encoding='utf-8') as f:
        content = f.read()

    codes = []
    in_candidates = False
    for line in content.split('\n'):
        if '全量候选清单' in line:
            in_candidates = True
            continue
        if '谨慎清单' in line:
            in_candidates = False
            continue
        if not in_candidates:
            continue
        if '🔲' in line and line.strip().startswith('|'):
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 4:
                code = parts[2]
                if code.isdigit() and len(code) == 6:
                    codes.append(code)

    # Filter out already processed stocks
    codes = [c for c in codes if _stock_subdir(c) == 'candidates']

    if not codes:
        print(f"{_ts()} 没有待回测股票（全部已完成！）")
        return

    batches = [codes[i:i + 12] for i in range(0, len(codes), 12)]
    print(f"{_ts()} 全部待回测: {len(codes)} 只, 共 {len(batches)} 批\n")

    reports_dir = os.path.join(root, 'stocks')
    existing = [f for f in os.listdir(reports_dir) if f.startswith('网格策略对比_第')]
    max_batch = 0
    for f in existing:
        m = re.search(r'第(\d+)批', f)
        if m:
            max_batch = max(max_batch, int(m.group(1)))
    start_batch = max_batch + 1
    all_failed = []

    for batch_idx, batch_codes in enumerate(batches):
        batch_num = start_batch + batch_idx
        args.codes = ','.join(batch_codes)
        args.batch = batch_num

        print(f"\n{_ts()} {'=' * 60}")
        print(f"{_ts()} 批次 {batch_num}/{start_batch + len(batches) - 1}  ({len(batch_codes)}只)")
        print(f"{_ts()} {'=' * 60}\n")

        failed = []
        try:
            failed = _run_single_batch(args) or []
        except Exception as e:
            print(f"{_ts()} 批次 {batch_num} 崩溃: {e}")
        all_failed.extend(failed)

    if all_failed:
        print(f"\n{_ts()} {'=' * 60}")
        print(f"{_ts()} 补偿轮: {len(all_failed)} 只失败股票单独重试")
        print(f"{_ts()} {'=' * 60}\n")
        retry_batch = start_batch + len(batches)
        args.codes = ','.join(all_failed)
        args.batch = retry_batch
        try:
            still_failed = _run_single_batch(args) or []
            if still_failed:
                print(f"\n{_ts()} ❌ 补偿后仍失败 {len(still_failed)} 只: {', '.join(still_failed)}")
            else:
                print(f"\n{_ts()} ✅ 补偿轮全部成功")
        except Exception as e:
            print(f"{_ts()} 补偿轮崩溃: {e}")
            print(f"{_ts()} ❌ 最终失败: {', '.join(all_failed)}")

    print(f"\n{_ts()} 全部 {len(batches)} 批完成。")


def _run_single_batch(args):
    """单批次回测（多线程并行）"""
    token = os.getenv('TUSHARE_TOKEN')
    if not token:
        print("错误: 未设置 TUSHARE_TOKEN")
        sys.exit(1)

    ts.set_token(token)

    codes = [c.strip() for c in args.codes.split(',')]

    # 第一阶段：创建目录（单线程，避免竞态）
    for code in codes:
        _ensure_stock_dir(code, args.start, args.end)
        print(f"  {_ts()} [{code}] 目录准备")

    # 第二阶段：并行回测
    results = []
    failed_codes = []
    _print_lock = threading.Lock()

    def _backtest_one(code):
        try:
            time.sleep(random.uniform(0.1, 0.8))
            fetcher = DataFetcher()
            record, metrics, best_trades, lo, hi, p50, step, strategy, df, grid, best_params = \
                _run_backtest(code, args, fetcher)
            with _print_lock:
                print(f"  {_ts()} [{code}] {len(df)}条 step={step} "
                      f"B={best_params['B']:.2f} S={best_params['S']:.2f} "
                      f"ret={metrics['total_return']:.2f}% "
                      f"score={record['score']:.2f} stb={record['stability']:.2f} "
                      f"{metrics['trade_count']}t",
                      flush=True)
            return ('ok', record)
        except Exception as e:
            with _print_lock:
                print(f"  {_ts()} [{code}] **失败**: {e}", flush=True)
            return ('fail', code)

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_backtest_one, c): c for c in codes}
        for fut in as_completed(futures):
            status, payload = fut.result()
            if status == 'ok':
                results.append(payload)
            else:
                failed_codes.append(payload)

    if failed_codes:
        print(f"\n{_ts()} ⚠️ 本批失败 {len(failed_codes)} 只: {', '.join(failed_codes)}")

    sr = sorted(results, key=lambda x: x['score'], reverse=True)
    excellent = [r for r in sr if _classify(r) == 'excellent']
    good = [r for r in sr if _classify(r) == 'good']
    ok = [r for r in sr if _classify(r) == 'ok']
    bad = [r for r in sr if _classify(r) == 'bad']

    today = datetime.now().strftime('%Y-%m-%d')
    fp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      'stocks', f'网格策略对比_第{args.batch}批_{today}.md')
    lines = [f"# 网格策略对比 — 第{args.batch}批\n",
             f"> {args.start} ~ {args.end} | 本金{args.cash:,.0f} | 佣金{args.commission:.1%} | 固定不复利\n",
             "---\n## 一、综合排名\n",
             "| # | 代码 | 名称 | B(元) | S(元) | 收益率 | 加权分数 | 年化率% | 交易(轮) | 胜率 | 均持(天) | 最长(天) | 均利(元) | 步长 | 组合数 |",
             "|---|------|------|------:|------:|------:|------:|-----:|--------:|-----:|--------:|--------:|--------:|-----:|------:|"]
    for i, r in enumerate(sr):
        lines.append(f"| {i+1} | {r['code']} | {r['name']} | "
                     f"{r['B']:.2f} | {r['S']:.2f} | "
                     f"**{r['return']:.2f}%** | **{r['score']:.2f}** | "
                     f"~{r['annual']:.0f}% | "
                     f"{r['trades']} | {r['win_rate']:.0f}% | "
                     f"{r['avg_hold']:.1f} | {r['max_hold']} | {r['avg_profit']:,.0f} | "
                     f"{r['step']} | {r['combos']} |")
    lines.append("")
    lines.append("---\n## 二、分类\n")
    lines.append(f"| 评级 | 数量 | 标的 |")
    lines.append(f"|------|------|------|")
    lines.append(f"| 🌟 优秀 | {len(excellent)} | {', '.join(r['name'] for r in excellent) if excellent else '—'} |")
    lines.append(f"| ✅ 合格 | {len(good)} | {', '.join(r['name'] for r in good) if good else '—'} |")
    lines.append(f"| ⚠️ 观察 | {len(ok)} | {', '.join(r['name'] for r in ok) if ok else '—'} |")
    lines.append(f"| ❌ 不适合 | {len(bad)} | {', '.join(r['name'] for r in bad) if bad else '—'} |")
    lines.append("")
    lines.append("---\n## 风险提示\n仅供研究参考，不构成投资建议。")

    with open(fp, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f"\n{_ts()} 报告: {os.path.basename(fp)}")
    print(f"{_ts()} 🌟{len(excellent)} ✅{len(good)} ⚠️{len(ok)} ❌{len(bad)}")

    import shutil
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stocks')
    for r in excellent + good:
        src = os.path.join(base, 'candidates', r['code'])
        dst = os.path.join(base, 'qualified', r['code'])
        if os.path.isdir(src) and not os.path.isdir(dst):
            shutil.move(src, dst)
            print(f"{_ts()} 迁移: {r['code']} → qualified")
    for r in bad + ok:
        src = os.path.join(base, 'candidates', r['code'])
        dst = os.path.join(base, 'disqualified', r['code'])
        if os.path.isdir(src) and not os.path.isdir(dst):
            shutil.move(src, dst)
            print(f"{_ts()} 迁移: {r['code']} → disqualified")

    _update_comparison_doc(results, args.batch, excellent, good, ok, bad)
    return failed_codes


def cmd_batch(args):
    """批量回测多只股票，生成个股报告 + 综合对比报告。所有回测逻辑复用 _run_backtest。"""
    if args.all:
        _run_all_batches(args)
        return

    token = os.getenv('TUSHARE_TOKEN')
    if not token:
        print("错误: 未设置 TUSHARE_TOKEN，请在 .env 中配置")
        sys.exit(1)

    ts.set_token(token)

    fetcher = DataFetcher()
    codes = [c.strip() for c in args.codes.split(',')]

    import json

    class Enc(json.JSONEncoder):
        def default(self, o):
            return o.strftime('%Y-%m-%d') if hasattr(o, 'strftime') else super().default(o)

    results = []
    for code in codes:
        print(f"\n{'#' * 60}")
        print(f"# {code}")
        print(f"{'#' * 60}")
        _ensure_stock_dir(code, args.start, args.end)
        try:
            record, metrics, best_trades, lo, hi, p50, step, strategy, df, grid, best_params = \
                _run_backtest(code, args, fetcher)

            print(f"  数据: {len(df)} 条, {lo:.2f}~{hi:.2f}, 中位={p50:.2f}, 步长={step}")
            print(f"  搜索: {len(grid)} 组")
            print(f"  最优: B={best_params['B']:.2f} S={best_params['S']:.2f} "
                  f"收益率={metrics['total_return']:.2f}% {metrics['trade_count']}轮")

            if not args.no_report:
                output_dir = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    'stocks', _stock_subdir(code), code, 'reports',
                )
                report = ReportGenerator(output_dir)
                report.generate_backtest_report(
                    stock_code=record['code'],
                    stock_name=record['name'],
                    strategy_name=args.strategy,
                    params=best_params,
                    param_desc=strategy.describe_params(best_params),
                    param_grid_info=record['param_grid_info'],
                    result=metrics,
                    trades=best_trades,
                    pricing_model_desc='限价条件单',
                    start_date=args.start,
                    end_date=args.end,
                    trading_days=len(df),
                )

            results.append(record)
        except Exception as e:
            print(f"  ERROR: {e}")

    if len(results) < 2:
        return

    sr = sorted(results, key=lambda x: x['score'], reverse=True)
    excellent = [r for r in sr if _classify(r) == 'excellent']
    good = [r for r in sr if _classify(r) == 'good']
    ok = [r for r in sr if _classify(r) == 'ok']
    bad = [r for r in sr if _classify(r) == 'bad']

    today = datetime.now().strftime('%Y-%m-%d')
    fp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      'stocks', f'网格策略对比_第{args.batch}批_{today}.md')
    lines = [f"# 网格策略对比 — 第{args.batch}批\n",
             f"> {args.start} ~ {args.end} | 本金{args.cash:,.0f} | 佣金{args.commission:.1%} | 固定不复利\n",
             "---\n## 一、综合排名\n",
             "| # | 代码 | 名称 | B(元) | S(元) | 收益率 | 加权分数 | 年化率% | 交易(轮) | 胜率 | 均持(天) | 最长(天) | 均利(元) | 箱体(元) | 步长(元) |",
             "|---|------|------|------:|------:|------:|------:|-----:|--------:|-----:|--------:|--------:|--------:|---------|--------:|"]
    for i, r in enumerate(sr):
        lines.append(f"| {i+1} | {r['code']} | {r['name']} | "
                     f"{r['B']:.2f} | {r['S']:.2f} | "
                     f"**{r['return']:.2f}%** | **{r['score']:.2f}** | "
                     f"~{r['annual']:.0f}% | "
                     f"{r['trades']} | {r['win_rate']:.0f}% | "
                     f"{r['avg_hold']:.1f} | {r['max_hold']} | {r['avg_profit']:,.0f} | "
                     f"{r['price_min']:.2f}~{r['price_max']:.2f} | {r['step']} |")
    lines.append("")
    lines.append("---\n## 二、分类评估\n")
    lines.append(f"| 评级 | 数量 | 标的 |")
    lines.append(f"|------|------|------|")
    lines.append(f"| 🌟 优秀 | {len(excellent)} | {', '.join(r['name'] for r in excellent) if excellent else '—'} |")
    lines.append(f"| ✅ 合格 | {len(good)} | {', '.join(r['name'] for r in good) if good else '—'} |")
    lines.append(f"| ⚠️ 观察 | {len(ok)} | {', '.join(r['name'] for r in ok) if ok else '—'} |")
    lines.append(f"| ❌ 不适合 | {len(bad)} | {', '.join(r['name'] for r in bad) if bad else '—'} |")
    lines.append("")

    from datetime import date as date_cls
    for i, r in enumerate(sr):
        tag = _CLASSIFY_TAG[_classify(r)]
        lines.append(f"### {i+1}. {r['code']} {r['name']} {tag}\n")
        lines.append(f"B={r['B']:.2f} S={r['S']:.2f}（{r['spread_pct']:.1f}%）| "
                     f"{r['return']:.2f}% | {r['trades']}轮 | 均持{r['avg_hold']:.1f}天 | 步长{r['step']}\n")
        comp = [t for t in r['raw_trades'] if 'sell_date' in t]
        if not comp:
            lines.append("*无交易*\n")
            continue
        lines.append("| # | 买入日 | B(元) | 卖出日 | S(元) | 持仓(天) | 盈亏(元) |")
        lines.append("|---|------|------:|------|------:|--------:|--------:|")
        for idx, t in enumerate(comp):
            bd = t['buy_date'].strftime('%Y-%m-%d') if hasattr(t['buy_date'], 'strftime') else t['buy_date'][:10]
            sd = t['sell_date'].strftime('%Y-%m-%d') if hasattr(t['sell_date'], 'strftime') else t['sell_date'][:10]
            try: hd = (date_cls.fromisoformat(sd) - date_cls.fromisoformat(bd)).days
            except: hd = 0
            lines.append(f"| {idx+1} | {bd} | {t['buy_price']:.2f} | "
                         f"{sd} | {t['sell_price']:.2f} | {hd} | {t.get('profit', 0):+,.0f} |")
        lines.append("")

    lines.append("---\n## 风险提示\n仅供研究参考，不构成投资建议。")
    with open(fp, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f"\n综合报告: {fp}")
    print(f"✅{len(good)} ⚠️{len(ok)} ❌{len(bad)}")

    import shutil
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stocks')
    for r in good:
        src = os.path.join(base, 'candidates', r['code'])
        dst = os.path.join(base, 'qualified', r['code'])
        if os.path.isdir(src) and not os.path.isdir(dst):
            shutil.move(src, dst)
            print(f"  迁移: {r['code']} → qualified")
    for r in bad:
        src = os.path.join(base, 'candidates', r['code'])
        dst = os.path.join(base, 'disqualified', r['code'])
        if os.path.isdir(src) and not os.path.isdir(dst):
            shutil.move(src, dst)
            print(f"  迁移: {r['code']} → disqualified")
    for r in ok:
        src = os.path.join(base, 'candidates', r['code'])
        dst = os.path.join(base, 'disqualified', r['code'])
        if os.path.isdir(src) and not os.path.isdir(dst):
            shutil.move(src, dst)
            print(f"  迁移: {r['code']} → disqualified (观察)")

    _update_comparison_doc(results, args.batch, excellent, good, ok, bad)


def _update_comparison_doc(results, batch, excellent, good, ok, bad):
    """追加本批结果到 A类股_网格搜索_横向对比.md"""
    cmp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'A类股_网格搜索_横向对比.md')
    if not os.path.exists(cmp):
        return

    with open(cmp, encoding='utf-8') as f:
        lines = f.read().split('\n')

    insert_pos = None
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith('|---:') or s.startswith('|:---:'):
            insert_pos = i + 1
        elif s.startswith('|') and s.count('|') >= 8 and s[2:3].isdigit():
            insert_pos = i + 1

    if insert_pos is None:
        return

    sr = sorted(results, key=lambda x: x['score'], reverse=True)

    ann_s = lambda r: f"{r['annual']:.0f}%" if r['annual'] else '—'
    new_rows = []
    for r in sr:
        name = _get_stock_name(r['code'])
        ind = _get_stock_industry(r['code'])
        step_display = round(float(r['step']), 2) if r.get('step') else 0.01
        new_rows.append(
            f"| {batch} | {r['code']} | {name} | {ind} | "
            f"{r['B']:.2f} | {r['S']:.2f} | "
            f"**{r['return']:.2f}%** | {r['stability']:.2f} | **{r['score']:.2f}** | "
            f"{ann_s(r)} | "
            f"{r['trades']} | "
            f"{step_display} | "
            f"{_CLASSIFY_TAG[_classify(r)]} |")

    for row in reversed(new_rows):
        lines.insert(insert_pos, row)

    passed = sum(1 for line in lines if '|' in line and ('🌟' in line or '✅' in line))
    excellent_count = sum(1 for line in lines if '|' in line and '🌟' in line)
    total_data = sum(1 for line in lines
                     if line.strip().startswith('|')
                     and line.strip().count('|') >= 8
                     and line.strip()[2:3].isdigit())

    for i, line in enumerate(lines):
        if '总计已回测' in line:
            lines[i] = f'- 总计已回测：**{total_data}** 只'
        if '优秀+合格' in line and '🌟' in line:
            lines[i] = f'- 🌟 优秀 + ✅ 合格：**{passed}** 只（🌟{excellent_count} + ✅{passed - excellent_count}）'

    with open(cmp, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"  {_ts()} 横向对比已更新")


def cmd_round3(args):
    """第三轮精细化回测：对 A类股_优秀及合格标的.md 中步长≥0.05的标的降档复测"""
    token = os.getenv('TUSHARE_TOKEN')
    if not token:
        print("错误: 未设置 TUSHARE_TOKEN")
        sys.exit(1)

    ts.set_token(token)

    cmp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'A类股_优秀及合格标的.md')
    if not os.path.exists(cmp):
        print(f"错误: 找不到 {cmp}")
        sys.exit(1)

    STEP_DOWNGRADE = {
        '0.05': 0.02,
        '0.1': 0.02,
        '0.2': 0.05,
        '0.5': 0.05,
    }

    codes_to_refine = []
    with open(cmp, encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if not s.startswith('|') or s.count('|') < 11:
                continue
            parts = [p.strip() for p in s.split('|')]
            code = parts[2]
            if not code.isdigit() or len(code) != 6:
                continue
            name = parts[3]
            step_str = parts[12]
            if step_str not in STEP_DOWNGRADE:
                continue
            codes_to_refine.append((code, name, step_str, STEP_DOWNGRADE[step_str]))

    print(f"{_ts()} 第三轮精细化回测：{len(codes_to_refine)} 只待降档")
    for code, name, old_step, new_step in codes_to_refine:
        print(f"  {code} {name}: step {old_step} → {new_step}")

    results = []
    _print_lock = threading.Lock()
    _file_lock = threading.Lock()

    # ── ensure header section exists once ──
    header = '| 批 | 代码 | 名称 | 行业 | B(元) | S(元) | 收益率 | 稳定性分 | 加权分数 | 年化率% | 交易(轮) | 步长 | 合格? |'
    sep   = '|:---:|---:|------|------|------:|------:|------:|------:|------:|-----:|--------:|-----:|-------|'
    need_header = True
    with open(cmp, encoding='utf-8') as f:
        for line in f:
            if '精细步长复测' in line:
                need_header = False
                break
    if need_header:
        with open(cmp, 'a', encoding='utf-8') as f:
            f.write('\n---\n\n## 🔬 精细步长复测（降档步长）\n\n')
            f.write('> 降档规则：0.05→0.02 | 0.1→0.02 | 0.2→0.05 | 0.5→0.05\n\n')
            f.write(header + '\n')
            f.write(sep + '\n')

    def _backtest_one(code, name, force_step_val):
        try:
            time.sleep(random.uniform(0.1, 0.8))
            fetcher = DataFetcher()
            record, metrics, best_trades, lo, hi, p50, step, strategy, df, grid, best_params = \
                _run_backtest(code, args, fetcher, force_step=force_step_val)
            with _print_lock:
                print(f"  {_ts()} [{code}] {len(df)}条 grid={len(grid)} "
                      f"B={best_params['B']:.2f} S={best_params['S']:.2f} "
                      f"ret={metrics['total_return']:.2f}% "
                      f"score={record['score']:.2f} stb={record['stability']:.2f} "
                      f"{metrics['trade_count']}t",
                      flush=True)
            ann_s = f"{record['annual']:.0f}%" if record['annual'] else '—'
            step_display = round(float(record['step']), 2)
            tag = _CLASSIFY_TAG[_classify(record)]
            ind = _get_stock_industry(record['code'])
            row = (
                f"| 3 | {record['code']} | {name} | {ind} | "
                f"{best_params['B']:.2f} | {best_params['S']:.2f} | "
                f"**{record['return']:.2f}%** | {record['stability']:.2f} | "
                f"**{record['score']:.2f}** | "
                f"{ann_s} | "
                f"{record['trades']} | "
                f"{step_display} | "
                f"{tag} |\n"
            )
            with _file_lock:
                with open(cmp, 'a', encoding='utf-8') as f:
                    f.write(row)
            return ('ok',)
        except Exception as e:
            with _print_lock:
                print(f"  {_ts()} [{code}] **失败**: {e}", flush=True)
            return ('fail', code)

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {}
        for code, name, old_step, new_step in codes_to_refine:
            futures[ex.submit(_backtest_one, code, name, new_step)] = (code, name)
        for fut in as_completed(futures):
            status = fut.result()
            if status[0] == 'ok':
                results.append(status[1:])

    print(f"\n{_ts()} 第三轮完成。{len(results)} 只已追加到 {os.path.basename(cmp)}")


def cmd_daemon(args):
    token = os.getenv('TUSHARE_TOKEN')
    if not token:
        print("错误: 未设置 TUSHARE_TOKEN，请在 .env 中配置")
        sys.exit(1)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from scheduler.daemon import run_daemon
    from scheduler.mailer import Mailer

    try:
        from config.email import EmailConfig
    except ImportError:
        print("错误: config/email.py 不存在，请复制 config/email.example.py 并填写配置")
        sys.exit(1)

    ts.set_token(token)
    fetcher = DataFetcher()
    mailer = Mailer(EmailConfig)

    stocks_config = []
    for spec in args.stocks:
        parts = spec.split(',')
        code = parts[0]
        strategy_name = parts[1]
        holding = len(parts) > 2 and parts[2].lower() == 'true'

        strategy_module = _import_stock(code)
        config = strategy_module.config
        strategy_cls = getattr(strategy_module.strategy, strategy_name)

        strategy = strategy_cls(
            stock_code=config.STOCK_CODE,
            stock_name=config.STOCK_NAME,
        )

        params = {}
        if (hasattr(config, 'BEST_BUY') and hasattr(config, 'BEST_SELL')
                and config.BEST_BUY is not None and config.BEST_SELL is not None):
            params = {'B': config.BEST_BUY, 'S': config.BEST_SELL}

        stocks_config.append({
            'stock_code': config.STOCK_CODE,
            'stock_name': config.STOCK_NAME,
            'ts_code': config.TS_CODE,
            'strategy': strategy,
            'strategy_params': params,
            'user_holding': holding,
            'email_subject_prefix': f'[{strategy_name}]',
        })

    run_daemon(stocks_config, fetcher, mailer, hour=args.hour, minute=args.minute)


def main():
    parser = argparse.ArgumentParser(description='量化策略平台')
    sub = parser.add_subparsers(dest='command')

    bt = sub.add_parser('backtest', help='回测 + 生成报告')
    bt.add_argument('--code', default='000727', help='股票代码 (default: 000727)')
    bt.add_argument('--strategy', default='GridThresholdStrategy', help='策略类名')
    bt.add_argument('--start', help='开始日期 (YYYY-MM-DD)')
    bt.add_argument('--end', help='结束日期 (YYYY-MM-DD)')
    bt.add_argument('--cash', type=float, default=100000, help='初始本金')
    bt.add_argument('--commission', type=float, default=0.001, help='佣金率')
    bt.add_argument('--no-report', action='store_true', help='不生成报告')
    bt.set_defaults(func=cmd_backtest)

    ba = sub.add_parser('batch', help='批量回测 + 生成综合对比报告')
    ba.add_argument('--codes', default='', help='股票代码，逗号分隔（--all 模式下可省略）')
    ba.add_argument('--batch', type=int, default=3, help='起始批次编号，用于报告命名')
    ba.add_argument('--all', action='store_true', help='从个股名录中读取所有🔲标的，分批自动回测')
    ba.add_argument('--strategy', default='GridThresholdStrategy', help='策略类名')
    ba.add_argument('--start', default='2024-06-01', help='开始日期 (YYYY-MM-DD)')
    ba.add_argument('--end', default='2026-05-16', help='结束日期 (YYYY-MM-DD)')
    ba.add_argument('--cash', type=float, default=100000, help='初始本金')
    ba.add_argument('--commission', type=float, default=0.001, help='佣金率')
    ba.add_argument('--no-report', action='store_true', help='不生成个股报告')
    ba.set_defaults(func=cmd_batch)

    r3 = sub.add_parser('round3', help='第三轮精细化回测：对优秀+合格标的强制small step')
    r3.add_argument('--start', default='2024-06-01', help='开始日期')
    r3.add_argument('--end', default='2026-05-16', help='结束日期')
    r3.add_argument('--cash', type=float, default=100000, help='初始本金')
    r3.add_argument('--commission', type=float, default=0.001, help='佣金率')
    r3.set_defaults(func=cmd_round3)

    cp = sub.add_parser('compare', help='多参数对比')
    cp.add_argument('--code', default='000727', help='股票代码')
    cp.add_argument('--strategy', default='GridThresholdStrategy', help='策略类名')
    cp.add_argument('--params', nargs='+', required=True,
                    help='参数组: "标签,B,S" 如 "最优,2.59,2.71" "实战,2.60,2.75"')
    cp.add_argument('--start', help='开始日期')
    cp.add_argument('--end', help='结束日期')
    cp.add_argument('--cash', type=float, default=100000)
    cp.add_argument('--commission', type=float, default=0.001)
    cp.set_defaults(func=cmd_compare)

    dm = sub.add_parser('daemon', help='启动定时邮件守护进程')
    dm.add_argument('--stocks', nargs='+', required=True,
                    help='股票配置: "股票代码,策略类名,是否持仓" 如 "000727,GridThresholdStrategy,true"')
    dm.add_argument('--hour', type=int, default=9)
    dm.add_argument('--minute', type=int, default=0)
    dm.set_defaults(func=cmd_daemon)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
    else:
        args.func(args)


if __name__ == '__main__':
    main()
