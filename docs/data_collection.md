# 数据采集与产能权重构建

## 为什么需要产品产能

同一个化工公司可能同时暴露于多个产品价格 driver。仅靠人工给 `driver_weight` 赋值，很容易忽略真实业务结构。例如氟化工公司中 R32、R134a、R125 的产能占比不同，对价格变化的股价传导强度也应不同。

更好的做法是先构建产品层数据：

```text
ticker, company_name, report_year, report_date, product_name, capacity, capacity_unit
```

再把产品映射到价格 driver，并按产能占比生成 company-driver 权重。

## 推荐开源流程

1. 用 [AKShare](https://akshare.akfamily.xyz/) 的巨潮资讯公告接口获取年报元数据和公告链接。
2. 下载年报 PDF。
3. 用 [pdfplumber](https://github.com/jsvine/pdfplumber) 或 [Camelot](https://camelot-py.readthedocs.io/en/master/) 抽取包含“产能”“万吨/年”“设计产能”等关键词的页面或表格。
4. 人工复核产品口径，写入 `data/raw/product_capacity.csv`。
5. 运行 `python main.py`，系统会优先使用产能数据生成 driver 权重。

## 当前项目中的辅助脚本

抓取巨潮资讯公告元数据：

```bash
pip install -r requirements-data.txt
python scripts/fetch_cninfo_reports.py --start-date 20200101 --end-date 20251231 --category 年报
```

抽取年报 PDF 中的产能相关片段：

```bash
python scripts/extract_capacity_snippets.py --pdf-dir data/raw/reports
```

## product_capacity.csv 格式

真实产能数据建议放在：

```text
data/raw/product_capacity.csv
```

字段：

```text
ticker,company_name,sub_industry,report_year,report_date,product_name,capacity,capacity_unit,source_type,source_url,note
```

说明：

- `report_date` 是年报或公告披露日期，不是报告期结束日。
- 权重只会在 `report_date` 之后生效，避免 look-ahead bias。
- `capacity_unit` 应尽量统一，例如全部用“万吨/年”。
- `source_url` 建议保留公告或年报链接，方便复核。

## product_driver_map.csv 格式

产品与价格 driver 的映射放在：

```text
config/product_driver_map.csv
```

字段：

```text
product_name,driver_name,driver_direction,driver_share,exposure_type
```

说明：

- `driver_direction=1` 表示产品价格上升通常利好公司。
- `driver_direction=-1` 可用于原材料价格或成本项。
- `driver_share` 用于一个产品拆成多个 driver 的情形，例如价差因子。
- `exposure_type` 用于标记 `product_price`、`feedstock_cost`、`spread_leg` 等。

## 重要注意

年报文本中的“产能”不是天然干净字段，常见问题包括：

- 设计产能、有效产能、在建产能、权益产能混用。
- 同一产品存在多个子公司或多条产线。
- 原材料、自用中间体和外售产品口径不同。
- 年报披露可能滞后，不能在披露日前用于历史回测。

因此，脚本只负责生成候选信息，最终进入 `product_capacity.csv` 的数据应保留来源并经过人工复核。
