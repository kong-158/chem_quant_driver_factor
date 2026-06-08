# Driver 价格数据获取说明

本文档说明如何获取 ABC 池相关产品的价格数据。当前实现参考了两个开源项目：

- `Rakion123/chemical-price-app`
- `Yufei0805/chemical-dashboard`

## 1. 参考项目结论

`chemical-price-app` 的核心路径是 Playwright 爬取生意社报价列表：

```text
https://www.100ppi.com/mprice/mlist-1-14-{page}.html
```

这个方式适合拿最新报价明细，例如规格、产地、供应商、地区、报价类型等；缺点是需要浏览器环境，历史时间序列不如结构化接口直接。

`chemical-dashboard` 的核心路径是 AkShare：

```python
ak.futures_spot_price_daily(start_day, end_day, vars_list)
```

该函数的数据源同样是生意社/100ppi，返回大宗商品日频现货价格和基差数据。这个方式更适合本项目的因子研究，因为我们需要历史价格序列来计算 driver momentum。

因此，当前项目优先采用 AkShare 路径；Playwright 报价爬虫作为后续补充，用于覆盖 MDI、TDI、制冷剂、钛白粉、黄磷、草甘膦等 AkShare 期现接口暂未覆盖的品种。

## 2. 配置文件

driver 到价格源的映射维护在：

```text
config/driver_price_sources.csv
```

主要字段：

- `driver_name`：项目中的 driver 名称。
- `source_type`：价格源类型，例如 `akshare_futures_spot`、`manual_required`、`synthetic_required`。
- `source_symbol`：AkShare/期货品种代码，例如 `TA`、`PX`、`V`、`UR`。
- `source_status`：覆盖状态。
- `is_active`：是否默认拉取。
- `notes`：口径说明。

`source_status` 含义：

- `exact`：可直接作为该 driver 的历史价格。
- `proxy`：弱代理，例如用聚酯短纤 `PF` 代理涤纶长丝，默认不启用。
- `upstream_proxy`：上游代理，例如用工业硅 `SI` 代理有机硅 DMC，默认不启用。
- `synthetic_required`：需要组合价差，例如炼化价差。
- `manual_required`：当前 AkShare 期现接口未覆盖，需另接网页源、付费源或手工 CSV。

## 3. 当前可自动拉取的 driver

当前默认精确覆盖以下 driver：

```text
PTA -> TA
PX -> PX
PVC -> V
聚乙烯 -> L
聚丙烯 -> PP
尿素 -> UR
纯碱 -> SA
甲醇 -> MA
烧碱 -> SH
工业硅 -> SI
多晶硅 -> PS
焦炭 -> J
硅铁 -> SF
```

这些 driver 可以通过 `scripts/fetch_driver_prices_akshare.py` 自动拉取。

## 4. 如何运行

安装可选数据依赖：

```bash
pip install -r requirements-data.txt
```

默认拉取最近 180 天的精确覆盖 driver：

```bash
python scripts/fetch_driver_prices_akshare.py
```

拉取指定区间：

```bash
python scripts/fetch_driver_prices_akshare.py \
  --start-date 2026-05-01 \
  --end-date 2026-06-08 \
  --output data/raw/driver_prices_akshare.csv
```

如果希望把结果直接作为主流程 driver 数据，可以输出到：

```bash
python scripts/fetch_driver_prices_akshare.py \
  --start-date 2026-05-01 \
  --end-date 2026-06-08 \
  --output data/raw/driver_prices.csv
```

注意：`data/raw/driver_prices.csv` 会被 `main.py` 优先读取。真实股票行情和真实 driver 价格的日期区间应尽量匹配，否则可用截面会变少。

生成覆盖率报告但不请求 AkShare：

```bash
python scripts/fetch_driver_prices_akshare.py --coverage-only
```

覆盖率报告路径：

```text
data/review/abc_driver_price_source_coverage.csv
data/review/abc_driver_price_source_summary.csv
```

## 5. Proxy 的使用

默认只拉取 `source_status=exact` 的品种。如果要临时拉 proxy，可显式指定：

```bash
python scripts/fetch_driver_prices_akshare.py \
  --source-status exact,proxy,upstream_proxy \
  --include-inactive
```

proxy 数据只能用于探索，不建议直接进入正式因子结果。尤其是：

- `涤纶长丝 -> PF`：PF 是聚酯短纤，不是长丝。
- `粘胶短纤 -> PF`：PF 不是粘胶短纤，只能算极弱纺织化工代理。
- `有机硅DMC -> SI`：工业硅是上游成本，不是 DMC 产品价格。

## 6. 后续补齐方向

下一步可以继续补以下品种：

- 聚氨酯：MDI、TDI、苯胺。
- 氟化工：R32、R125、R134a、氢氟酸、萤石、无水氟化铝、六氟磷酸锂。
- 钛白粉：钛白粉、钛精矿。
- 磷化工：磷矿石、黄磷、磷酸一铵、磷酸二铵。
- 农药：草甘膦、草铵膦、麦草畏、菊酯。
- 煤化工中间品：醋酸、DMF、己内酰胺、液氨、双氧水。

这些品种可以优先考虑三条路径：

1. 复用 `chemical-price-app` 的 Playwright 生意社报价列表，先抓最新报价。
2. 寻找 AkShare 中其他现货/商品函数是否覆盖。
3. 接入百川、卓创、隆众等付费或半结构化数据源，并统一落到 `date, driver_name, price` 格式。
