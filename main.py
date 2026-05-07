import pandas as pd
import numpy as np
import tushare as ts
from datetime import datetime
import warnings
import os
from dotenv import load_dotenv

load_dotenv()

warnings.filterwarnings('ignore')

ts.set_token(os.getenv('TUSHARE_TOKEN'))
pro = ts.pro_api()


class GtechQuantStrategy:
    def __init__(self, stock_code='000727', init_cash=100000):
        self.stock_code = stock_code
        self.init_cash = init_cash
        self.data = None

    def fetch_data(self, start_date='2023-01-01', end_date=None):
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')

        self.start_date = start_date
        self.end_date = end_date

        if self.stock_code.startswith('sz'):
            ts_code = self.stock_code[2:] + '.SZ'
        elif self.stock_code.startswith('sh'):
            ts_code = self.stock_code[2:] + '.SH'
        else:
            ts_code = self.stock_code + '.SZ'

        print(f"获取股票数据: {self.stock_code}({ts_code})，时间范围: {start_date} 至 {end_date}")

        stock_data = pro.daily(
            ts_code=ts_code,
            start_date=start_date.replace('-', ''),
            end_date=end_date.replace('-', ''),
            adj='qfq'
        )

        if stock_data.empty:
            print("获取到空数据，请检查股票代码或时间范围")
            return

        stock_data.rename(columns={
            'trade_date': '日期',
            'open': '开盘',
            'close': '收盘',
            'high': '最高',
            'low': '最低',
            'vol': '成交量',
            'pct_chg': '涨跌幅'
        }, inplace=True)

        stock_data['日期'] = pd.to_datetime(stock_data['日期'])
        stock_data.set_index('日期', inplace=True)
        stock_data = stock_data.sort_index()

        required_columns = ['开盘', '收盘', '最高', '最低', '成交量', '涨跌幅']
        self.data = stock_data[required_columns]

        print(f"成功获取{self.stock_code}数据，时间范围: {start_date} 至 {end_date}")
        print(f"数据量: {len(self.data)}条")
        print(f"价格分布: 最低 ¥{self.data['最低'].min():.2f} / 最高 ¥{self.data['最高'].max():.2f} / 均值 ¥{self.data['收盘'].mean():.2f}")

    def generate_trade_log(self, start_date='2024-06-30', end_date=None, buy_threshold=2.55, sell_threshold=2.8, verbose=False):
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')

        if self.data is None:
            print("请先调用 fetch_data() 获取数据")
            return None, 0

        df = self.data.loc[start_date:end_date].copy()

        if df.empty:
            print(f"指定时间范围 {start_date} 至 {end_date} 内无数据")
            return None, 0

        fixed_capital = self.init_cash
        shares_per_trade = int(fixed_capital / (buy_threshold * 1.001))
        if shares_per_trade <= 0:
            print("资金不足以买入1股，请调整参数")
            return None, 0

        shares = 0
        holding = False
        total_profit = 0
        last_buy_cost = 0
        fund = fixed_capital
        prev_fund = fixed_capital

        trade_log = []

        for i, row in df.iterrows():
            date = i
            low_price = row['最低']
            high_price = row['最高']
            close_price = row['收盘']

            if not holding:
                if low_price < buy_threshold:
                    action = '买入'
                    shares = shares_per_trade
                    last_buy_cost = shares * buy_threshold * 1.001
                    holding = True
                else:
                    action = '观望'
            else:
                if high_price > sell_threshold:
                    action = '卖出'
                    revenue = shares * sell_threshold * 0.999
                    total_profit += revenue - last_buy_cost
                    shares = 0
                    holding = False
                else:
                    action = '持有'

            if holding:
                fund = fixed_capital + total_profit - last_buy_cost + shares * close_price
            else:
                fund = fixed_capital + total_profit

            profit_loss_rate = 0.0 if i == df.index[0] else (fund - prev_fund) / prev_fund * 100
            prev_fund = fund

            trade_log.append({
                '日期': date,
                '最低价': low_price,
                '最高价': high_price,
                '开盘价': row['开盘'],
                '收盘价': close_price,
                '操作': action,
                '资金': fund,
                '盈亏率': profit_loss_rate
            })

        trade_log_df = pd.DataFrame(trade_log)

        if verbose:
            print("\n" + "=" * 80)
            print(f"交易日志 (买入阈值: {buy_threshold}, 卖出阈值: {sell_threshold})")
            print("=" * 80)
            print(trade_log_df.to_string(index=False, formatters={
                '日期': lambda x: x.strftime('%Y-%m-%d'),
                '最低价': '{:.2f}'.format,
                '最高价': '{:.2f}'.format,
                '开盘价': '{:.2f}'.format,
                '收盘价': '{:.2f}'.format,
                '资金': '{:.2f}'.format,
                '盈亏率': '{:.2f}%'.format
            }))

        total_return = (fund - self.init_cash) / self.init_cash * 100
        if verbose:
            print(f"\n最终资金: ¥{fund:.2f}")
            print(f"总收益率: {total_return:.2f}%")

        return trade_log_df, total_return

    def optimize_thresholds(self, start_date='2024-06-30', end_date=None):
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')

        if self.data is None:
            self.fetch_data(start_date=start_date, end_date=end_date)

        if self.data is None:
            print("数据获取失败，无法优化")
            return None, None, None

        lo = self.data['最低'].min()
        hi = self.data['最高'].max()
        window_lo = np.round(lo, 2)
        window_hi = np.round(hi * 1.05, 2)

        p50 = self.data['收盘'].median()
        if p50 <= 10:
            step = 0.01
        elif p50 <= 100:
            step = 0.1
        else:
            step = 0.5

        print("===== 自动推导搜索参数 =====")
        print(f"价格分布: 最低 ¥{lo:.2f} / 中位数 ¥{p50:.2f} / 最高 ¥{hi:.2f}")
        print(f"搜索窗口: ({window_lo}, {window_hi})")
        print(f"步长: {step}  (中位数{'<10' if p50 <= 10 else '<100' if p50 <= 100 else '>=100'}，自动选择)")
        print("=============================")

        print(f"\n开始优化阈值，时间范围: {start_date} 至 {end_date}")
        print(f"买卖阈值范围: {window_lo} - {window_hi}, 步长: {step}")

        thresholds = np.round(np.arange(window_lo, window_hi + step, step), decimals=2)

        best_return = -float('inf')
        best_buy_threshold = None
        best_sell_threshold = None

        total_combinations = len(thresholds) * len(thresholds)
        print(f"总共有 {total_combinations} 种阈值组合需要测试")

        for i, buy_threshold in enumerate(thresholds):
            for j, sell_threshold in enumerate(thresholds):
                if sell_threshold <= buy_threshold:
                    continue

                progress = (i * len(thresholds) + j + 1) / total_combinations * 100

                _, total_return = self.generate_trade_log(
                    start_date=start_date,
                    end_date=end_date,
                    buy_threshold=buy_threshold,
                    sell_threshold=sell_threshold,
                    verbose=False
                )

                if total_return > best_return:
                    best_return = total_return
                    best_buy_threshold = buy_threshold
                    best_sell_threshold = sell_threshold
                    print(f"找到更好的阈值组合: 买入={buy_threshold:.2f}, 卖出={sell_threshold:.2f}, 收益率={total_return:.2f}% (进度: {progress:.1f}%)")
                elif (i * len(thresholds) + j + 1) % 10 == 0:
                    print(f"测试进度: {progress:.1f}%, 当前最佳: 买入={best_buy_threshold:.2f}, 卖出={best_sell_threshold:.2f}, 收益率={best_return:.2f}%")

        print("=" * 80)
        print("阈值优化完成")
        print(f"最佳买入阈值: {best_buy_threshold:.2f}")
        print(f"最佳卖出阈值: {best_sell_threshold:.2f}")
        print(f"最大收益率: {best_return:.2f}%")
        print("=" * 80)

        trade_log_df, _ = self.generate_trade_log(
            start_date=start_date,
            end_date=end_date,
            buy_threshold=best_buy_threshold,
            sell_threshold=best_sell_threshold,
            verbose=False
        )

        trades = trade_log_df[trade_log_df['操作'].isin(['买入', '卖出'])]
        bt = trades[trades['操作'] == '买入'].reset_index(drop=True)
        st = trades[trades['操作'] == '卖出'].reset_index(drop=True)
        rounds = min(len(bt), len(st))

        print(f"\n===== 最佳参数交易明细 ({rounds} 轮) =====")
        print(f"{'轮次':<6} {'买入日期':<8} {'买入日最低':<10} {'卖出日期':<8} {'卖出日最高':<10} {'持仓天数':<10}")
        for i in range(rounds):
            bd = bt.loc[i, '日期'].strftime('%Y-%m-%d')
            sd = st.loc[i, '日期'].strftime('%Y-%m-%d')
            bl = bt.loc[i, '最低价']
            sh = st.loc[i, '最高价']
            days = (st.loc[i, '日期'] - bt.loc[i, '日期']).days
            print(f"第{i+1:2d}轮  {bd:<14} ¥{bl:<9.2f} {sd:<14} ¥{sh:<9.2f} {days:>5}天")

        return best_buy_threshold, best_sell_threshold, best_return


def main():
    print("限价阈值网格策略系统")
    print("=" * 50)

    strategy = GtechQuantStrategy(stock_code='sz000727', init_cash=100000)

    start_date = '2024-09-01'
    end_date = '2025-09-01'
    strategy.fetch_data(start_date=start_date, end_date=end_date)

    print("\n" + "=" * 60)
    print("生成交易日志...")
    print("=" * 60)
    trade_log_df, total_return = strategy.generate_trade_log(
        start_date=start_date, end_date=end_date, verbose=True
    )

    trades = trade_log_df[trade_log_df['操作'].isin(['买入', '卖出'])]
    if len(trades) > 0:
        print(f"\n交易次数: {len(trades)}")
        print(f"收益率: {total_return:.2f}%")

    return strategy


if __name__ == "__main__":
    main()
