# Review Data Snapshots

这个目录用于提交小体量、可公开审查的数据快照。原始 PDF、完整 raw 数据和本地生成中间表仍保留在 `data/raw/`，默认不会提交到 GitHub。

当前文件：

- `product_capacity_review_queue_2025.csv`：按 `config/driver_mapping.csv` 逐行对齐的产品产能审查队列。
- `product_capacity_draft_2025.csv`：从审查队列中筛出的自动草稿，只包含 `review_status=proposed_accept` 的候选。
- `latest_product_capacity_2025.csv`：在自动候选和年报逐页文本基础上人工整理的最新产品产能审查稿。
- `latest_product_capacity_2025.md`：上述 CSV 的 Markdown 预览版，方便在 GitHub 页面直接阅读。
- `chain_kg_heavy_chemical_screen.csv`：参考 ChainKnowledgeGraph 生成的重资产化工公司初筛结果。
- `heavy_chemical_universe_candidates.csv`：手工清洗后的扩展股票池候选表。
- `heavy_chemical_universe_candidates.md`：上述候选表的 Markdown 预览版，方便在 GitHub 页面直接阅读。
- `abc_driver_price_source_coverage.csv`：ABC 池 ticker-driver 对价格源的覆盖率报告。
- `abc_driver_price_source_summary.csv`：ABC 池价格源覆盖率汇总。

注意：这些数据来自 2025 年年报文本自动抽取，仍需人工复核后才能整理为正式的 `data/raw/product_capacity.csv`。

扩展股票池候选表来自 ChainKnowledgeGraph 的公司-行业、公司-主营产品关系和人工产业链清洗，不等同于最终投资标的或正式 driver 权重。详细说明见 `docs/universe_selection.md`。

价格源覆盖率表来自 `config/driver_price_sources.csv` 和 ABC 池映射，详细说明见 `docs/driver_price_data.md`。
