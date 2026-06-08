"""Scrape latest chemical quotes from 100ppi with Playwright.

The output is meant for source discovery and price monitoring. 生意社网页报价是
“最新报价明细”，不等同于可直接用于回测的历史时间序列。正式因子仍应优先使用
`date, driver_name, price` 的连续历史数据。

Examples:
    python scripts/scrape_100ppi_quotes_playwright.py --pages 2
    python scripts/scrape_100ppi_quotes_playwright.py --headful --pages 1
"""

from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path
from urllib.parse import urljoin
import re

import pandas as pd


BASE_URL = "https://www.100ppi.com"
QUOTE_URL_TEMPLATE = "https://www.100ppi.com/mprice/mlist-1-14-{page}.html"

TARGET_COLUMNS = [
    "driver_name",
    "match_keywords",
    "category",
    "source_type",
    "is_active",
    "notes",
]

QUOTE_COLUMNS = [
    "scrape_date",
    "page",
    "product_name",
    "specification",
    "brand",
    "price_text",
    "price",
    "unit",
    "price_type",
    "region",
    "supplier",
    "quote_date",
    "product_url",
    "source_url",
]

EXACT_PRODUCT_KEYWORDS = {
    "苯胺",
    "醋酸",
    "己内酰胺",
    "电石",
    "液氨",
    "黄磷",
    "溴素",
    "小苏打",
    "双氧水",
    "钛白粉",
    "钛精矿",
    "萤石",
}


def parse_args() -> Namespace:
    """解析命令行参数。"""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--targets",
        type=Path,
        default=Path("config/web_quote_targets.csv"),
        help="网页报价关键词目标配置。",
    )
    parser.add_argument("--pages", type=int, default=3, help="抓取生意社报价列表页数。")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/100ppi_quotes_latest.csv"),
        help="全部报价明细输出路径。默认写入 data/raw，不提交到 GitHub。",
    )
    parser.add_argument(
        "--matches-output",
        type=Path,
        default=Path("data/review/100ppi_quote_target_matches.csv"),
        help="目标 driver 关键词匹配结果输出路径。",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("data/review/100ppi_quote_target_summary.csv"),
        help="目标 driver 网页报价覆盖汇总输出路径。",
    )
    parser.add_argument("--timeout-ms", type=int, default=30_000, help="页面加载超时时间。")
    parser.add_argument("--headful", action="store_true", help="打开可视浏览器，方便调试网页结构。")
    return parser.parse_args()


def read_targets(path: Path) -> pd.DataFrame:
    """读取网页报价关键词目标配置。"""
    targets = pd.read_csv(path)
    missing = set(TARGET_COLUMNS) - set(targets.columns)
    if missing:
        raise ValueError(f"{path} 缺少字段: {sorted(missing)}")

    targets = targets[TARGET_COLUMNS].copy()
    targets["is_active"] = pd.to_numeric(targets["is_active"], errors="coerce").fillna(0).astype(int)
    return targets.sort_values(["category", "driver_name"]).reset_index(drop=True)


def parse_price_text(price_text: str) -> tuple[float | None, str]:
    """从 '8000元/吨' 这类文本中拆出数值和单位。"""
    text = str(price_text).replace(",", "").replace("，", "").strip()
    match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*(.*)", text)
    if not match:
        return None, ""
    price = float(match.group(1))
    unit = match.group(2).strip()
    return price, unit


def parse_quote_row(cells: list[str], page_no: int, source_url: str, product_url: str | None) -> dict[str, object] | None:
    """将网页表格的一行转成结构化报价记录。"""
    if len(cells) < 8:
        return None

    product_name = cells[0].strip()
    if not product_name or product_name in {"商品", "品名"}:
        return None

    price, unit = parse_price_text(cells[3])
    quote_date = pd.to_datetime(cells[7].strip(), errors="coerce")
    return {
        "scrape_date": pd.Timestamp.today().normalize(),
        "page": page_no,
        "product_name": product_name,
        "specification": cells[1].strip(),
        "brand": cells[2].strip(),
        "price_text": cells[3].strip(),
        "price": price,
        "unit": unit,
        "price_type": cells[4].strip(),
        "region": cells[5].strip(),
        "supplier": cells[6].strip(),
        "quote_date": quote_date,
        "product_url": product_url or "",
        "source_url": source_url,
    }


