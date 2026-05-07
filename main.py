import pandas as pd
import numpy as np
import tushare as ts
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import warnings
import os
from dotenv import load_dotenv

load_dotenv()

warnings.filterwarnings('ignore')

ts.set_token(os.getenv('TUSHARE_TOKEN'))
pro = ts.pro_api()

plt.rcParams['font.sans-serif'] = ['SimHei']  # 显示中文
plt.rcParams['axes.unicode_minus'] = False


class GtechQuantStrategy:
    def __init__(self, stock_code='000727', init_cash=100000):
        """
        冠捷科技量化策略类

        参数:
        stock_code: 股票代码，默认冠捷科技
        init_cash: 初始资金
        """
        self.stock_code = stock_code
        self.init_cash = init_cash
        self.data = None
        self.signals = None

    def fetch_data(self, start_date='2023-01-01', end_date=None):
        """
        获取股票数据（使用tushare）

        参数:
        start_date: 开始日期
        end_date: 结束日期，默认今天
        """
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
            print(f"获取到空数据，请检查股票代码或时间范围")
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
        print(f"列: {required_columns}")
        print(f"\n价格分布分析:")
        print(f"收盘价最小值: {self.data['收盘'].min():.2f}")
        print(f"收盘价最大值: {self.data['收盘'].max():.2f}")
        print(f"收盘价平均值: {self.data['收盘'].mean():.2f}")

    def calculate_indicators(self):
        """计算技术指标"""
        if self.data is None:
            print("请先获取数据")
            return

        df = self.data.copy()

        # 1. 移动平均线
        df['MA5'] = df['收盘'].rolling(window=5).mean()
        df['MA10'] = df['收盘'].rolling(window=10).mean()
        df['MA20'] = df['收盘'].rolling(window=20).mean()
        df['MA60'] = df['收盘'].rolling(window=60).mean()

        # 2. RSI指标
        delta = df['收盘'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        # 3. 布林带
        df['BB_middle'] = df['收盘'].rolling(window=20).mean()
        bb_std = df['收盘'].rolling(window=20).std()
        df['BB_upper'] = df['BB_middle'] + 2 * bb_std
        df['BB_lower'] = df['BB_middle'] - 2 * bb_std
        df['BB_width'] = (df['BB_upper'] - df['BB_lower']) / df['BB_middle']

        # 4. MACD
        exp1 = df['收盘'].ewm(span=12, adjust=False).mean()
        exp2 = df['收盘'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_diff'] = df['MACD'] - df['MACD_signal']

        # 5. 成交量均线
        df['Volume_MA5'] = df['成交量'].rolling(window=5).mean()
        df['Volume_ratio'] = df['成交量'] / df['Volume_MA5']

        # 6. 价格动量
        df['Momentum'] = df['收盘'] - df['收盘'].shift(5)
        df['ROC'] = (df['收盘'] - df['收盘'].shift(10)) / df['收盘'].shift(10) * 100

        self.data = df
        print("技术指标计算完成")

    def generate_signals(self):
        """生成交易信号"""
        if self.data is None:
            print("请先计算指标")
            return

        df = self.data.copy()

        # 初始化信号列
        df['signal'] = 0  # 0: 持有, 1: 买入, -1: 卖出
        df['position'] = 0  # 持仓状态

        # 复合买入条件（需要满足至少3个条件）
        buy_conditions = []

        # 条件1: 短期均线上穿长期均线（金叉）
        condition1 = (df['MA5'] > df['MA20']) & (df['MA5'].shift(1) <= df['MA20'].shift(1))
        buy_conditions.append(condition1)

        # 条件2: RSI超卖反弹
        condition2 = (df['RSI'] < 35) & (df['RSI'].shift(1) < 30) & (df['RSI'] > df['RSI'].shift(1))
        buy_conditions.append(condition2)

        # 条件3: 价格突破布林带下轨（超卖反弹）
        condition3 = (df['收盘'].shift(1) < df['BB_lower'].shift(1)) & (df['收盘'] > df['BB_lower'])
        buy_conditions.append(condition3)

        # 条件4: MACD金叉
        condition4 = (df['MACD'] > df['MACD_signal']) & (df['MACD'].shift(1) <= df['MACD_signal'].shift(1))
        buy_conditions.append(condition4)

        # 条件5: 成交量放大
        condition5 = (df['Volume_ratio'] > 1.5) & (df['收盘'] > df['开盘'])
        buy_conditions.append(condition5)

        # 条件6: 动量转正
        condition6 = (df['Momentum'] > 0) & (df['ROC'] > 0)
        buy_conditions.append(condition6)

        # 综合买入信号（满足至少3个条件）
        buy_signal = sum(buy_conditions) >= 3

        # 复合卖出条件
        sell_conditions = []

        # 条件1: 短期均线下穿长期均线（死叉）
        sell_condition1 = (df['MA5'] < df['MA20']) & (df['MA5'].shift(1) >= df['MA20'].shift(1))
        sell_conditions.append(sell_condition1)

        # 条件2: RSI超买回落
        sell_condition2 = (df['RSI'] > 70) & (df['RSI'].shift(1) > 75) & (df['RSI'] < df['RSI'].shift(1))
        sell_conditions.append(sell_condition2)

        # 条件3: 价格突破布林带上轨（超买）
        sell_condition3 = (df['收盘'] > df['BB_upper']) & (df['收盘'].shift(1) <= df['BB_upper'].shift(1))
        sell_conditions.append(sell_condition3)

        # 条件4: MACD死叉
        sell_condition4 = (df['MACD'] < df['MACD_signal']) & (df['MACD'].shift(1) >= df['MACD_signal'].shift(1))
        sell_conditions.append(sell_condition4)

        # 条件5: 放量下跌
        sell_condition5 = (df['Volume_ratio'] > 1.2) & (df['收盘'] < df['开盘'])
        sell_conditions.append(sell_condition5)

        # 条件6: 动量转负
        sell_condition6 = (df['Momentum'] < 0) & (df['ROC'] < 0)
        sell_conditions.append(sell_condition6)

        # 综合卖出信号（满足至少3个条件）
        sell_signal = sum(sell_conditions) >= 3

        # 设置信号
        df.loc[buy_signal, 'signal'] = 1
        df.loc[sell_signal, 'signal'] = -1

        # 生成持仓状态（简化版，不考虑仓位管理）
        position = 0
        positions = []
        for sig in df['signal'].values:
            if sig == 1:
                position = 1
            elif sig == -1:
                position = 0
            positions.append(position)

        df['position'] = positions

        self.signals = df[['收盘', 'MA5', 'MA20', 'RSI', 'BB_upper', 'BB_lower',
                           'MACD', 'MACD_signal', 'MACD_diff', 'Volume_ratio', 'signal', 'position']]

        # 统计信号数量
        buy_count = buy_signal.sum()
        sell_count = sell_signal.sum()

        print(f"买入信号次数: {buy_count}")
        print(f"卖出信号次数: {sell_count}")

        return df

    def generate_price_threshold_signals(self, buy_threshold=2.55, sell_threshold=2.8):
        """
        生成价格阈值策略信号
        
        参数:
        buy_threshold: 买入阈值
        sell_threshold: 卖出阈值
        """
        if self.data is None:
            print("请先获取数据")
            return
        
        df = self.data.copy()
        
        # 初始化信号列
        df['signal'] = 0  # 0: 持有, 1: 买入, -1: 卖出
        df['position'] = 0  # 持仓状态
        
        # 价格阈值策略：最低价判断买入，最高价判断卖出
        buy_signal = df['最低'] < buy_threshold
        sell_signal = df['最高'] > sell_threshold
        
        # 设置信号
        df.loc[buy_signal, 'signal'] = 1
        df.loc[sell_signal, 'signal'] = -1
        
        # 生成持仓状态
        position = 0
        positions = []
        for sig in df['signal'].values:
            if sig == 1:
                position = 1
            elif sig == -1:
                position = 0
            positions.append(position)
        
        df['position'] = positions
        
        # 统计信号数量
        buy_count = buy_signal.sum()
        sell_count = sell_signal.sum()
        
        print(f"价格阈值策略 - 买入信号次数: {buy_count}")
        print(f"价格阈值策略 - 卖出信号次数: {sell_count}")
        
        return df

    def backtest(self, commission=0.001, signals=None):
        """
        回测策略

        参数:
        commission: 交易佣金
        signals: 可选，自定义信号数据框
        """
        if signals is None:
            if self.signals is None:
                print("请先生成信号")
                return None
            df = self.signals.copy()
        else:
            df = signals.copy()
        
        df = df.dropna()

        # 初始化回测变量
        cash = self.init_cash
        shares = 0
        portfolio_value = []
        returns = []
        trades = []

        position = 0
        entry_price = 0

        for i, row in df.iterrows():
            price = row['收盘']

            # 买入信号
            if row['signal'] == 1 and position == 0:
                # 计算可买股数
                shares_to_buy = int(cash / (price * (1 + commission)))
                if shares_to_buy > 0:
                    cost = shares_to_buy * price * (1 + commission)
                    cash -= cost
                    shares += shares_to_buy
                    position = 1
                    entry_price = price

                    trades.append({
                        'date': i,
                        'type': '买入',
                        'price': price,
                        'shares': shares_to_buy,
                        'value': shares_to_buy * price
                    })

            # 卖出信号
            elif row['signal'] == -1 and position == 1:
                if shares > 0:
                    revenue = shares * price * (1 - commission)
                    cash += revenue

                    trades.append({
                        'date': i,
                        'type': '卖出',
                        'price': price,
                        'shares': shares,
                        'value': shares * price,
                        'profit': (price - entry_price) * shares
                    })

                    shares = 0
                    position = 0
                    entry_price = 0

            # 计算当日资产总值
            portfolio_value.append(cash + shares * price)

            # 计算当日收益率
            if len(portfolio_value) > 1:
                daily_return = (portfolio_value[-1] - portfolio_value[-2]) / portfolio_value[-2]
                returns.append(daily_return)
            else:
                returns.append(0)

        # 计算回测结果
        df['portfolio_value'] = portfolio_value
        df['daily_return'] = returns

        # 计算最终收益
        final_value = portfolio_value[-1] if portfolio_value else self.init_cash
        total_return = (final_value - self.init_cash) / self.init_cash

        # 计算夏普比率（假设无风险利率为3%）
        if len(returns) > 1:
            annual_return = (1 + total_return) ** (252 / len(returns)) - 1
            annual_volatility = np.std(returns) * np.sqrt(252)
            sharpe_ratio = (annual_return - 0.03) / annual_volatility if annual_volatility > 0 else 0

            # 最大回撤
            cumulative = (1 + pd.Series(returns)).cumprod()
            running_max = cumulative.expanding().max()
            drawdown = (cumulative - running_max) / running_max
            max_drawdown = drawdown.min()

            # 胜率
            profitable_trades = [t for t in trades if t.get('profit', 0) > 0]
            win_rate = len(profitable_trades) / len(trades) if trades else 0
        else:
            annual_return = 0
            annual_volatility = 0
            sharpe_ratio = 0
            max_drawdown = 0
            win_rate = 0

        # 输出回测结果
        print("\n" + "=" * 50)
        print("回测结果统计")
        print("=" * 50)
        print(f"初始资金: ¥{self.init_cash:,.2f}")
        print(f"最终资产: ¥{final_value:,.2f}")
        print(f"总收益率: {total_return:.2%}")
        print(f"年化收益率: {annual_return:.2%}")
        print(f"年化波动率: {annual_volatility:.2%}")
        print(f"夏普比率: {sharpe_ratio:.2f}")
        print(f"最大回撤: {max_drawdown:.2%}")
        print(f"交易次数: {len(trades)}")
        print(f"胜率: {win_rate:.2%}")

        # 输出最近5次交易
        if trades:
            print(f"\n最近5次交易记录:")
            recent_trades = trades[-5:] if len(trades) > 5 else trades
            for trade in recent_trades:
                trade_type = trade['type']
                profit_str = f"，盈亏: ¥{trade.get('profit', 0):,.2f}" if 'profit' in trade else ""
                print(f"{trade['date'].strftime('%Y-%m-%d')} {trade_type} {trade['shares']}股 "
                      f"@¥{trade['price']:.2f}{profit_str}")

        return {
            'final_value': final_value,
            'total_return': total_return,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'trades': trades,
            'portfolio_values': df[['portfolio_value', 'daily_return']]
        }

    def plot_results(self, backtest_results=None, comparison_results=None):
        """简化后的可视化结果，只显示资金变化和收益率曲线"""
        if self.signals is None:
            print("请先生成信号")
            return
    
        # 只创建一个子图用于显示资产曲线
        fig, ax = plt.subplots(1, 1, figsize=(15, 8))
    
        if backtest_results and 'portfolio_values' in backtest_results:
            portfolio_df = backtest_results['portfolio_values']
            ax.plot(portfolio_df.index, portfolio_df['portfolio_value'],
                     label='复合策略', color='darkorange', linewidth=2)
            
            if comparison_results and 'portfolio_values' in comparison_results:
                comparison_portfolio_df = comparison_results['portfolio_values']
                ax.plot(comparison_portfolio_df.index, comparison_portfolio_df['portfolio_value'],
                         label='价格阈值策略', color='green', linewidth=2)
            
            ax.axhline(y=self.init_cash, color='gray', linestyle='--', alpha=0.5, label='初始资金')
            
            # 计算并显示收益率
            final_value = portfolio_df['portfolio_value'].iloc[-1]
            total_return = (final_value - self.init_cash) / self.init_cash * 100
            ax.set_title(f'资产变动曲线 (复合策略收益率: {total_return:.2f}%)', fontsize=14)
            
            if comparison_results and 'portfolio_values' in comparison_results:
                comparison_final_value = comparison_portfolio_df['portfolio_value'].iloc[-1]
                comparison_return = (comparison_final_value - self.init_cash) / self.init_cash * 100
                ax.text(0.02, 0.95, f'复合策略收益率: {total_return:.2f}%', 
                         transform=ax.transAxes, fontsize=12, 
                         bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
                ax.text(0.02, 0.88, f'价格阈值策略收益率: {comparison_return:.2f}%', 
                         transform=ax.transAxes, fontsize=12, 
                         bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    
        ax.set_ylabel('资产价值(元)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.show()

    def generate_trade_log(self, start_date='2024-06-30', end_date=None, buy_threshold=2.55, sell_threshold=2.8, verbose=False):
        """
        生成交易日志
        参数:
        start_date: 开始日期
        end_date: 结束日期，默认今天
        buy_threshold: 买入阈值
        sell_threshold: 卖出阈值
        verbose: 是否打印详细信息
        """
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
        profit_loss_rate = 0.0

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

            if i == df.index[0]:
                profit_loss_rate = 0.0
            else:
                profit_loss_rate = (fund - prev_fund) / prev_fund * 100

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

            if not holding:
                previous_action = '卖出' if action == '卖出' else '观望'
            else:
                previous_action = '持有'

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

        final_fund = fund
        total_return = (final_fund - self.init_cash) / self.init_cash * 100
        if verbose:
            print(f"\n最终资金: ¥{final_fund:.2f}")
            print(f"总收益率: {total_return:.2f}%")

        return trade_log_df, total_return

    def plot_trade_log(self, trade_log_df, buy_threshold=2.60, sell_threshold=2.75):
        """
        绘制交易日志图像
        参数:
        trade_log_df: 交易日志DataFrame
        buy_threshold: 买入阈值
        sell_threshold: 卖出阈值
        """
        if trade_log_df is None:
            print("交易日志为空，请先生成交易日志")
            return
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 12), sharex=True)
        
        # 绘制资金变化曲线
        ax1.plot(trade_log_df['日期'], trade_log_df['资金'], label='资金', color='blue', linewidth=2)
        ax1.axhline(y=self.init_cash, color='gray', linestyle='--', alpha=0.5, label='初始资金')
        ax1.set_title('资金变化曲线', fontsize=14)
        ax1.set_ylabel('资金(元)', fontsize=12)
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # 标记买入和卖出操作
        buy_signals = trade_log_df[trade_log_df['操作'] == '买入']
        sell_signals = trade_log_df[trade_log_df['操作'] == '卖出']
        
        ax1.scatter(buy_signals['日期'], buy_signals['资金'], marker='^', color='green', label='买入', s=100)
        ax1.scatter(sell_signals['日期'], sell_signals['资金'], marker='v', color='red', label='卖出', s=100)
        
        # 绘制价格曲线
        ax2.plot(trade_log_df['日期'], trade_log_df['收盘价'], label='收盘价', color='purple', linewidth=2)
        ax2.plot(trade_log_df['日期'], trade_log_df['最低价'], label='最低价', color='blue', linewidth=1, linestyle='--')
        ax2.plot(trade_log_df['日期'], trade_log_df['最高价'], label='最高价', color='red', linewidth=1, linestyle='--')
        
        # 添加价格阈值线
        ax2.axhline(y=buy_threshold, color='green', linestyle='--', alpha=0.5, label=f'买入阈值 ({buy_threshold})')
        ax2.axhline(y=sell_threshold, color='red', linestyle='--', alpha=0.5, label=f'卖出阈值 ({sell_threshold})')
        
        ax2.set_title('价格变化曲线', fontsize=14)
        ax2.set_ylabel('价格(元)', fontsize=12)
        ax2.set_xlabel('日期', fontsize=12)
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.show()
    
    def optimize_thresholds(self, start_date='2024-06-30', end_date=None, buy_range=(2.4, 2.6), sell_range=(2.7, 2.9), step=0.05):
        """
        优化买入和卖出阈值，最大化收益
        参数:
        start_date: 开始日期
        end_date: 结束日期，默认今天
        buy_range: 买入阈值范围 (最小值, 最大值)
        sell_range: 卖出阈值范围 (最小值, 最大值)
        step: 搜索步长
        """
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')

        print(f"开始优化阈值，时间范围: {start_date} 至 {end_date}")
        print(f"买入阈值范围: {buy_range[0]} - {buy_range[1]}, 步长: {step}")
        print(f"卖出阈值范围: {sell_range[0]} - {sell_range[1]}, 步长: {step}")

        if self.data is None:
            self.fetch_data(start_date=start_date, end_date=end_date)

        if self.data is None:
            print("数据获取失败，无法优化")
            return None, None, None
        
        # 生成阈值组合
        buy_thresholds = np.arange(buy_range[0], buy_range[1] + step, step)
        sell_thresholds = np.arange(sell_range[0], sell_range[1] + step, step)
        
        # 初始化最佳结果
        best_return = -float('inf')
        best_buy_threshold = None
        best_sell_threshold = None
        
        # 网格搜索
        total_combinations = len(buy_thresholds) * len(sell_thresholds)
        print(f"总共有 {total_combinations} 种阈值组合需要测试")
        
        for i, buy_threshold in enumerate(buy_thresholds):
            for j, sell_threshold in enumerate(sell_thresholds):
                # 确保卖出阈值大于买入阈值
                if sell_threshold <= buy_threshold:
                    continue
                
                # 计算当前组合的进度
                progress = (i * len(sell_thresholds) + j + 1) / total_combinations * 100
                
                # 生成交易日志并计算收益率
                trade_log_df, total_return = self.generate_trade_log(
                    start_date=start_date,
                    end_date=end_date,
                    buy_threshold=buy_threshold,
                    sell_threshold=sell_threshold,
                    verbose=False
                )
                
                # 更新最佳结果
                if total_return > best_return:
                    best_return = total_return
                    best_buy_threshold = buy_threshold
                    best_sell_threshold = sell_threshold
                    print(f"找到更好的阈值组合: 买入={buy_threshold:.2f}, 卖出={sell_threshold:.2f}, 收益率={total_return:.2f}% (进度: {progress:.1f}%)")
                elif (i * len(sell_thresholds) + j + 1) % 10 == 0:
                    # 每10个组合打印一次进度
                    print(f"测试进度: {progress:.1f}%, 当前最佳: 买入={best_buy_threshold:.2f}, 卖出={best_sell_threshold:.2f}, 收益率={best_return:.2f}%")
        
        print("=" * 80)
        print("阈值优化完成")
        print(f"最佳买入阈值: {best_buy_threshold:.2f}")
        print(f"最佳卖出阈值: {best_sell_threshold:.2f}")
        print(f"最大收益率: {best_return:.2f}%")
        print("=" * 80)
        
        return best_buy_threshold, best_sell_threshold, best_return

    def monitor_current_signal(self):
        """监控当前信号"""
        if self.signals is None:
            print("请先生成信号")
            return

        # 获取最新数据
        latest = self.signals.iloc[-1]

        print("\n" + "=" * 50)
        print(f"冠捷科技({self.stock_code})当前监控信号")
        print("=" * 50)
        print(f"日期: {latest.name.strftime('%Y-%m-%d')}")
        print(f"收盘价: ¥{latest['收盘']:.2f}")
        print(f"5日均线: ¥{latest.get('MA5', 0):.2f}")
        print(f"20日均线: ¥{latest.get('MA20', 0):.2f}")
        print(f"RSI: {latest.get('RSI', 0):.1f}")

        signal = latest.get('signal', 0)
        position = latest.get('position', 0)

        print(f"\n当前信号: {signal}")
        if signal == 1:
            print("建议: 🟢 买入")
            print("理由: 多个技术指标显示买入信号")
        elif signal == -1:
            print("建议: 🔴 卖出")
            print("理由: 多个技术指标显示卖出信号")
        else:
            print("建议: 🟡 持有/观望")
            print("理由: 未达到明确的买卖信号阈值")

        print(f"建议仓位: {'持仓' if position == 1 else '空仓'}")

        # 技术指标状态
        print(f"\n技术指标状态:")

        # MA状态
        if 'MA5' in latest and 'MA20' in latest:
            ma_status = "金叉" if latest['MA5'] > latest['MA20'] else "死叉"
            print(f"均线状态: {ma_status} (5日线 {'高于' if latest['MA5'] > latest['MA20'] else '低于'} 20日线)")

        # RSI状态
        if 'RSI' in latest:
            if latest['RSI'] < 30:
                rsi_status = "超卖"
            elif latest['RSI'] > 70:
                rsi_status = "超买"
            else:
                rsi_status = "正常"
            print(f"RSI状态: {rsi_status} ({latest['RSI']:.1f})")

        # MACD状态
        if 'MACD_diff' in latest:
            macd_status = "金叉" if latest['MACD_diff'] > 0 else "死叉"
            print(f"MACD状态: {macd_status}")

        print("=" * 50)


# 主程序
def main():
    print("冠捷科技量化策略系统")
    print("=" * 50)

    # 创建策略实例，使用带市场前缀的股票代码
    strategy = GtechQuantStrategy(stock_code='sz000727', init_cash=100000)

    # 获取数据
    strategy.fetch_data(start_date='2024-09-01', end_date='2025-09-01')

    # 3. 生成交易日志（按照用户最新要求）
    print("\n" + "=" * 60)
    print("生成交易日志...")
    print("=" * 60)
    start_date = '2024-09-01'
    end_date = '2025-09-01'
    trade_log_df, _ = strategy.generate_trade_log(start_date=start_date, end_date=end_date)
    
    # 绘制交易日志图像
    if trade_log_df is not None:
        print("\n生成交易日志图像...")
        strategy.plot_trade_log(trade_log_df)

    return strategy


if __name__ == "__main__":
    main()