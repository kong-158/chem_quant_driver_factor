"""Parse structured capacity candidates from extracted report snippets."""

from argparse import ArgumentParser
from pathlib import Path
import re

import pandas as pd


CAPACITY_PATTERN = re.compile(r"(?P<value>\d{1,4}(?:,\d{3})*(?:\.\d+)?)\s*(?P<unit>万吨/年|万吨|吨/年|吨)")
FILENAME_PATTERN = re.compile(r"(?P<ticker>\d{6}\.(?:SZ|SH))_(?P<company>[^_]+)_(?P<date>\d{4}-\d{2}-\d{2})_")

POSITIVE_TERMS = [
    "公司目前拥有",
    "现已形成",
    "主要产品产能",
    "主要产品的产能",
    "主要产品的产能情况",
    "设计产能",
    "生产能力",
    "年产能",
    "具备",
]

NEGATIVE_TERMS = [
    "行业产能",
    "我国",
    "全球",
    "市场",
    "CR10",
    "产能过剩",
    "新增产能",
    "在建产能",
    "在建",
    "项目",
    "募投",
    "投资建设",
    "环评批复",
    "排污许可证",
    "许可内容",
    "废气",
    "废水",
]
DELIMITER_PATTERN = re.compile(r"[，,、；;。和及]")
CAPACITY_TERMS = ["产能", "设计产能", "生产能力", "年产能", "年产"]
COMPANY_CAPACITY_TERMS = [
    "主要产品产能",
    "主要产品的产能",
    "主要产品的产能情况",
    "设计产能",
    "产能与开工情况",
    "产能利用率",
    "主要厂区或项目",
    "现有产能",
    "公司目前拥有",
    "公司拥有",
    "截至报告期末",
]
INDUSTRY_TERMS = ["行业产能", "国内", "我国", "全球", "市场", "CR10", "据百川"]
RESOURCE_TERMS = ["保有资源", "资源储量", "储备", "矿石量", "探明"]
PROJECT_TERMS = ["新增", "新增加", "在建", "扩建", "技改", "项目", "投产", "转让", "置换"]
PRODUCTION_TERMS = ["生产", "销售", "产量", "销量"]


def _normalize_text(text: str) -> str:
    """压缩空白字符，方便正则抽取。"""
    return re.sub(r"\s+", "", str(text))


def _parse_report_meta(pdf_file: str) -> dict:
    """从 PDF 文件名中解析 ticker、公司名和披露日期。"""
    filename = Path(str(pdf_file)).name
    match = FILENAME_PATTERN.search(filename)
    if not match:
        return {"ticker": "", "company_name": "", "report_date": ""}
    return {
        "ticker": match.group("ticker"),
        "company_name": match.group("company"),
        "report_date": match.group("date"),
    }


def _to_float(value: str) -> float:
    """将带千分位的数字转成 float。"""
    return float(str(value).replace(",", ""))


def _unit_to_wan_ton(value: float, unit: str) -> float:
    """统一换算为万吨/年口径。"""
    if unit == "吨" or unit == "吨/年":
        return value / 10000
    return value


def _window(text: str, start: int, end: int, width: int = 80) -> str:
    """截取候选周边上下文。"""
    return text[max(start - width, 0) : min(end + width, len(text))]


def _score_candidate(
    context: str,
    alias: str,
    unit: str,
    distance: int,
    is_after_product: bool,
    has_capacity_term: bool,
    delimiter_count: int,
    candidate_type: str,
) -> tuple[int, str]:
    """根据上下文给候选打粗略置信度。"""
    score = 45
    if distance <= 20:
        score += 8
    if "万吨" in unit:
        score += 3
    if is_after_product:
        score += 4
        if distance <= 12:
            score += 4
    else:
        score -= 2

    if has_capacity_term:
        score += 20
    else:
        score -= 10

    if delimiter_count:
        score -= min(delimiter_count * 18, 45)

    for term in POSITIVE_TERMS:
        if term in context:
            score += 4

    if candidate_type != "company_capacity":
        for term in NEGATIVE_TERMS:
            if term in context:
                score -= 12

    # 产品别名出现在“公司拥有/形成/主要产品产能”附近，通常更像公司自身口径。
    if alias in context and any(term in context for term in ["公司目前拥有", "现已形成", "主要产品"]):
        score += 10

    if any(term in context for term in [f"生产{alias}", f"销售{alias}"]) and not has_capacity_term:
        score -= 15

    type_adjustment = {
        "company_capacity": 10,
        "project_or_change_capacity": -8,
        "industry_context": -25,
        "resource_reserve": -20,
        "production_or_sales": -20,
        "unknown": -5,
    }
    score += type_adjustment.get(candidate_type, 0)

    score = max(min(score, 100), 0)
    if score >= 75:
        confidence = "high"
    elif score >= 55:
        confidence = "medium"
    else:
        confidence = "low"
    return score, confidence