def scrape_quote_pages(pages: int, timeout_ms: int, headful: bool) -> pd.DataFrame:
    """使用 Playwright 抓取生意社化工报价列表。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "缺少 playwright，请运行: pip install -r requirements-data.txt && python -m playwright install chromium"
        ) from exc

    records: list[dict[str, object]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headful)
        page = browser.new_page(locale="zh-CN")
        page.set_default_timeout(timeout_ms)

        for page_no in range(1, pages + 1):
            source_url = QUOTE_URL_TEMPLATE.format(page=page_no)
            print(f"scraping 100ppi quotes: {source_url}")
            page.goto(source_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_load_state("networkidle", timeout=timeout_ms)

            # 报价表没有稳定 id，按 tr/td 泛化解析，后续网页结构变动时更容易维护。
            rows = page.locator("table tr").all()
            for row in rows:
                cells = [cell.inner_text().strip() for cell in row.locator("td").all()]
                product_link = row.locator("td").first.locator("a").first
                product_url = ""
                try:
                    href = product_link.get_attribute("href")
                    if href:
                        product_url = urljoin(BASE_URL, href)
                except Exception:  # noqa: BLE001 - 链接缺失不影响报价行
                    product_url = ""
                parsed = parse_quote_row(cells, page_no, source_url, product_url)
                if parsed:
                    records.append(parsed)

        browser.close()

    quotes = pd.DataFrame(records, columns=QUOTE_COLUMNS)
    if not quotes.empty:
        quotes = quotes.drop_duplicates(["page", "product_name", "specification", "brand", "price_text", "supplier"])
        quotes = quotes.sort_values(["quote_date", "product_name"], ascending=[False, True]).reset_index(drop=True)
    return quotes


def split_keywords(value: str) -> list[str]:
    """拆分分号分隔的关键词列表。"""
    return [item.strip() for item in str(value).replace("；", ";").split(";") if item.strip()]


def keyword_matches(keyword: str, product_name: str, specification: str) -> bool:
    """判断关键词是否匹配报价行，避免宽泛产品名误伤衍生品。"""
    keyword_clean = keyword.strip()
    product_clean = product_name.strip()
    if keyword_clean in EXACT_PRODUCT_KEYWORDS:
        return product_clean.casefold() == keyword_clean.casefold()

    combined_text = f"{product_name} {specification}".casefold()
    return keyword_clean.casefold() in combined_text


def match_targets(quotes: pd.DataFrame, targets: pd.DataFrame) -> pd.DataFrame:
    """按关键词把网页报价匹配到项目 driver。"""
    output_cols = ["driver_name", "category", "matched_keyword", *QUOTE_COLUMNS]
    if quotes.empty or targets.empty:
        return pd.DataFrame(columns=output_cols)

    active_targets = targets[(targets["source_type"] == "100ppi_mprice") & (targets["is_active"] == 1)].copy()
    records: list[dict[str, object]] = []
    for _, target in active_targets.iterrows():
        keywords = split_keywords(target["match_keywords"])
        for _, quote in quotes.iterrows():
            product_name = str(quote["product_name"])
            spec = str(quote["specification"])
            matched = next((kw for kw in keywords if keyword_matches(kw, product_name, spec)), None)
            if not matched:
                continue

            record = {
                "driver_name": target["driver_name"],
                "category": target["category"],
                "matched_keyword": matched,
            }
            record.update(quote.to_dict())
            records.append(record)

    matches = pd.DataFrame(records, columns=output_cols)
    if not matches.empty:
        matches = matches.drop_duplicates(["driver_name", "product_name", "specification", "brand", "supplier"])
        matches = matches.sort_values(["driver_name", "quote_date", "product_name"], ascending=[True, False, True])
    return matches.reset_index(drop=True)


def build_summary(targets: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    """生成网页报价目标覆盖汇总。"""
    active_targets = targets[(targets["source_type"] == "100ppi_mprice") & (targets["is_active"] == 1)].copy()
    if matches.empty:
        active_targets["match_count"] = 0
        active_targets["latest_quote_date"] = pd.NaT
        active_targets["sample_products"] = ""
        return active_targets[["driver_name", "category", "match_count", "latest_quote_date", "sample_products", "notes"]]

    grouped = (
        matches.groupby(["driver_name", "category"], dropna=False)
        .agg(
            match_count=("product_name", "size"),
            latest_quote_date=("quote_date", "max"),
            sample_products=("product_name", lambda x: ";".join(sorted(set(map(str, x)))[:5])),
        )
        .reset_index()
    )
    summary = active_targets.merge(grouped, on=["driver_name", "category"], how="left")
    summary["match_count"] = summary["match_count"].fillna(0).astype(int)
    summary["sample_products"] = summary["sample_products"].fillna("")
    return summary[["driver_name", "category", "match_count", "latest_quote_date", "sample_products", "notes"]]


def main() -> None:
    """运行生意社网页报价抓取。"""
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]

    targets = read_targets(project_root / args.targets)
    quotes = scrape_quote_pages(args.pages, timeout_ms=args.timeout_ms, headful=args.headful)

    output_path = project_root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    quotes.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"saved quotes: {output_path} ({len(quotes)} rows)")

    matches = match_targets(quotes, targets)
    matches_path = project_root / args.matches_output
    matches_path.parent.mkdir(parents=True, exist_ok=True)
    matches.to_csv(matches_path, index=False, encoding="utf-8-sig")
    print(f"saved matches: {matches_path} ({len(matches)} rows)")

    summary = build_summary(targets, matches)
    summary_path = project_root / args.summary_output
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"saved summary: {summary_path}")
    print(summary[["driver_name", "match_count", "latest_quote_date", "sample_products"]].to_string(index=False))


if __name__ == "__main__":
    main()
