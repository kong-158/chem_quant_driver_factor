"""Build review-ready product capacity tables from parsed report candidates."""

from argparse import ArgumentParser
from pathlib import Path

import pandas as pd


PROPOSED_STATUS = "proposed_accept"
MISSING_STATUS = "missing_candidate"
LOW_CONFIDENCE_STATUS = "needs_review_low_confidence"
NON_COMPANY_STATUS = "needs_review_non_company_capacity"


def _read_optional_csv(path: Path) -> pd.DataFrame:
    """读取可选 CSV；文件不存在时返回空表。"""
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _format_raw_capacity(row: pd.Series) -> str:
    """把原始数字和单位拼成便于人工复核的文本。"""
    raw_capacity = row.get("raw_capacity")
    raw_unit = row.get("raw_unit")
    if pd.isna(raw_capacity) or pd.isna(raw_unit):
        return ""
    value = pd.to_numeric(raw_capacity, errors="coerce")
    if pd.isna(value):
        return f"{raw_capacity}{raw_unit}"
    return f"{value:g}{raw_unit}"


def _review_status(row: pd.Series) -> str:
    """根据候选类型和置信度给出人工复核状态。"""
    if pd.isna(row.get("capacity_wan_ton_per_year")):
        return MISSING_STATUS

    candidate_type = row.get("candidate_type", "")
    confidence = row.get("confidence", "")
    confidence_score = row.get("confidence_score", 0)
    is_company_capacity = candidate_type == "company_capacity"
    is_usable_confidence = confidence in {"high", "medium"} and confidence_score >= 55

    if is_company_capacity and is_usable_confidence:
        return PROPOSED_STATUS
    if candidate_type and not is_company_capacity:
        return NON_COMPANY_STATUS
    return LOW_CONFIDENCE_STATUS


def build_expected_products(driver_mapping: pd.DataFrame, product_driver_map: pd.DataFrame) -> pd.DataFrame:
    """从 driver_mapping 展开应复核的公司-产品清单。

    当前配置基本是一对一映射，但保留 product_driver_map 是为了后续支持一个
    driver 对应多个产品或价差腿。
    """
    mapping = driver_mapping.copy()
    mapping["driver_weight"] = pd.to_numeric(mapping["driver_weight"], errors="coerce")

    if product_driver_map.empty or "driver_name" not in product_driver_map.columns:
        mapping["product_name"] = mapping["driver_name"]
        return mapping

    product_cols = ["product_name", "driver_name", "driver_direction", "driver_share", "exposure_type"]
    available_cols = [col for col in product_cols if col in product_driver_map.columns]
    product_map = product_driver_map[available_cols].drop_duplicates()

    expanded = mapping.merge(product_map, on="driver_name", how="left")
    expanded["product_name"] = expanded["product_name"].fillna(expanded["driver_name"])
    if "driver_direction" not in expanded.columns:
        expanded["driver_direction"] = 1.0
    if "driver_share" not in expanded.columns:
        expanded["driver_share"] = 1.0
    if "exposure_type" not in expanded.columns:
        expanded["exposure_type"] = "product_price"

    expanded["driver_direction"] = pd.to_numeric(expanded["driver_direction"], errors="coerce").fillna(1.0)
    expanded["driver_share"] = pd.to_numeric(expanded["driver_share"], errors="coerce").fillna(1.0)
    expanded["exposure_type"] = expanded["exposure_type"].fillna("product_price")
    return expanded


