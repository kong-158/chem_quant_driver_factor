# Review Data Snapshots

这个目录用于提交小体量、可公开审查的数据快照。原始 PDF、完整 raw 数据和本地生成中间表仍保留在 `data/raw/`，默认不会提交到 GitHub。

当前文件：

- `product_capacity_review_queue_2025.csv`：按 `config/driver_mapping.csv` 逐行对齐的产品产能审查队列。
- `product_capacity_draft_2025.csv`：从审查队列中筛出的自动草稿，只包含 `review_status=proposed_accept` 的候选。

注意：这些数据来自 2025 年年报文本自动抽取，仍需人工复核后才能整理为正式的 `data/raw/product_capacity.csv`。
