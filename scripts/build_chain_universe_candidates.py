"""Screen heavy-asset chemical companies from ChainKnowledgeGraph JSONL data.

Usage:
    python scripts/build_chain_universe_candidates.py \
        --chain-kg-dir /path/to/ChainKnowledgeGraph \
        --output data/review/chain_kg_heavy_chemical_screen.csv
"""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import json

import pandas as pd


HEAVY_CHEMICAL_INDUSTRIES = {
    "纯碱",
    "氯碱",
    "煤化工",
    "钛白粉",
    "氟化工",
    "聚氨酯",
    "有机硅",
    "涤纶",
    "粘胶",
    "氮肥",
    "磷肥及磷化工",
    "复合肥",
    "炼油化工",
    "其他石化",
}

HEAVY_PRODUCT_KEYWORDS = [
    "PTA",
    "PX",
    "精对苯二甲酸",
    "芳烃",
    "炼油",
    "乙烯",
    "丙烯",
    "聚乙烯",
    "聚丙烯",
    "涤纶",
    "聚酯",
    "POY",
    "FDY",
    "DTY",
    "甲醇",
    "焦化",
    "尿素",
    "DMF",
    "醋酸",
    "己二酸",
    "纯碱",
    "小苏打",
    "PVC",
    "聚氯乙烯",
    "烧碱",
    "钛白粉",
    "钛精矿",
    "制冷剂",
    "R32",
    "R125",
    "R134a",
    "氢氟酸",
    "萤石",
    "异氰酸酯",
    "MDI",
    "TDI",
    "黄磷",
    "磷矿石",
    "磷酸一铵",
    "磷酸二铵",
    "草甘膦",
    "有机硅",
    "工业硅",
]

NOISE_PRODUCT_KEYWORDS = [
    "贸易",
    "服务",
    "租赁",
    "房地产",
    "工程",
    "运输",
    "物流",
    "仓储",
    "机械",
    "平衡项目",
    "调整项目",
    "销售商品",
    "主要产品",
    "电力",
    "热能",
]

NOISE_PRODUCT_EXACT_NAMES = {
    "销售",
    "自产",
    "本期",
    "加工",
    "化工",
    "商贸",
    "劳务",
    "材料出售",
}


def read_jsonl(path: Path) -> pd.DataFrame:
    """读取 ChainKnowledgeGraph 的 JSONL 文件。"""
    rows = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return pd.DataFrame(rows)


def to_float(value: object) -> float:
    """把主营产品权重转成 float，失败时返回 0。"""
    numeric_value = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric_value):
        return 0.0
    return float(numeric_value)


def contains_any(text: str, keywords: list[str]) -> bool:
    """判断文本是否包含任一关键词。"""
    return any(keyword in text for keyword in keywords)


def is_noise_product(product_name: object) -> bool:
    """过滤泛化、非产品或明显非主营产品价格项。"""
    text = str(product_name).strip()
    return text in NOISE_PRODUCT_EXACT_NAMES or contains_any(text, NOISE_PRODUCT_KEYWORDS)


def product_signal(products: pd.DataFrame, top_n: int) -> dict[str, object]:
    """根据主营产品关键词估算公司的重资产化工暴露强度。"""
    if products.empty:
        return {
            "product_signal_weight": 0.0,
            "matched_product_keywords": "",
            "top_chain_products": "",
        }

    working = products.copy()
    working["rel_weight_numeric"] = working["rel_weight"].map(to_float)
    working = working[working["rel_weight_numeric"] > 0]
    working["is_noise"] = working["product_name"].fillna("").map(is_noise_product)
    working["is_signal"] = working["product_name"].fillna("").map(lambda x: contains_any(str(x), HEAVY_PRODUCT_KEYWORDS))

    signal_rows = working[working["is_signal"] & ~working["is_noise"]]
    matched_keywords = []
    for product_name in signal_rows["product_name"].dropna().astype(str):
        matched_keywords.extend([keyword for keyword in HEAVY_PRODUCT_KEYWORDS if keyword in product_name])

    top_rows = working[~working["is_noise"]].sort_values("rel_weight_numeric", ascending=False).head(top_n)
    top_products = [
        f"{row.product_name}({row.rel_weight_numeric:.3f})"
        for row in top_rows.itertuples(index=False)
    ]

    return {
        "product_signal_weight": round(float(signal_rows["rel_weight_numeric"].sum()), 6),
        "matched_product_keywords": ";".join(sorted(set(matched_keywords))),
        "top_chain_products": "; ".join(top_products),
    }


def build_screen(chain_kg_dir: Path, top_n: int) -> pd.DataFrame:
    """从公司-行业、公司-产品关系中筛选重资产化工候选公司。"""
    data_dir = chain_kg_dir / "data"
    company_industry = read_jsonl(data_dir / "company_industry.json")
    company_product = read_jsonl(data_dir / "company_product.json")

    industry_candidates = company_industry[
        company_industry["industry_name"].isin(HEAVY_CHEMICAL_INDUSTRIES)
    ].copy()

    product_groups = {
        key: group
        for key, group in company_product.groupby("company_code", dropna=False)
    }

    rows = []
    for row in industry_candidates.itertuples(index=False):
        products = product_groups.get(row.company_code, pd.DataFrame())
        signal = product_signal(products, top_n=top_n)
        score = signal["product_signal_weight"]
        if row.industry_name in {"炼油化工", "煤化工", "纯碱", "氯碱", "钛白粉", "氟化工", "聚氨酯", "涤纶"}:
            score += 1.0

        rows.append(
            {
                "ticker": row.company_code,
                "company_name": row.company_name,
                "industry_code": row.industry_code,
                "industry_name": row.industry_name,
                "chain_kg_score": round(score, 6),
                **signal,
            }
        )

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    return result.sort_values(
        ["chain_kg_score", "product_signal_weight", "ticker"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def parse_args() -> ArgumentParser:
    """解析命令行参数。"""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--chain-kg-dir",
        type=Path,
        default=Path("/tmp/ChainKnowledgeGraph"),
        help="本地 ChainKnowledgeGraph 仓库路径。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/review/chain_kg_heavy_chemical_screen.csv"),
        help="筛选结果输出路径。",
    )
    parser.add_argument(
        "--top-products",
        type=int,
        default=8,
        help="每家公司保留的主营产品条数。",
    )
    return parser.parse_args()


def main() -> None:
    """运行候选池筛选。"""
    args = parse_args()
    result = build_screen(args.chain_kg_dir, top_n=args.top_products)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"saved {len(result)} rows to {args.output}")


if __name__ == "__main__":
    main()
