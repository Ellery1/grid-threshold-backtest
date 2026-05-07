import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import GtechQuantStrategy

if __name__ == "__main__":
    # # 创建策略实例
    # strategy = GtechQuantStrategy(stock_code='sz000727', init_cash=100000)
    #
    # # 运行阈值优化
    # # start_date 和 end_date -> 回测的时间区间
    # # buy_range = (2.4, 2.6) -> 买入窗口，要在该窗口值中筛选出最好的买入值
    # # sell_range = (2.7, 2.9) -> 卖出窗口，要在该窗口值中筛选出最好的卖出值
    # # step = 0.05 -> 梯度下降的步长
    # best_buy_threshold, best_sell_threshold, best_return = strategy.optimize_thresholds(
    #     start_date='2025-01-01',
    #     end_date='2026-05-07',
    #     buy_range=(2.2, 2.8),
    #     sell_range=(2.6, 3.2),
    #     step=0.01
    # )

    # 创建策略实例
    strategy = GtechQuantStrategy(stock_code='sz002415', init_cash=100000)

    # 运行阈值优化
    best_buy_threshold, best_sell_threshold, best_return = strategy.optimize_thresholds(
        start_date='2025-01-01',
        end_date='2026-05-07',
        buy_range=(28, 36),
        sell_range=(35, 40),
        step=0.05
    )

    print(f"最终优化结果:")
    print(f"最佳买入阈值: {best_buy_threshold:.2f}")
    print(f"最佳卖出阈值: {best_sell_threshold:.2f}")
    print(f"最大收益率: {best_return:.2f}%")