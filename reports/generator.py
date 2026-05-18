import os
from datetime import datetime
from collections import Counter
import numpy as np


class ReportGenerator:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate_backtest_report(
        self,
        stock_code: str,
        stock_name: str,
        strategy_name: str,
        params: dict,
        param_desc: str,
        param_grid_info: dict,
        result: dict,
        trades: list[dict],
        pricing_model_desc: str,
        start_date: str,
        end_date: str,
        trading_days: int,
    ) -> str:
        today = datetime.now().strftime('%Y-%m-%d')
        filename = f"{stock_code}_{stock_name}_回测报告_{today}.md"
        filepath = os.path.join(self.output_dir, filename)

        complete_trades = [t for t in trades if 'sell_date' in t]

        lines = []
        lines.append(
            f"# {stock_code} {stock_name} 量化策略回测报告\n"
        )
        lines.append(f"> 生成日期：{today}  ")
        lines.append(f"> 股票代码：{stock_code}（{stock_name}）  ")
        lines.append(
            f"> 回测期间：{start_date} ~ {end_date}"
            f"（{trading_days} 个交易日）  "
        )
        lines.append(f"> 策略类型：{strategy_name}  \n")

        lines.append("---\n")
        lines.append("## 一、参数搜索过程\n")
        lines.append(f"- 搜索窗口：({param_grid_info['window_lo']}, "
                     f"{param_grid_info['window_hi']})")
        lines.append(f"- 步长：{param_grid_info['step']}")
        lines.append(
            f"- 有效组合数：{param_grid_info['combinations']} 组\n"
        )
        lines.append(f"- 最优解：{param_desc}")
        lines.append(
            f"- 最大收益率：**{result['total_return']:.2f}%**"
        )
        if 'score' in result:
            lines.append(f"- 稳定性分：{result.get('stability', '—')}  "
                         f"| 加权分数：**{result['score']}**\n")
        else:
            lines.append("")

        lines.append("---\n")
        lines.append("## 二、回测绩效\n")
        lines.append("| 指标 | 数值 |")
        lines.append("|------|------|")
        lines.append(f"| 回测期间 | {start_date} ~ {end_date} |")
        lines.append(f"| 交易日数 | {trading_days} 天 |")
        lines.append(f"| 初始本金 | ¥{100000:,.0f} |")
        lines.append(
            f"| 最终资金 | ¥{result['final_value']:,.2f} |"
        )
        lines.append(
            f"| 总收益率 | **{result['total_return']:.2f}%** |"
        )
        lines.append(
            f"| 年化收益率（约） | **~{result['annual_return']:.0f}%** |"
        )
        lines.append(
            f"| 完整交易轮次 | **{result['trade_count']} 轮**"
        )
        if 'score' in result:
            lines.append(
                f"| 稳定性分 | {result['stability']:.2f} "
                f"（0.4 + 0.6 × min({result['trade_count']}/10, 1)） |"
            )
            lines.append(
                f"| 加权分数（score） | **{result['score']}** "
                f"（收益率 × 稳定性分） |"
            )
        lines.append(
            f"| 平均每轮持仓天数 | ~{result['avg_hold_days']:.1f} 个交易日 |"
        )

        if complete_trades:
            profits = [t.get('profit', 0) for t in complete_trades]
            avg_profit = sum(profits) / len(profits)
            lines.append(
                f"| 平均每轮收益 | ¥{avg_profit:,.0f}"
                f"（约 {avg_profit / 100000 * 100:.1f}%） |"
            )
            max_hold = max(
                (t['sell_date'] - t['buy_date']).days
                for t in complete_trades
            )
            lines.append(
                f"| 最长单轮持仓 | {max_hold} 天 |"
            )
        lines.append("")

        lines.append("---\n")
        lines.append("## 三、交易明细\n")
        lines.append(
            "| 轮次 | 买入日期 | 买入价 | 买入日最低 | "
            "卖出日期 | 卖出价 | 卖出日最高 | 持仓天数 | 盈亏 |"
        )
        lines.append(
            "|------|---------|--------|-----------|"
            "---------|--------|-----------|---------|------|"
        )
        for idx, t in enumerate(complete_trades):
            bd = t['buy_date'].strftime('%Y-%m-%d')
            sd = t['sell_date'].strftime('%Y-%m-%d')
            hold = (t['sell_date'] - t['buy_date']).days
            profit = t.get('profit', 0)
            bl = t.get('buy_day_low', t['buy_price'])
            sh = t.get('sell_day_high', t['sell_price'])
            lines.append(
                f"| {idx + 1} | {bd} | ¥{t['buy_price']:.2f} | "
                f"¥{bl:.2f} | {sd} | ¥{t['sell_price']:.2f} | "
                f"¥{sh:.2f} | {hold} | ¥{profit:+,.0f} |"
            )

        if len(trades) > len(complete_trades):
            last = trades[-1]
            if 'sell_date' not in last:
                bd = last['buy_date'].strftime('%Y-%m-%d')
                lines.append(
                    f"| *持仓中* | {bd} | ¥{last['buy_price']:.2f} | "
                    f"— | — | — | — | — | — |"
                )
        lines.append("")

        lines.append("---\n")
        lines.append("## 四、持仓时长分布\n")
        if complete_trades:
            hold_bins = Counter()
            for t in complete_trades:
                days = (t['sell_date'] - t['buy_date']).days
                if days == 1:
                    hold_bins['1 天'] += 1
                elif days <= 3:
                    hold_bins['2~3 天'] += 1
                elif days <= 10:
                    hold_bins['4~10 天'] += 1
                elif days <= 35:
                    hold_bins['11~35 天'] += 1
                else:
                    hold_bins['36 天+'] += 1

            lines.append("| 持仓天数 | 轮次数 |")
            lines.append("|---------|--------|")
            for label, count in hold_bins.items():
                lines.append(f"| {label} | {count} 轮 |")
        lines.append("")

        lines.append("---\n")
        lines.append("## 五、风险提示\n")
        lines.append(
            "1. **过拟合风险**：本策略参数通过网格搜索在历史数据上优化得出，"
            "未来市场环境变化可能导致参数失效"
        )
        lines.append(
            "2. **流动性风险**：实际交易中可能面临滑点，"
            "尤其在小盘股流动性不足时"
        )
        lines.append(
            "3. **单边市风险**：如果股价长期脱离交易区间，"
            "策略将持续空仓/套牢，无法获利"
        )
        lines.append(
            "4. **成交模型差异**：回测假设限价条件单精确成交，"
            "实盘中存在未成交/部分成交的可能性"
        )
        lines.append(
            "5. **本报告仅供研究参考，不构成投资建议**"
        )

        content = '\n'.join(lines) + '\n'
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"报告已生成: {filepath}")
        return filepath

    def generate_comparison_report(
        self,
        stock_code: str,
        stock_name: str,
        scenarios: list[dict],
    ) -> str:
        today = datetime.now().strftime('%Y-%m-%d')
        filename = f"{stock_code}_{stock_name}_参数对比报告_{today}.md"
        filepath = os.path.join(self.output_dir, filename)

        lines = []
        lines.append(
            f"# {stock_code} {stock_name} 参数对比报告\n"
        )
        lines.append(f"> 生成日期：{today}\n")

        lines.append("## 收益率总览\n")
        lines.append(
            "| 方案 | 参数 | 区间 | 交易日 | "
            "轮次 | 收益率 | 年化 |"
        )
        lines.append(
            "|------|------|------|--------|"
            "------|--------|------|"
        )
        for s in scenarios:
            lines.append(
                f"| **{s['label']}** | {s['param_desc']} | "
                f"{s.get('period', '—')} | {s.get('trading_days', '—')} | "
                f"{s['result']['trade_count']} | "
                f"**{s['result']['total_return']:.2f}%** | "
                f"~{s['result']['annual_return']:.0f}% |"
            )
        lines.append("")

        for s in scenarios:
            lines.append(f"---\n")
            lines.append(
                f"### {s['label']} — {s['param_desc']}\n"
            )
            trades = s.get('trades', [])
            complete = [
                t for t in trades if 'sell_date' in t
            ]
            if not complete:
                lines.append("无完整交易\n")
                continue

            lines.append(
                "| 轮次 | 买入日期 | 买入日最低 | "
                "卖出日期 | 卖出日最高 | 持仓天数 |"
            )
            lines.append(
                "|------|---------|-----------|"
                "---------|-----------|---------|"
            )
            for idx, t in enumerate(complete):
                bd = t['buy_date'].strftime('%Y-%m-%d')
                sd = t['sell_date'].strftime('%Y-%m-%d')
                hold = (t['sell_date'] - t['buy_date']).days
                bl = t.get('buy_day_low', t['buy_price'])
                sh = t.get('sell_day_high', t['sell_price'])
                lines.append(
                    f"| {idx + 1} | {bd} | ¥{bl:.2f} | "
                    f"{sd} | ¥{sh:.2f} | {hold} |"
                )
            lines.append("")

        lines.append("---\n")
        lines.append("## 风险提示\n")
        lines.append("本报告仅供研究参考，不构成投资建议。")

        content = '\n'.join(lines) + '\n'
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"对比报告已生成: {filepath}")
        return filepath