def select_best_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    """为每个公司-产品选择最适合进入审查队列的一条候选。"""
    if candidates.empty:
        return pd.DataFrame(columns=["ticker", "product_name"])

    df = candidates.copy()
    df["confidence_score"] = pd.to_numeric(df["confidence_score"], errors="coerce").fillna(0)
    df["distance_to_product"] = pd.to_numeric(df["distance_to_product"], errors="coerce").fillna(999)
    df["delimiter_count"] = pd.to_numeric(df["delimiter_count"], errors="coerce").fillna(99)
    df["page_number"] = pd.to_numeric(df["page_number"], errors="coerce").fillna(9999)

    type_rank = {
        "company_capacity": 0,
        "project_or_change_capacity": 1,
        "production_or_sales": 2,
        "industry_context": 3,
        "resource_reserve": 4,
        "unknown": 5,
    }
    confidence_rank = {"high": 0, "medium": 1, "low": 2}
    df["_type_rank"] = df["candidate_type"].map(type_rank).fillna(9)
    df["_confidence_rank"] = df["confidence"].map(confidence_rank).fillna(9)

    # 先保留公司自身产能口径，再看置信度和距离，尽量避免行业/资源/项目口径误入。
    df = df.sort_values(
        [
            "ticker",
            "product_name",
            "_type_rank",
            "_confidence_rank",
            "confidence_score",
            "delimiter_count",
            "distance_to_product",
            "page_number",
        ],
        ascending=[True, True, True, True, False, True, True, True],
    )
    best = df.groupby(["ticker", "product_name"], as_index=False).head(1)
    return best.drop(columns=["_type_rank", "_confidence_rank"]).reset_index(drop=True)


def build_review_queue(
    driver_mapping: pd.DataFrame,
    product_driver_map: pd.DataFrame,
    candidates: pd.DataFrame,
    manifest: pd.DataFrame,
    report_metadata: pd.DataFrame,
    report_year: int,
) -> pd.DataFrame:
    """构建逐 driver 的产能审查队列。"""
    expected = build_expected_products(driver_mapping, product_driver_map)
    best_candidates = select_best_candidates(candidates)

    merged = expected.merge(
        best_candidates,
        on=["ticker", "product_name"],
        how="left",
        suffixes=("", "_candidate"),
    )
    candidate_cols = [
        "capacity_wan_ton_per_year",
        "raw_capacity",
        "raw_unit",
        "candidate_type",
        "confidence",
        "confidence_score",
        "matched_alias",
        "has_capacity_term",
        "distance_to_product",
        "delimiter_count",
        "page_number",
        "candidate_context",
        "pdf_file",
    ]
    for col in candidate_cols:
        if col not in merged.columns:
            merged[col] = pd.NA

    if not manifest.empty:
        manifest_cols = [
            "ticker",
            "announcement_time",
            "announcement_title",
            "announcement_id",
            "pdf_url",
            "pdf_path",
        ]
        manifest_cols = [col for col in manifest_cols if col in manifest.columns]
        merged = merged.merge(manifest[manifest_cols].drop_duplicates("ticker"), on="ticker", how="left")

    if not report_metadata.empty and "公告链接" in report_metadata.columns:
        merged = merged.merge(
            report_metadata[["ticker", "公告链接"]].drop_duplicates("ticker"),
            on="ticker",
            how="left",
        )

    if "report_year" not in merged.columns:
        merged["report_year"] = report_year
    merged["report_year"] = merged["report_year"].fillna(report_year).astype(int)
    if "report_date" not in merged.columns:
        merged["report_date"] = pd.NaT
    if "announcement_time" not in merged.columns:
        merged["announcement_time"] = pd.NaT
    merged["report_date"] = merged["report_date"].fillna(merged["announcement_time"])
    merged["review_status"] = merged.apply(_review_status, axis=1)
    merged["proposed_capacity"] = merged["capacity_wan_ton_per_year"]
    merged["proposed_capacity_unit"] = "万吨/年"
    merged["raw_capacity_text"] = merged.apply(_format_raw_capacity, axis=1)
    merged["source_type"] = "cninfo_annual_report"
    if "pdf_url" not in merged.columns:
        merged["pdf_url"] = ""
    if "公告链接" not in merged.columns:
        merged["公告链接"] = ""
    if "pdf_file" not in merged.columns:
        merged["pdf_file"] = pd.NA
    if "pdf_path" not in merged.columns:
        merged["pdf_path"] = ""
    merged["source_url"] = merged["pdf_url"]
    merged["source_announcement_url"] = merged["公告链接"]
    merged["source_pdf_file"] = merged["pdf_file"].fillna(merged["pdf_path"])
    merged["evidence_page"] = merged.get("page_number", "")
    merged["review_decision"] = ""
    merged["final_capacity"] = ""
    merged["final_capacity_unit"] = ""
    merged["review_note"] = ""

    ordered_cols = [
        "ticker",
        "company_name",
        "sub_industry",
        "driver_name",
        "driver_weight",
        "product_name",
        "driver_direction",
        "driver_share",
        "exposure_type",
        "report_year",
        "report_date",
        "review_status",
        "proposed_capacity",
        "proposed_capacity_unit",
        "raw_capacity_text",
        "confidence",
        "confidence_score",
        "candidate_type",
        "matched_alias",
        "has_capacity_term",
        "distance_to_product",
        "delimiter_count",
        "evidence_page",
        "candidate_context",
        "source_type",
        "source_url",
        "source_announcement_url",
        "source_pdf_file",
        "announcement_title",
        "announcement_id",
        "review_decision",
        "final_capacity",
        "final_capacity_unit",
        "review_note",
    ]
    for col in ordered_cols:
        if col not in merged.columns:
            merged[col] = ""

    return merged[ordered_cols].sort_values(["ticker", "driver_name", "product_name"]).reset_index(drop=True)


