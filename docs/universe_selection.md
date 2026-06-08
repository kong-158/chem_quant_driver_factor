# 股票池扩展与产业链筛选说明

本文档记录如何从“公司-产品-产业链”角度扩展化工 driver 因子股票池。当前内容用于研究审查，不构成投资建议。

## 1. 年报 PDF 下载状态

我已经在本地下载了 starter universe 的 2025 年年报 PDF，路径为：

```text
data/raw/reports/2025/
```

对应 manifest：

```text
data/raw/cninfo_pdf_manifest.csv
```

截至本次整理，manifest 共 15 条记录，`status=success` 共 15 条。PDF 文件位于 `data/raw/` 下，按照 `.gitignore` 不提交到 GitHub；仓库只提交小体量、可审查的产能快照到 `data/review/`。

## 2. ChainKnowledgeGraph 的使用方式

参考项目：

```text
https://github.com/liuhuanyong/ChainKnowledgeGraph
```

该项目的可用结构主要包括：

- `company_industry.json`：公司-申万行业关系。
- `company_product.json`：公司-主营产品关系，含 `rel_weight`。
- `product_product.json`：产品上下游关系。

本项目没有直接复制其全量数据，而是新增脚本：

```bash
python scripts/build_chain_universe_candidates.py \
  --chain-kg-dir /path/to/ChainKnowledgeGraph \
  --output data/review/chain_kg_heavy_chemical_screen.csv
```

脚本只读取本地 clone 的 ChainKnowledgeGraph JSONL 文件，并输出一份轻量筛选结果。筛选逻辑是：

1. 保留纯碱、氯碱、煤化工、钛白粉、氟化工、聚氨酯、涤纶、炼油化工等重资产化工行业。
2. 用 PTA、PX、PVC、烧碱、纯碱、尿素、TDI、MDI、R32、钛白粉、工业硅、有机硅等关键词识别产品价格敏感业务。
3. 剔除贸易、租赁、工程、物流、泛销售等非产品价格项。
4. 输出 `chain_kg_score`、匹配产品关键词和主营产品证据。

注意：ChainKnowledgeGraph 的产品上下游边噪声较大，适合做 schema 和候选筛选参考，不适合直接作为最终产能或权重事实源。

## 3. 新增配置文件

本轮新增以下文件：

```text
config/chemical_chain_edges.csv
config/universe_heavy_chemical_candidates.csv
config/universe_expanded_heavy_chemical.csv
config/driver_mapping_heavy_chemical_candidates.csv
data/review/chain_kg_heavy_chemical_screen.csv
data/review/heavy_chemical_universe_candidates.csv
data/review/heavy_chemical_universe_candidates.md
```

其中：

- `chemical_chain_edges.csv`：干净的化工产业链边，例如 `PX -> PTA -> 涤纶长丝`、`萤石 -> 氢氟酸 -> R32/R125/R134a`。
- `universe_heavy_chemical_candidates.csv`：手工清洗后的 26 个重资产化工候选标的。
- `universe_expanded_heavy_chemical.csv`：starter universe 15 个标的 + 26 个候选标的，共 41 个。
- `driver_mapping_heavy_chemical_candidates.csv`：候选标的的初版 driver 权重，权重均已归一化为 1。
- `data/review/*.md/csv`：便于在 GitHub 页面直接审查的轻量快照。

## 4. 当前候选池口径

优先纳入的 A 类候选主要满足：

- 产品链条清晰。
- 装置重、固定资产属性强。
- 产品价格或价差对盈利弹性更直观。
- 可通过年报产能进一步验证 driver 权重。

典型例子：

- 芳烃/聚酯链：恒力石化、荣盛石化、东方盛虹、恒逸石化、新凤鸣。
- 煤化工/纯碱/氯碱链：宝丰能源、远兴能源、山东海化、三友化工、氯碱化工、新疆天业。
- 聚氨酯/醋酸/环氧丙烷链：沧州大化、江苏索普、滨化股份。
- 工业硅/有机硅链：合盛硅业、新安股份。
- 磷化工链：川恒股份。

B 类候选不是排除，而是提醒需要更多年报拆分或业务纯度确认，例如多氟多、昊华科技、君正集团、新洋丰、六国化工、金浦钛业、安纳达、惠云钛业、鲁北化工等。

## 5. 后续建议

下一步不要急着把候选表直接替换 `config/universe.csv`。建议流程是：

1. 按候选池下载这些公司的最新年报 PDF。
2. 用现有产能提取脚本抽取产品产能、装置产能和收入分部。
3. 人工复核 A 类候选的产能权重，先并入 10-15 个最干净的标的。
4. 将确认后的权重写入正式 `config/driver_mapping.csv` 或 `data/raw/product_capacity.csv`。
5. 再运行 `python main.py` 检验扩展股票池后的 IC 和分组回测是否稳定。