def _classify_candidate(context: str, alias: str, has_capacity_term: bool) -> str:
    """识别候选属于公司产能、项目产能、行业背景还是产销量。"""
    if any(term in context for term in [f"生产{alias}", f"销售{alias}"]):
        return "production_or_sales"
    if any(term in context for term in COMPANY_CAPACITY_TERMS):
        return "company_capacity"
    if any(term in context for term in INDUSTRY_TERMS):
        return "industry_context"
    if any(term in context for term in RESOURCE_TERMS):
        return "resource_reserve"
    if any(term in context for term in PROJECT_TERMS):
        return "project_or_change_capacity"
    if any(term in context for term in PRODUCTION_TERMS) and not has_capacity_term:
        return "production_or_sales"
    if has_capacity_term:
        return "company_capacity"
    return "unknown"


def _extract_for_alias(text: str, product_name: str, alias: str) -> list[dict]:
    """围绕一个产品别名抽取产能数字候选。"""
    rows = []
    for alias_match in re.finditer(re.escape(alias), text, flags=re.IGNORECASE):
        left = max(alias_match.start() - 60, 0)
        right = min(alias_match.end() + 80, len(text))
        local_text = text[left:right]
        matches = []

        for cap_match in CAPACITY_PATTERN.finditer(local_text):
            absolute_start = left + cap_match.start()
            absolute_end = left + cap_match.end()
            distance = min(abs(absolute_start - alias_match.end()), abs(alias_match.start() - absolute_end))

            # 距离太远时，数字很可能属于其他产品或行业描述。
            if distance > 55:
                continue

            is_after_product = absolute_start >= alias_match.start()
            matches.append((0 if is_after_product else 1, distance, absolute_start, absolute_end, cap_match))

        if not matches:
            continue

        # 同一句里常常同时列示多个产品产能，只取离当前产品最近的数字，
        # 例如“尿素216万吨、烧碱94万吨、PVC90万吨”。
        direction_rank, distance, absolute_start, absolute_end, cap_match = sorted(matches, key=lambda item: (item[0], item[1]))[0]
        is_after_product = direction_rank == 0

        raw_value = _to_float(cap_match.group("value"))
        raw_unit = cap_match.group("unit")
        context = _window(text, absolute_start, absolute_end)
        relation_start = min(alias_match.start(), absolute_start)
        relation_end = max(alias_match.end(), absolute_end)
        relation_text = text[relation_start:relation_end]
        near_text = text[max(relation_start - 20, 0) : min(relation_end + 20, len(text))]
        relation_for_delimiter = re.sub(r"(?<=\d),(?=\d{3})", "", relation_text)
        delimiter_count = len(DELIMITER_PATTERN.findall(relation_for_delimiter))
        has_capacity_term = any(term in near_text for term in CAPACITY_TERMS)
        candidate_type = _classify_candidate(context, alias, has_capacity_term)
        score, confidence = _score_candidate(
            context,
            alias,
            raw_unit,
            distance,
            is_after_product,
            has_capacity_term,
            delimiter_count,
            candidate_type,
        )

        rows.append(
            {
                "product_name": product_name,
                "matched_alias": alias,
                "raw_capacity": raw_value,
                "raw_unit": raw_unit,
                "capacity_wan_ton_per_year": _unit_to_wan_ton(raw_value, raw_unit),
                "capacity_position": "after_product" if is_after_product else "before_product",
                "distance_to_product": distance,
                "has_capacity_term": has_capacity_term,
                "delimiter_count": delimiter_count,
                "candidate_type": candidate_type,
                "confidence_score": score,
                "confidence": confidence,
                "candidate_context": context,
            }
        )
    return rows