def build_capacity_draft(review_queue: pd.DataFrame) -> pd.DataFrame:
    """从审查队列中提取可作为草稿的 product_capacity 兼容表。"""
    draft = review_queue[review_queue["review_status"] == PROPOSED_STATUS].copy()
    if draft.empty:
        return draft

    draft["capacity"] = pd.to_numeric(draft["proposed_capacity"], errors="coerce")
    draft["capacity_unit"] = "万吨/年"
    draft["note"] = (
        "auto_draft_from_2025_annual_report; "
        + draft["raw_capacity_text"].fillna("").astype(str)
        + "; confidence="
        + draft["confidence"].fillna("").astype(str)
        + "; score="
        + draft["confidence_score"].fillna("").astype(str)
    )

    ordered_cols = [
        "ticker",
        "company_name",
        "sub_industry",
        "report_year",
        "report_date",
        "product_name",
        "capacity",
        "capacity_unit",
        "source_type",
        "source_url",
        "note",
        "driver_name",
        "driver_weight",
        "confidence",
        "confidence_score",
        "candidate_type",
        "evidence_page",
        "candidate_context",
    ]
    return draft[ordered_cols].sort_values(["ticker", "product_name"]).reset_index(drop=True)


def main() -> None:
    """命令行入口。"""
    parser = ArgumentParser(description="Build product capacity review queue and draft table.")
    parser.add_argument("--driver-mapping", default="config/driver_mapping.csv", help="公司-driver 映射")
    parser.add_argument("--product-driver-map", default="config/product_driver_map.csv", help="产品-driver 映射")
    parser.add_argument("--candidates", default="data/raw/capacity_candidates_2025.csv", help="产能候选明细")
    parser.add_argument("--manifest", default="data/raw/cninfo_pdf_manifest.csv", help="PDF 下载清单")
    parser.add_argument("--report-metadata", default="data/raw/cninfo_latest_reports.csv", help="公告元数据")
    parser.add_argument("--report-year", type=int, default=2025, help="报告期年份")
    parser.add_argument("--queue-output", default="data/raw/product_capacity_review_queue_2025.csv", help="审查队列输出")
    parser.add_argument("--draft-output", default="data/raw/product_capacity_draft_2025.csv", help="产能草稿输出")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    driver_mapping = pd.read_csv(project_root / args.driver_mapping)
    product_driver_map = _read_optional_csv(project_root / args.product_driver_map)
    candidates = _read_optional_csv(project_root / args.candidates)
    manifest = _read_optional_csv(project_root / args.manifest)
    report_metadata = _read_optional_csv(project_root / args.report_metadata)

    queue = build_review_queue(
        driver_mapping=driver_mapping,
        product_driver_map=product_driver_map,
        candidates=candidates,
        manifest=manifest,
        report_metadata=report_metadata,
        report_year=args.report_year,
    )
    draft = build_capacity_draft(queue)

    queue_path = project_root / args.queue_output
    draft_path = project_root / args.draft_output
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    queue.to_csv(queue_path, index=False, encoding="utf-8-sig")
    draft.to_csv(draft_path, index=False, encoding="utf-8-sig")

    print(f"Saved {len(queue):,} review rows to {queue_path}")
    print(f"Saved {len(draft):,} draft rows to {draft_path}")
    print(queue["review_status"].value_counts().to_string())


if __name__ == "__main__":
    main()
