import os
import sys
import argparse
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from data.fetcher import DataFetcher
from stocks.base import BaseStrategy
from reports.generator import ReportGenerator


def _import_stock(code):
    for sub in ['qualified', 'unqualified']:
        try:
            return __import__(f'stocks.{sub}.{code}', fromlist=['strategy', 'config'])
        except ModuleNotFoundError:
            continue
    raise ModuleNotFoundError(f"股票 {code} 不在 qualified 或 unqualified 中")


def _stock_subdir(code):
    for sub in ['qualified', 'unqualified']:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stocks', sub, code)
        if os.path.isdir(p):
            return sub
    return 'qualified'


def cmd_backtest(args):
    token = os.getenv('TUSHARE_TOKEN')
    if not token:
        print("错误: 未设置 TUSHARE_TOKEN，请在 .env 中配置")
        sys.exit(1)

    fetcher = DataFetcher(token)
    today = datetime.now().strftime('%Y-%m-%d')

    start = args.start or '2025-01-01'
    end = args.end or today

    strategy_module = _import_stock(args.code)
    config = strategy_module.config
    strategy_cls = getattr(strategy_module.strategy, args.strategy)

    print(f"\n{'=' * 60}")
    print(
        f"{config.STOCK_CODE} {config.STOCK_NAME} "
        f"— {args.strategy} 回测"
    )
    print(f"{'=' * 60}")

    print(f"\n拉取数据: {config.TS_CODE} ({start} ~ {end})")
    df = fetcher.fetch(config.TS_CODE, start, end)
    print(
        f"数据: {len(df)} 条, "
        f"{df.index[0].strftime('%Y-%m-%d')} ~ "
        f"{df.index[-1].strftime('%Y-%m-%d')}"
    )
    price_range = f"Y{df['close'].min():.2f} ~ Y{df['close'].max():.2f}"
    print(f"价格区间: {price_range}")

    strategy = strategy_cls(
        stock_code=config.STOCK_CODE,
        stock_name=config.STOCK_NAME,
        init_cash=args.cash,
        commission=args.commission,
    )

    grid = strategy.param_grid(df)
    print(f"\n搜索空间: {len(grid)} 组参数组合")

    best_params, best_return, best_trades = strategy.optimize(df, grid)
    final_value, _, days = strategy.backtest(df, best_params)
    metrics = strategy.calc_metrics(final_value, best_trades, days)

    print(f"\n{'=' * 60}")
    print("最优参数")
    print(f"{'=' * 60}")
    print(f"  {strategy.describe_params(best_params)}")
    print(f"  收益率: {metrics['total_return']:.2f}%")
    print(f"  年化: {metrics['annual_return']:.0f}%")
    print(f"  交易: {metrics['trade_count']} 轮")
    print(f"  胜率: {metrics['win_rate']:.0f}%")
    print(f"  均持: {metrics['avg_hold_days']:.1f} 天")

    if not args.no_report:
        output_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'stocks', _stock_subdir(args.code), args.code, 'reports',
        )
        report = ReportGenerator(output_dir)

        lo = float(df['low'].min())
        hi = float(df['high'].max())
        p50 = float(df['close'].median())
        step = 0.01 if p50 <= 10 else (0.05 if p50 <= 100 else 0.1)

        report.generate_backtest_report(
            stock_code=config.STOCK_CODE,
            stock_name=config.STOCK_NAME,
            strategy_name=args.strategy,
            params=best_params,
            param_desc=strategy.describe_params(best_params),
            param_grid_info={
                'window_lo': round(lo, 2),
                'window_hi': round(hi * 1.05, 2),
                'step': step,
                'combinations': len(grid),
            },
            result=metrics,
            trades=best_trades,
            pricing_model_desc='限价条件单',
            start_date=start,
            end_date=end,
            trading_days=len(df),
        )

    summary_trades = best_trades[:10] if len(best_trades) > 10 else best_trades
    complete = [t for t in summary_trades if 'sell_date' in t]
    if complete:
        print(f"\n前 {len(complete)} 轮交易明细:")
        for t in complete:
            bd = t['buy_date'].strftime('%Y-%m-%d')
            sd = t['sell_date'].strftime('%Y-%m-%d')
            hd = (t['sell_date'] - t['buy_date']).days
            print(
                f"  {bd} ~ {sd}  "
                f"{hd}天  "
                f"¥{t.get('profit', 0):+,.0f}"
            )


def cmd_compare(args):
    token = os.getenv('TUSHARE_TOKEN')
    if not token:
        print("错误: 未设置 TUSHARE_TOKEN，请在 .env 中配置")
        sys.exit(1)

    fetcher = DataFetcher(token)
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

    fetcher = DataFetcher(token)
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
