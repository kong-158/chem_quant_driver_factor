# Contributing

欢迎提交 issue 或 pull request，一起完善这个化工行业 driver 因子研究框架。

## 开发原则

- 保持代码清晰、模块职责明确。
- 不在 notebook 中堆核心逻辑，核心逻辑应放在 `src/`。
- 因子计算不能使用未来数据。
- 回测逻辑必须明确调仓日、持有期和收益口径。
- 新增功能时尽量补充 README 或注释说明。

## 本地运行

```bash
pip install -r requirements.txt
python main.py
```

运行后请确认以下文件能够生成：

```text
outputs/tables/factor_ic_summary.csv
outputs/tables/monthly_group_returns.csv
outputs/tables/top_bottom_performance.csv
outputs/figures/ic_series.png
outputs/figures/group_cum_returns.png
outputs/figures/top_bottom_cum_returns.png
outputs/figures/drawdown.png
```

## Pull Request 建议

- 简要说明改动内容和研究动机。
- 如果新增因子，请说明因子定义和是否存在 look-ahead bias 风险。
- 如果修改回测逻辑，请说明调仓、持仓和收益计算口径变化。
- 不要提交本地 raw 数据、生成后的输出图表或中间文件。
