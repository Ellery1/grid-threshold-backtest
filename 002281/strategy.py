import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import tushare as ts
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

ts.set_token(os.getenv('TUSHARE_TOKEN'))
pro = ts.pro_api()

STOCK = 'sz002281'
INIT_CASH = 100000
COMMISSION = 0.001

TRAIN_START = '2024-02-01'
TRAIN_END = '2025-07-31'
VAL_START = '2025-08-01'
VAL_END = '2026-05-07'


def fetch_data(start_date, end_date):
    ts_code = '002281.SZ'
    raw = pro.daily(ts_code=ts_code, start_date=start_date.replace('-', ''),
                    end_date=end_date.replace('-', ''), adj='qfq')
    if raw.empty:
        return None
    raw['trade_date'] = pd.to_datetime(raw['trade_date'])
    raw = raw.sort_values('trade_date').set_index('trade_date')
    return raw[['open', 'close', 'high', 'low', 'vol', 'pct_chg']]


def calc_metrics(trades, final_value, days):
    complete_trades = [t for t in trades if 'sell_date' in t]
    total_return = (final_value - INIT_CASH) / INIT_CASH * 100
    if days > 0:
        annual_return = ((final_value / INIT_CASH) ** (365 / days) - 1) * 100
    else:
        annual_return = 0

    profitable = [t for t in complete_trades if t.get('profit', 0) > 0]
    win_rate = len(profitable) / len(complete_trades) * 100 if complete_trades else 0

    if complete_trades:
        hold_days = [(t['sell_date'] - t['buy_date']).days for t in complete_trades]
        avg_hold = sum(hold_days) / len(hold_days)
    else:
        avg_hold = 0

    return {
        'total_return': total_return,
        'annual_return': annual_return,
        'win_rate': win_rate,
        'trade_count': len(complete_trades),
        'avg_hold_days': avg_hold
    }


def backtest(data, signal_func, params):
    cash = INIT_CASH
    shares = 0
    holding = False
    entry_price = 0
    entry_date = None
    peak_since_entry = 0
    trades = []
    daily_value = []

    for i in range(1, len(data)):
        prev_row = data.iloc[i - 1]
        curr_row = data.iloc[i]
        curr_date = data.index[i]

        signal = signal_func(data, i, holding, peak_since_entry, entry_price, params)
        action, action_price = signal

        if action == 'buy' and not holding:
            action_price = round(action_price, 2)
            shares = int(cash / (action_price * (1 + COMMISSION)))
            if shares > 0:
                cost = shares * action_price * (1 + COMMISSION)
                cash -= cost
                holding = True
                entry_price = action_price
                entry_date = curr_date
                peak_since_entry = action_price
                trades.append({'buy_date': curr_date, 'buy_price': action_price, 'shares': shares})

        elif action == 'sell' and holding:
            action_price = round(action_price, 2)
            revenue = shares * action_price * (1 - COMMISSION)
            cash += revenue
            trades[-1]['sell_date'] = curr_date
            trades[-1]['sell_price'] = action_price
            trades[-1]['profit'] = revenue - trades[-1].get('cost_override',
                                                             shares * trades[-1]['buy_price'] * (1 + COMMISSION))
            holding = False
            entry_price = 0
            entry_date = None
            peak_since_entry = 0

        if holding and i > 0:
            peak_since_entry = max(peak_since_entry, curr_row['high'])

        daily_value.append({'date': curr_date, 'value': cash + (shares * curr_row['close'] if holding else 0)})

    final_value = daily_value[-1]['value'] if daily_value else INIT_CASH
    days = (data.index[-1] - data.index[0]).days
    return final_value, trades, days


def signal_ma(data, i, holding, peak_since_entry, entry_price, params):
    N = params['N']
    price = data.iloc[i]['open']
    close_yesterday = data.iloc[i - 1]['close']
    close_today = data.iloc[i]['close']
    ma_val = data['close'].rolling(N).mean().iloc[i - 1]

    if not holding and close_today > ma_val and close_yesterday <= ma_val:
        return 'buy', price
    elif holding and close_today < ma_val:
        return 'sell', price
    return 'hold', price


def signal_momentum(data, i, holding, peak_since_entry, entry_price, params):
    N1 = params['N1']
    X = params['X']
    price = data.iloc[i]['open']
    curr_close = data.iloc[i]['close']
    vol_today = data.iloc[i]['vol']
    vol_ma = data['vol'].rolling(20).mean().iloc[i - 1]

    if not holding:
        highest_n = data['close'].iloc[max(0, i - N1):i].max()
        if curr_close >= highest_n and vol_today > 1.5 * vol_ma:
            return 'buy', price
    elif holding and peak_since_entry > 0:
        stop_price = peak_since_entry * (1 - X)
        if curr_close < stop_price:
            return 'sell', price
    return 'hold', price


def signal_golden_cross(data, i, holding, peak_since_entry, entry_price, params):
    short = params['short']
    long = params['long']
    price = data.iloc[i]['open']
    close = data.iloc[i]['close']
    vol_today = data.iloc[i]['vol']

    ma_s = data['close'].rolling(short).mean()
    ma_l = data['close'].rolling(long).mean()
    vol_ma5 = data['vol'].rolling(5).mean()

    golden = (ma_s.iloc[i - 1] > ma_l.iloc[i - 1]) and (ma_s.iloc[i - 2] <= ma_l.iloc[i - 2])
    dead = (ma_s.iloc[i - 1] < ma_l.iloc[i - 1]) and (ma_s.iloc[i - 2] >= ma_l.iloc[i - 2])

    if not holding and golden and vol_today > vol_ma5.iloc[i - 1]:
        return 'buy', price
    elif holding and dead:
        return 'sell', price
    return 'hold', price


