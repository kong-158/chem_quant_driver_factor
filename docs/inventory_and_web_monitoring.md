# 库存与网页监控方案

本文档说明如何覆盖 ABC 池相关产品的库存监控、网页报价和行业周报入口。

## 1. 总体原则

本项目的 driver 数据分三层处理：

1. 价格日频：优先使用 AkShare 结构化接口，适合进入因子回测。
2. 库存周频：优先找 AkShare/交易所库存或仓单 proxy；没有结构化接口的产品，用行业周报每周维护。
3. 网页报价：使用虚拟浏览器抓取生意社最新报价，先做监控和补源，不直接伪造成历史序列。

库存与价格不同，很多化工品没有公开、连续、统一口径的社会库存数据。因此当前脚本把交易所库存明确标为 `exchange_proxy`，把需要行业周报维护的品种标为 `manual_required`，避免在研究里混淆口径。

## 2. 库存源配置

库存映射文件：

```text
config/driver_inventory_sources.csv
```

主要字段：

- `driver_name`：项目 driver 名称。
- `source_type`：库存源类型，例如 `akshare_futures_inventory_em`、`weekly_report_required`。
- `source_symbol`：AkShare 查询参数，例如 `PTA`、`纯碱`、`塑料`。
- `source_status`：库存口径状态。
- `frequency`：建议更新频率。
- `is_active`：是否默认自动拉取。
- `notes`：口径说明。

当前可自动拉取的库存 proxy：

```text
PTA
PX
PVC
聚乙烯
聚丙烯
尿素
纯碱
甲醇
烧碱
工业硅
多晶硅
焦炭
硅铁
```

这些数据来自：

```python
ak.futures_inventory_em(symbol=...)
```

注意：这里多数是期货相关库存/仓单 proxy，不等同于厂家库存、港口库存或全社会库存。

## 3. 运行库存抓取

安装可选数据依赖：

```bash
pip install -r requirements-data.txt
python -m playwright install chromium
```

只生成覆盖率报告：

```bash
python scripts/fetch_driver_inventory_akshare.py --coverage-only
```

抓取可自动覆盖的库存 proxy：

```bash
python scripts/fetch_driver_inventory_akshare.py
```

输出路径：

```text
data/raw/driver_inventory_akshare.csv
data/review/abc_driver_inventory_source_coverage.csv
data/review/abc_driver_inventory_source_summary.csv
```

`data/raw/` 下的完整数据默认不提交 GitHub；`data/review/` 下的小体量覆盖率报告用于审查。

## 4. 生意社网页报价

网页报价目标配置：

```text
config/web_quote_targets.csv
```

运行：

```bash
python scripts/scrape_100ppi_quotes_playwright.py --pages 3
```

输出：

```text
data/raw/100ppi_quotes_latest.csv
data/review/100ppi_quote_target_matches.csv
data/review/100ppi_quote_target_summary.csv
```

这个脚本抓取：

```text
https://www.100ppi.com/mprice/mlist-1-14-{page}.html
```

并按关键词匹配 MDI、TDI、制冷剂、钛白粉、黄磷、磷酸铵、草甘膦、醋酸、DMF、环氧丙烷等品种。

使用方式建议：

- 每天或每周跑一次，监控是否有目标品种报价。
- 对匹配结果做人工复核，确认规格、地区和报价类型。
- 只有当同一口径能稳定沉淀为历史序列时，才整理为 `data/raw/driver_prices.csv`。

## 5. 行业周报检索

周报检索 query 配置：

```text
config/weekly_report_queries.csv
```

默认使用 requests + 搜狗搜索，中文行业周报结果相对更稳定；脚本会自动把当前年月追加到 query，提高结果时效性。如果需要历史检索，可以加 `--no-current-month`；如果需要调试动态页面，可以加 `--method browser` 使用 Playwright。

运行小样本：

```bash
python scripts/search_weekly_reports_playwright.py --limit-queries 2 --max-results 5
```

运行全部：

```bash
python scripts/search_weekly_reports_playwright.py --max-results 8
```

使用虚拟浏览器调试：

```bash
python scripts/search_weekly_reports_playwright.py --method browser --headful --limit-queries 1
```

输出：

```text
data/raw/weekly_report_links.csv
data/review/weekly_report_search_sample.csv
```

周报检索适合覆盖：

- 纯碱厂家库存。
- 尿素企业库存和港口库存。
- PVC 华东/华南社会库存。
- PTA 社会库存、聚酯开工率。
- 乙二醇港口库存。
- 制冷剂库存、配额和开工率。
- 钛白粉厂家库存。
- 黄磷、磷酸一铵、磷酸二铵库存。
- 草甘膦库存和订单。
- 有机硅 DMC 库存与开工率。

搜索引擎结果不稳定，脚本只负责沉淀候选链接。真正进入因子前，建议把周报中的库存字段人工或半自动整理为统一格式：

```text
date,driver_name,inventory,inventory_unit,source_name,source_url,notes
```

如果短时间内频繁运行，搜索引擎可能返回反爬页面，导致输出 0 行。遇到这种情况建议稍后重试，或使用：

```bash
python scripts/search_weekly_reports_playwright.py --method browser --engine sogou --headful --limit-queries 1
```

## 6. 后续接入因子的建议

库存因子可以先从三个低复杂度方向开始：

- `inventory_mom_4w`：库存过去 4 周变化率。
- `inventory_mom_12w`：库存过去 12 周变化率。
- `price_inventory_signal`：价格上涨且库存下降的交叉信号。

第一版不建议直接把库存和价格混成黑箱模型。更清晰的做法是先分别测试：

1. 价格动量因子。
2. driver-stock gap 因子。
3. 库存变化因子。
4. 价格上涨 + 库存下降的组合筛选条件。

这样能判断到底是产品价格、库存去化，还是股价滞后反应在起作用。