def parse_capacity_candidates(snippets: pd.DataFrame, aliases: pd.DataFrame) -> pd.DataFrame:
    """从产能片段中抽取结构化候选。"""
    rows = []
    aliases = aliases.dropna(subset=["product_name", "alias"]).copy()

    for snippet_row in snippets.itertuples(index=False):
        meta = _parse_report_meta(snippet_row.pdf_file)
        text = _normalize_text(snippet_row.snippet)

        for alias_row in aliases.itertuples(index=False):
            product_name = str(alias_row.product_name)
            alias = str(alias_row.alias)
            if alias not in text:
                continue

            for candidate in _extract_for_alias(text, product_name, alias):
                rows.append(
                    {
                        **meta,
                        "report_year": 2025,
                        "pdf_file": snippet_row.pdf_file,
                        "page_number": snippet_row.page_number,
                        "matched_keywords": snippet_row.matched_keywords,
                        **candidate,
                    }
                )

    candidates = pd.DataFrame(rows)
    if candidates.empty:
        return candidates

    candidates = candidates.drop_duplicates(
        subset=[
            "ticker",
            "product_name",
            "page_number",
            "raw_capacity",
            "raw_unit",
            "candidate_context",
        ]
    )
    candidates = candidates.sort_values(
        ["ticker", "confidence_score", "product_name", "page_number"],
        ascending=[True, False, True, True],
    )
    return candidates.reset_index(drop=True)


def summarize_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    """按公司和产品生成复核摘要，每组保留最高分候选。"""
    if candidates.empty:
        return candidates

    sorted_candidates = candidates.sort_values(
        ["ticker", "product_name", "confidence_score", "distance_to_product", "page_number"],
        ascending=[True, True, False, True, True],
    )
    best = sorted_candidates.groupby(["ticker", "product_name"], as_index=False).head(1).copy()

    counts = (
        candidates.groupby(["ticker", "product_name"], as_index=False)
        .agg(
            candidate_count=("product_name", "size"),
            high_confidence_count=("confidence", lambda x: (x == "high").sum()),
            pages=("page_number", lambda x: ";".join(map(str, sorted(set(x))))),
        )
    )
    summary = best.merge(counts, on=["ticker", "product_name"], how="left")

    review_cols = [
        "review_status",
        "final_capacity",
        "final_capacity_unit",
        "review_note",
    ]
    for col in review_cols:
        summary[col] = ""

    ordered_cols = [
        "ticker",
        "company_name",
        "report_year",
        "report_date",
        "product_name",
        "capacity_wan_ton_per_year",
        "raw_capacity",
        "raw_unit",
        "confidence",
        "confidence_score",
        "capacity_position",
        "distance_to_product",
        "has_capacity_term",
        "delimiter_count",
        "candidate_type",
        "candidate_count",
        "high_confidence_count",
        "pages",
        "page_number",
        "matched_alias",
        "candidate_context",
        "review_status",
        "final_capacity",
        "final_capacity_unit",
        "review_note",
    ]
    return summary[ordered_cols].sort_values(["ticker", "confidence_score", "product_name"], ascending=[True, False, True])


def main() -> None:
    """命令行入口。"""
    parser = ArgumentParser(description="Parse capacity candidates from extracted CNINFO report snippets.")
    parser.add_argument("--snippets", default="data/raw/capacity_snippets_2025.csv", help="产能片段 CSV")
    parser.add_argument("--aliases", default="config/product_aliases.csv", help="产品别名 CSV")
    parser.add_argument("--candidates-output", default="data/raw/capacity_candidates_2025.csv", help="候选明细输出")
    parser.add_argument("--summary-output", default="data/raw/capacity_candidate_summary_2025.csv", help="候选摘要输出")
    parser.add_argument("--review-output", default="data/raw/product_capacity_review_template_2025.csv", help="人工复核模板输出")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    snippets = pd.read_csv(project_root / args.snippets)
    aliases = pd.read_csv(project_root / args.aliases)

    candidates = parse_capacity_candidates(snippets, aliases)
    summary = summarize_candidates(candidates)

    for output in [args.candidates_output, args.summary_output, args.review_output]:
        output_path = project_root / output
        output_path.parent.mkdir(parents=True, exist_ok=True)

    candidates.to_csv(project_root / args.candidates_output, index=False, encoding="utf-8-sig")
    summary.to_csv(project_root / args.summary_output, index=False, encoding="utf-8-sig")
    summary.to_csv(project_root / args.review_output, index=False, encoding="utf-8-sig")

    print(f"Saved {len(candidates):,} candidates to {project_root / args.candidates_output}")
    print(f"Saved {len(summary):,} review rows to {project_root / args.review_output}")
    if not candidates.empty:
        print(candidates["confidence"].value_counts().to_string())


if __name__ == "__main__":
    main()