def run_strategy(data, signal_func, param_grid, strategy_name):
    best_train_return = -float('inf')
    best_params = None
    best_train_trades = None

    for params in param_grid:
        final_value, trades, days = backtest(data.loc[TRAIN_START:TRAIN_END].copy(), signal_func, params)
        total_return = (final_value - INIT_CASH) / INIT_CASH * 100
        if total_return > best_train_return:
            best_train_return = total_return
            best_params = params
            best_train_trades = trades

    train_val, train_trades, train_days = backtest(data.loc[TRAIN_START:TRAIN_END].copy(),
                                                     signal_func, best_params)
    train_metrics = calc_metrics(train_trades, train_val, train_days)

    val_val, val_trades, val_days = backtest(data.loc[VAL_START:VAL_END].copy(),
                                               signal_func, best_params)
    val_metrics = calc_metrics(val_trades, val_val, val_days)

    overfit_ratio = val_metrics['total_return'] / train_metrics['total_return'] * 100 if train_metrics['total_return'] > 0.01 else 0
    if overfit_ratio >= 50:
        overfit_label = '通过'
    elif overfit_ratio >= 30:
        overfit_label = '警戒'
    else:
        overfit_label = '失败'

    print(f"\n===== 策略 {strategy_name} =====")
    print(f"最优参数: {best_params}")
    print(f"训练集 ({TRAIN_START} ~ {TRAIN_END}):")
    print(f"  收益率={train_metrics['total_return']:.2f}% 年化={train_metrics['annual_return']:.2f}% "
          f"交易{train_metrics['trade_count']}次 胜率{train_metrics['win_rate']:.0f}% "
          f"均持{train_metrics['avg_hold_days']:.0f}天")
    print(f"验证集 ({VAL_START} ~ {VAL_END}):")
    print(f"  收益率={val_metrics['total_return']:.2f}% 年化={val_metrics['annual_return']:.2f}% "
          f"交易{val_metrics['trade_count']}次 胜率{val_metrics['win_rate']:.0f}% "
          f"均持{val_metrics['avg_hold_days']:.0f}天")
    print(f"过拟合检测: {overfit_label} (验证/训练={overfit_ratio:.0f}%)")

    return {
        'name': strategy_name,
        'params': best_params,
        'val_return': val_metrics['total_return'],
        'val_annual': val_metrics['annual_return'],
        'train_return': train_metrics['total_return'],
        'train_annual': train_metrics['annual_return'],
        'val_trades': val_trades,
        'val_metrics': val_metrics,
        'train_trades': train_trades,
        'train_metrics': train_metrics,
        'overfit_label': overfit_label,
        'overfit_ratio': overfit_ratio,
        'signal_func': signal_func,
    }


def print_trade_detail(trades, label):
    complete = [t for t in trades if 'sell_date' in t]
    if not complete:
        print(f"\n{label}: 无完整交易")
        return
    print(f"\n{label} ({len(complete)} 轮):")
    print(f"{'买入日期':<14} {'买入价':<8} {'卖出日期':<14} {'卖出价':<8} {'持仓':<6} {'盈亏'}")
    for t in complete:
        bd = t['buy_date'].strftime('%Y-%m-%d')
        sd = t['sell_date'].strftime('%Y-%m-%d')
        days = (t['sell_date'] - t['buy_date']).days
        profit = t.get('profit', 0)
        cost = t['shares'] * t['buy_price'] * (1 + COMMISSION)
        pct = profit / cost * 100 if cost > 0 else 0
        print(f"{bd:<14} ¥{t['buy_price']:<7.2f} {sd:<14} ¥{t['sell_price']:<7.2f} {days:>4}天 ¥{profit:+.0f}({pct:+.1f}%)")


def main():
    print("002281 光迅科技 量化策略回测")
    print("=" * 60)

    all_data = fetch_data('2024-02-01', '2026-05-07')
    if all_data is None or all_data.empty:
        print("数据获取失败")
        return
    print(f"数据: {len(all_data)}条, {all_data.index[0].strftime('%Y-%m-%d')} ~ {all_data.index[-1].strftime('%Y-%m-%d')}")
    print(f"价格区间: ¥{all_data['close'].min():.2f} ~ ¥{all_data['close'].max():.2f}")

    results = []

    param_a = [{'N': n} for n in [10, 20, 30, 60, 90, 120]]
    results.append(run_strategy(all_data, signal_ma, param_a, 'A-均线趋势'))

    param_b = [{'N1': n1, 'X': x} for n1 in [20, 40, 60] for x in [0.05, 0.08, 0.10, 0.12, 0.15]]
    results.append(run_strategy(all_data, signal_momentum, param_b, 'B-动量突破'))

    param_c = [{'short': s, 'long': l} for s in [5, 8, 10] for l in [20, 30, 40, 60] if s < l]
    results.append(run_strategy(all_data, signal_golden_cross, param_c, 'C-金叉死叉'))

    results.sort(key=lambda x: x['val_return'], reverse=True)

    print("\n" + "=" * 60)
    print("最终排名 (按验证集收益率)")
    print("=" * 60)
    for i, r in enumerate(results):
        print(f"{i + 1}. {r['name']}: 验证集 {r['val_return']:.2f}% (训练集 {r['train_return']:.2f}%), "
              f"参数={r['params']}, 过拟合={r['overfit_label']}")

    best = results[0]
    print(f"\n最优策略: {best['name']}, 参数: {best['params']}")

    print("\n----- 最优策略 训练集 交易明细 -----")
    print_trade_detail(best['train_trades'], '训练集')
    print("\n----- 最优策略 验证集 交易明细 -----")
    print_trade_detail(best['val_trades'], '验证集')

    return best


if __name__ == '__main__':
    main()
