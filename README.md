# 基于化工行业景气度 Driver 的 A 股中低频因子研究

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## 1. 项目背景

本项目用于研究化工品价格、价差或行业景气度指标的变化，是否能够领先解释相关 A 股上市公司的未来收益。核心关注点是：当产品价格或景气度 driver 已经上涨，但股价尚未充分反应时，是否存在可被中低频因子捕捉的机会。

当前版本是 MVP，不引入复杂量化框架和机器学习模型，只完成可复现的基础研究流水线：数据读取、因子构造、收益标签、Rank IC、月频分组回测和结果输出。

> 免责声明：本项目仅用于量化研究框架展示和学习交流，不构成任何投资建议。默认 sample 数据为程序生成的模拟数据，不代表真实行情或真实化工品价格。

## 2. 研究逻辑

1. 为每家公司配置一个或多个化工品 driver，并设置权重。
2. 如果存在产品产能数据，则优先用产能占比生成 point-in-time driver 权重。
3. 计算 driver 过去 20 日、60 日动量。
4. 计算股票自身过去 20 日、60 日动量。
5. 构造 driver-stock gap：`driver_momentum - stock_momentum`。
6. 用 t 日因子预测 t 日之后 20 或 60 个交易日收益。
7. 用 Rank IC 和月频分组回测检验因子有效性。

## 3. 数据结构

股票价格数据路径：

```text
data/raw/stock_prices.csv
```

字段：

```text
date,ticker,close,adj_close,volume
```

driver 数据路径：

```text
data/raw/driver_prices.csv
```

字段：

```text
date,driver_name,price
```

如果 `data/raw/` 下没有真实数据，程序会自动生成并使用：

```text
data/sample/stock_prices.csv
data/sample/driver_prices.csv
```

开源仓库默认不提交 `data/raw/`、`data/processed/`、`data/sample/*.csv` 和 `outputs/` 下的生成结果。运行 `python main.py` 后，这些文件会在本地自动生成。

公司与 driver 映射文件：

```text
config/driver_mapping.csv
```

字段：

```text
ticker,company_name,sub_industry,driver_name,driver_weight
```

如果希望用年报披露的产品产能自动生成权重，可以提供：

```text
data/raw/product_capacity.csv
```

字段：

```text
ticker,company_name,sub_industry,report_year,report_date,product_name,capacity,capacity_unit,source_type,source_url,note
```

产品与价格 driver 的映射文件：

```text
config/product_driver_map.csv
```

字段：

```text
product_name,driver_name,driver_direction,driver_share,exposure_type
```

系统会优先使用 `product_capacity.csv` 生成产能权重，并以 `report_date` 作为生效日，避免在年报披露日前使用未来产能信息。没有产能文件时，会退回 `config/driver_mapping.csv` 的人工权重。

## 4. 因子定义

当前版本实现以下基础因子：

- `driver_mom_20d`：公司对应 driver 过去 20 个交易日加权涨幅。
- `driver_mom_60d`：公司对应 driver 过去 60 个交易日加权涨幅。
- `stock_mom_20d`：股票复权价过去 20 个交易日涨幅。
- `stock_mom_60d`：股票复权价过去 60 个交易日涨幅。
- `driver_stock_gap_20d`：`driver_mom_20d - stock_mom_20d`。
- `driver_stock_gap_60d`：`driver_mom_60d - stock_mom_60d`。

所有因子都只使用 t 日及以前的信息，不使用未来数据。

## 5. 收益标签

当前版本计算：

- `future_ret_20d`
- `future_ret_60d`
- `future_excess_ret_20d`
- `future_excess_ret_60d`

其中超额收益为个股未来收益减去同一截面股票池等权未来收益。

## 6. 回测方法

月频分组回测逻辑：

1. 每个自然月最后一个可用交易日调仓。
2. 按指定因子从低到高分成 5 组。
3. 每组内部等权持有到下一个调仓日。
4. 计算每组月度收益。
5. 计算最高因子组减最低因子组的 `Top-Bottom` 收益。

默认回测因子为：

```text
driver_stock_gap_20d
```

## 7. 如何运行

安装依赖：

```bash
pip install -r requirements.txt
```

一键运行：

```bash
python main.py
```

也可以使用 Makefile：

```bash
make install
make run
```

如果你在项目外层目录，可以运行：

```bash
cd quant_driver_factor
python main.py
```

## 8. 输出结果

运行后会生成以下表格：

```text
outputs/tables/factor_ic_series.csv
outputs/tables/factor_ic_summary.csv
outputs/tables/monthly_group_returns.csv
outputs/tables/top_bottom_performance.csv
```

运行后会生成以下图片：

```text
outputs/figures/ic_series.png
outputs/figures/group_cum_returns.png
outputs/figures/top_bottom_cum_returns.png
outputs/figures/drawdown.png
```

中间数据集会保存到：

```text
data/processed/factor_dataset.csv
data/processed/driver_mapping_effective.csv
```

## 9. 目录说明

```text
quant_driver_factor/
├── config/              # 股票池与 driver 映射
├── data/raw/            # 真实原始数据
├── data/sample/         # 自动生成的样本数据
├── data/processed/      # 因子与收益标签合并后的中间结果
├── notebooks/           # 数据检查和结果展示用 notebook
├── outputs/figures/     # 输出图表
├── outputs/tables/      # 输出表格
├── src/                 # 核心代码模块
└── main.py              # 一键运行入口
```

## 10. 后续扩展方向

1. 替换 sample 数据为真实行情和化工品价格数据。
2. 用年报、官网和公告持续完善 `product_capacity.csv`。
3. 增加行业中性、市值中性处理。
4. 增加交易成本和换手率。
5. 增加更多子行业和更多 driver。
6. 对比股价动量因子，检验 driver 因子的增量效果。
7. 增加滚动窗口检验，观察因子稳定性。
8. 增加机器学习模型，但第一版暂不实现。

## 11. 数据采集

本项目预留了年报/公告采集与产能提取的轻量入口，详见：

```text
docs/data_collection.md
```

可选依赖：

```bash
pip install -r requirements-data.txt
```

抓取巨潮资讯年报公告元数据：

```bash
python scripts/fetch_cninfo_reports.py --start-date 20200101 --end-date 20251231 --category 年报
```

从年报 PDF 中抽取产能相关候选片段：

```bash
python scripts/extract_capacity_snippets.py --pdf-dir data/raw/reports
```

## 12. 开源协作

本项目使用 MIT License。欢迎通过 issue 或 pull request 贡献：

- 新的 driver 映射。
- 更严格的收益和回测口径。
- 更完整的研究报告模板。
- 行业中性、市值中性、交易成本和换手率模块。

提交 PR 前建议运行：

```bash
python main.py
```
