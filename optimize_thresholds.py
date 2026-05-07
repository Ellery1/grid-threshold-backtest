import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import GtechQuantStrategy

if __name__ == "__main__":
    strategy = GtechQuantStrategy(stock_code='sz000727', init_cash=100000)

    best_buy_threshold, best_sell_threshold, best_return = strategy.optimize_thresholds(
        start_date='2025-01-01',
        end_date='2026-05-07'
    )

    print(f"最终优化结果:")
    print(f"最佳买入阈值: {best_buy_threshold:.2f}")
    print(f"最佳卖出阈值: {best_sell_threshold:.2f}")
    print(f"最大收益率: {best_return:.2f}%")
