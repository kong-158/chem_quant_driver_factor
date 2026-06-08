# 数据采集与产能权重构建

## 为什么需要产品产能

同一个化工公司可能同时暴露于多个产品价格 driver。仅靠人工给 `driver_weight` 赋值，很容易忽略真实业务结构。例如氟化工公司中 R32、R134a、R125 的产能占比不同，对价格变化的股价传导强度也应不同。

更好的做法是先构建产品层数据：

```text
ticker, company_name, report_year, report_date, product_name, capacity, capacity_unit
```

再把产品映射到价格 driver，并按产能占比生成 company-driver 权重。

## 推荐开源流程

1. 用 [AKShare](https://akshare.akfamily.xyz/) 的巨潮资讯公告接口获取最新已披露年报元数据和公告链接。
2. 下载年报 PDF。
3. 用 [pdfplumber](https://github.com/jsvine/pdfplumber) 或 [Camelot](https://camelot-py.readthedocs.io/en/master/) 抽取包含“产能”“万吨/年”“设计产能”等关键词的页面或表格。
4. 人工复核产品口径，写入 `data/raw/product_capacity.csv`。
5. 运行 `python main.py`，系统会优先使用产能数据生成 driver 权重。

## 当前项目中的辅助脚本

抓取巨潮资讯公告元数据：

```bash
pip install -r requirements-data.txt
python scripts/fetch_cninfo_reports.py
```

默认逻辑是抓“最新完整年报”。截至 2026-06-08，脚本默认目标是 2025 年年报，查询窗口为 2026-01-01 至 2026-06-08，并且每家公司只保留最新且最像年报全文的一条公告。若需要保留窗口内全部年报、摘要、更正等公告，可加：

```bash
python scripts/fetch_cninfo_reports.py --keep-all
```

如需指定报告期，例如强制抓 2024 年年报，可以写：

```bash
python scripts/fetch_cninfo_reports.py --report-year 2024 --start-date 20250101 --end-date 20251231
```

抽取年报 PDF 中的产能相关片段：

```bash
python scripts/download_cninfo_pdfs.py --output-dir data/raw/reports/2025
python scripts/export_report_text_pages.py --pdf-dir data/raw/reports/2025 --output data/raw/report_text_pages_2025.csv
python scripts/extract_capacity_snippets.py --pdf-dir data/raw/reports/2025 --output data/raw/capacity_snippets_2025.csv
python scripts/parse_capacity_candidates.py
python scripts/build_product_capacity_review_pack.py
```

`export_report_text_pages.py` 的设计参考了 [Annual-report-to-MDA-txt](https://github.com/Xingyixxxx/Annual-report-to-MDA-txt) 的处理思路：先用 `pdfplumber` 将年报逐页转成可检索文本，并保留真实 PDF 页码，后续再围绕产能关键词做定位和人工复核。本项目没有直接复制其代码，也不依赖 LLM/OCR 兜底作为默认流程。

上述流程会生成多类复核材料：

```text
data/raw/report_text_pages_2025.csv
data/raw/capacity_candidates_2025.csv
data/raw/capacity_candidate_summary_2025.csv
data/raw/product_capacity_review_template_2025.csv
data/raw/product_capacity_review_queue_2025.csv
data/raw/product_capacity_draft_2025.csv
```

- `report_text_pages_2025.csv`：年报逐页文本，保留页码，方便追溯证据。
- `capacity_candidates_2025.csv`：自动抽取的候选明细，包含页码、产品、数字、单位、上下文和置信度。
- `capacity_candidate_summary_2025.csv`：按公司和产品汇总后的候选摘要。
- `product_capacity_review_template_2025.csv`：按公司和产品汇总的人工复核模板。
- `product_capacity_review_queue_2025.csv`：按 `config/driver_mapping.csv` 逐行对齐的审查队列，推荐优先审查这张表。
- `product_capacity_draft_2025.csv`：只保留 `proposed_accept` 的产能草稿，字段兼容 `product_capacity.csv`，但仍需人工确认后再用于正式研究。

为了方便 GitHub 上直接审查，当前仓库还提交了一份公开快照：

```text
data/review/product_capacity_review_queue_2025.csv
data/review/product_capacity_draft_2025.csv
data/review/latest_product_capacity_2025.csv
data/review/latest_product_capacity_2025.md
```

其中 `latest_product_capacity_2025` 是在自动候选基础上人工整理的确认口径审查稿，优先采用公司自身披露的“设计产能”“现有产能”“产能与开工情况”，并剔除行业产能、产销量、资源储量和在建工程金额等不适合直接作为产品产能的口径。

`product_capacity_review_queue_2025.csv` 中的 `review_status` 说明：

- `proposed_accept`：候选更像公司自身产能，且置信度达到 high/medium。
- `missing_candidate`：没有在最新年报片段中匹配到该 driver 的产能候选。
- `needs_review_non_company_capacity`：候选可能是行业产能、资源储量、项目建设或产销量口径。
- `needs_review_low_confidence`：候选像公司产能，但抽取质量较弱，需要看年报原文确认。

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
