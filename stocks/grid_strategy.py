import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from stocks.base import BaseStrategy, Signal


class GridThresholdStrategy(BaseStrategy):
    def param_grid(self, df: pd.DataFrame) -> list[dict]:
        lo = float(df['low'].min())
        hi = float(df['high'].max())
        p50 = float(df['close'].median())

        if p50 <= 5:
            base_step = 0.01
        elif p50 <= 10:
            base_step = 0.02
        elif p50 <= 50:
            base_step = 0.1
        elif p50 <= 100:
            base_step = 0.5
        else:
            base_step = 1

        candidates = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5]
        step_idx = candidates.index(base_step) if base_step in candidates else 0

        while step_idx < len(candidates):
            step = candidates[step_idx]
            window_lo = round(lo, 2)
            window_hi = round(hi, 2)
            rng = np.round(np.arange(window_lo, window_hi + step, step), 2)
            total = len(rng) * (len(rng) - 1) // 2
            if total <= 50000:
                break
            step_idx += 1

        result = []
        for b in rng:
            for s in rng:
                if s > b:
                    result.append({'B': float(b), 'S': float(s)})
        return result

    def generate_signal(self, df: pd.DataFrame, params: dict = None) -> Signal:
        latest = df.iloc[-1]
        close = float(latest['close'])
        low = float(latest['low'])
        high = float(latest['high'])
        pct_chg = float(latest.get('pct_chg', 0))

        if params is None:
            return Signal(
                action='hold',
                action_price=close,
                details={
                    'close': close, 'low': low, 'high': high,
                    'pct_chg': pct_chg,
                    'date': str(df.index[-1].date()),
                },
            )

        B = params['B']
        S = params['S']

        reached_buy = low < B
        reached_sell = high > S

        if reached_buy and reached_sell:
            action = 'volatile'
            action_detail = f'日内振幅覆盖买卖线（低 ¥{low:.2f} < B ¥{B:.2f}，高 ¥{high:.2f} > S ¥{S:.2f}）'
        elif reached_buy:
            action = 'buy'
            action_detail = f'最低价 ¥{low:.2f} 跌破买入线 ¥{B:.2f}'
        elif reached_sell:
            action = 'sell'
            action_detail = f'最高价 ¥{high:.2f} 突破卖出线 ¥{S:.2f}'
        elif close < B:
            action = 'near_buy'
            action_detail = f'收盘 ¥{close:.2f} 低于买入线 ¥{B:.2f}，但今日最低未触发'
        elif close > S:
            action = 'near_sell'
            action_detail = f'收盘 ¥{close:.2f} 高于卖出线 ¥{S:.2f}，但今日最高未触发'
        else:
            action = 'hold'
            gap_buy = close - B
            gap_sell = S - close
            action_detail = f'震荡区间内（距买线 {gap_buy:+.2f}，距卖线 {gap_sell:+.2f}）'

        return Signal(
            action=action,
            action_price=close,
            details={
                'B': B, 'S': S,
                'close': close, 'low': low, 'high': high,
                'pct_chg': pct_chg,
                'action_detail': action_detail,
                'date': str(df.index[-1].date()),
                'recent': df.tail(10)[['open', 'close', 'high', 'low', 'pct_chg']],
            },
        )

    def backtest(
        self, df: pd.DataFrame, params: dict
    ) -> tuple[float, list[dict], int]:
        B = params['B']
        S = params['S']

        fixed_capital = self.init_cash
        shares_per_trade = int(fixed_capital / (B * (1 + self.commission)))
        if shares_per_trade <= 0:
            return float(self.init_cash), [], 0

        shares = 0
        holding = False
        total_profit = 0.0
        last_buy_cost = 0.0
        cash = float(fixed_capital)
        trades = []

        for i, row in df.iterrows():
            low_price = float(row['low'])
            high_price = float(row['high'])
            close_price = float(row['close'])

            if not holding:
                if low_price < B:
                    shares = shares_per_trade
                    last_buy_cost = shares * B * (1 + self.commission)
                    cash -= last_buy_cost
                    holding = True
                    trades.append({
                        'buy_date': i,
                        'buy_price': B,
                        'buy_day_low': low_price,
                        'shares': shares,
                    })
            else:
                if high_price > S:
                    revenue = shares * S * (1 - self.commission)
                    cash += revenue
                    profit = revenue - last_buy_cost
                    total_profit += profit
                    trades[-1]['sell_date'] = i
                    trades[-1]['sell_price'] = S
                    trades[-1]['sell_day_high'] = high_price
                    trades[-1]['profit'] = profit
                    shares = 0
                    holding = False

        if holding:
            final_value = cash + shares * float(df.iloc[-1]['close'])
        else:
            final_value = cash + total_profit

        days = (df.index[-1] - df.index[0]).days
        return final_value, trades, days

    def describe_params(self, params: dict) -> str:
        return f"买入阈值 ¥{params['B']:.2f} / 卖出阈值 ¥{params['S']:.2f}"

    def calc_metrics(
        self, final_value: float, trades: list[dict], days: int
    ) -> dict:
        complete = [t for t in trades if 'sell_date' in t]
        total_return = (final_value - self.init_cash) / self.init_cash * 100
        if days > 0 and final_value > 0:
            annual_return = (
                (final_value / self.init_cash) ** (365 / days) - 1
            ) * 100
        else:
            annual_return = 0.0

        profitable = [t for t in complete if t.get('profit', 0) > 0]
        win_rate = len(profitable) / len(complete) * 100 if complete else 0.0

        if complete:
            hold_days = [
                (t['sell_date'] - t['buy_date']).days for t in complete
            ]
            avg_hold = sum(hold_days) / len(hold_days)
        else:
            avg_hold = 0.0

        return {
            'total_return': total_return,
            'annual_return': annual_return,
            'win_rate': win_rate,
            'trade_count': len(complete),
            'avg_hold_days': avg_hold,
            'final_value': final_value,
        }

    def optimize(
        self, df: pd.DataFrame, param_grid: list[dict] = None
    ) -> tuple[dict, float, list[dict]]:
        if param_grid is None:
            param_grid = self.param_grid(df)

        best_return = -float('inf')
        best_params = None
        best_trades = None
        total = len(param_grid)

        step = 0.01
        for i in range(1, len(param_grid)):
            if param_grid[i]['B'] != param_grid[0]['B']:
                step = param_grid[i]['B'] - param_grid[0]['B']
                break

        for idx, params in enumerate(param_grid):
            final_value, trades, _ = self.backtest(df, params)
            total_return = (final_value - self.init_cash) / self.init_cash * 100

            if total_return > best_return:
                best_return = total_return
                best_params = params
                best_trades = trades

            if (idx + 1) % 500 == 0 or idx == total - 1:
                print(
                    f"  进度: {idx + 1}/{total} "
                    f"({(idx + 1) / total * 100:.1f}%), "
                    f"步长={step:.2f}, "
                    f"当前最优: B={best_params['B']:.2f} S={best_params['S']:.2f} "
                    f"收益率={best_return:.2f}%",
                    flush=True,
                )

        return best_params, best_return, best_trades
