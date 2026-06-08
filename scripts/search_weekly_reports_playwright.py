"""Search weekly industry report links.

The script keeps weekly inventory monitoring in a review-friendly form: it
collects candidate report links for each product chain, but does not pretend
that unstructured report text is already clean factor data.

Examples:
    python scripts/search_weekly_reports_playwright.py --limit-queries 2 --max-results 5
    python scripts/search_weekly_reports_playwright.py --method browser --headful
"""

from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path
from time import sleep
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
import base64
import html as html_lib
import re

import pandas as pd
import requests


QUERY_COLUMNS = ["topic", "query", "driver_names", "notes", "is_active"]
OUTPUT_COLUMNS = [
    "search_date",
    "topic",
    "query",
    "rank",
    "title",
    "url",
    "domain",
    "snippet",
    "driver_names",
    "notes",
    "search_url",
]


def parse_args() -> Namespace:
    """解析命令行参数。"""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--query-config",
        type=Path,
        default=Path("config/weekly_report_queries.csv"),
        help="行业周报检索 query 配置。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/weekly_report_links.csv"),
        help="全部检索结果输出路径。默认写入 data/raw，不提交到 GitHub。",
    )
    parser.add_argument(
        "--review-output",
        type=Path,
        default=Path("data/review/weekly_report_search_sample.csv"),
        help="小体量检索结果快照，方便 GitHub 审查。",
    )
    parser.add_argument("--max-results", type=int, default=8, help="每个 topic 保留的搜索结果数量。")
    parser.add_argument("--limit-queries", type=int, default=None, help="只跑前 N 个 active query，方便调试。")
    parser.add_argument("--timeout-ms", type=int, default=30_000, help="页面加载超时时间。")
    parser.add_argument("--sleep-seconds", type=float, default=1.0, help="不同 query 之间暂停秒数。")
    parser.add_argument(
        "--method",
        choices=["requests", "browser"],
        default="requests",
        help="检索方式。默认 requests 更稳定；browser 用 Playwright 调试动态页面。",
    )
    parser.add_argument(
        "--engine",
        choices=["sogou", "bing"],
        default="sogou",
        help="搜索引擎。默认搜狗，中文行业周报结果通常比 Bing 更稳定。",
    )
    parser.add_argument(
        "--no-current-month",
        dest="append_current_month",
        action="store_false",
        help="不在 query 后追加当前年月。默认会追加当前年月以提高周报时效性。",
    )
    parser.set_defaults(append_current_month=True)
    parser.add_argument("--headful", action="store_true", help="打开可视浏览器，方便处理搜索引擎反爬页面。")
    return parser.parse_args()


def read_queries(path: Path, limit_queries: int | None) -> pd.DataFrame:
    """读取行业周报检索配置。"""
    queries = pd.read_csv(path)
    missing = set(QUERY_COLUMNS) - set(queries.columns)
    if missing:
        raise ValueError(f"{path} 缺少字段: {sorted(missing)}")

    queries = queries[QUERY_COLUMNS].copy()
    queries["is_active"] = pd.to_numeric(queries["is_active"], errors="coerce").fillna(0).astype(int)
    active = queries[queries["is_active"] == 1].reset_index(drop=True)
    if limit_queries is not None:
        active = active.head(limit_queries).copy()
    return active


def decode_bing_redirect(href: str) -> str:
    """尽量把 Bing 跳转链接还原成真实链接。"""
    if not href:
        return ""

    url = urljoin("https://www.bing.com", href)
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    for key in ("u", "url", "r"):
        value = params.get(key, [""])[0]
        if not value:
            continue
        value = unquote(value)
        if value.startswith("a1"):
            encoded = value[2:]
            encoded += "=" * (-len(encoded) % 4)
            try:
                decoded = base64.urlsafe_b64decode(encoded).decode("utf-8", errors="ignore")
                if decoded.startswith(("http://", "https://")):
                    return decoded
            except Exception:  # noqa: BLE001 - 搜索引擎跳转格式不稳定
                pass
        if value.startswith(("http://", "https://")):
            return value
    return url


def clean_text(value: str) -> str:
    """压缩搜索结果中的空白字符。"""
    return re.sub(r"\s+", " ", str(value)).strip()


def strip_tags(value: str) -> str:
    """去掉简单 HTML 标签并反转义实体。"""
    no_tags = re.sub(r"<.*?>", "", value, flags=re.S)
    return clean_text(html_lib.unescape(no_tags))


def extract_domain(url: str) -> str:
    """从 URL 中提取域名。"""
    parsed = urlparse(url)
    return parsed.netloc.lower().replace("www.", "")


def is_useful_url(url: str) -> bool:
    """过滤搜索页内部链接和明显无效链接。"""
    if not url.startswith(("http://", "https://")):
        return False
    domain = extract_domain(url)
    if domain in {"bing.com", "cn.bing.com"}:
        return False
    if any(part in url for part in ["/search?", "javascript:", "#"]):
        return False
    return True


def parse_bing_results(page, max_results: int) -> list[dict[str, str]]:
    """从 Bing 页面解析标题、链接和摘要。"""
    records: list[dict[str, str]] = []

    result_blocks = page.locator("li.b_algo").all()
    for block in result_blocks:
        try:
            link = block.locator("h2 a").first
            href = decode_bing_redirect(link.get_attribute("href") or "")
            title = clean_text(link.inner_text())
            snippet = ""
            for selector in [".b_caption p", "p", ".b_algoSlug"]:
                try:
                    snippet = clean_text(block.locator(selector).first.inner_text())
                    if snippet:
                        break
                except Exception:  # noqa: BLE001
                    continue
            if is_useful_url(href):
                records.append({"title": title, "url": href, "snippet": snippet})
        except Exception:  # noqa: BLE001
            continue
        if len(records) >= max_results:
            break

    # 搜索页结构经常变化，保留一个更宽的 fallback。
    if len(records) < max_results:
        for link in page.locator("h2 a").all():
            try:
                href = decode_bing_redirect(link.get_attribute("href") or "")
                title = clean_text(link.inner_text())
                if is_useful_url(href) and href not in {item["url"] for item in records}:
                    records.append({"title": title, "url": href, "snippet": ""})
            except Exception:  # noqa: BLE001
                continue
            if len(records) >= max_results:
                break

    return records[:max_results]


def parse_bing_html_results(html_text: str, max_results: int) -> list[dict[str, str]]:
    """从 Bing HTML 中解析搜索结果。"""
    records: list[dict[str, str]] = []
    blocks = re.findall(r'<li[^>]+class="[^"]*\bb_algo\b[^"]*"[^>]*>.*?</li>', html_text, flags=re.S)
    for block in blocks:
        link_match = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.S)
        if not link_match:
            continue

        href = decode_bing_redirect(html_lib.unescape(link_match.group(1)))
        title = strip_tags(link_match.group(2))
        snippet_match = re.search(r"<p[^>]*>(.*?)</p>", block, flags=re.S)
        snippet = strip_tags(snippet_match.group(1)) if snippet_match else ""
        if is_useful_url(href):
            records.append({"title": title, "url": href, "snippet": snippet})
        if len(records) >= max_results:
            break
    return records[:max_results]


def resolve_sogou_redirect(href: str, headers: dict[str, str], timeout_seconds: float) -> str:
    """解析搜狗 /link 跳转，尽量还原真实 URL。"""
    url = urljoin("https://www.sogou.com", html_lib.unescape(href))
    parsed = urlparse(url)
    if "sogou.com" not in parsed.netloc or not parsed.path.startswith("/link"):
        return url

    try:
        response = requests.get(url, headers=headers, timeout=timeout_seconds, allow_redirects=True)
    except Exception:  # noqa: BLE001
        return url

    if response.url and "sogou.com/link" not in response.url:
        return response.url

    patterns = [
        r'window\.location\.replace\("([^"]+)"\)',
        r"window\.location\.replace\('([^']+)'\)",
        r'URL=\'([^\']+)\'',
        r'URL="([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, response.text, flags=re.S)
        if match:
            return html_lib.unescape(match.group(1))
    return url


def parse_sogou_html_results(
    html_text: str,
    max_results: int,
    headers: dict[str, str],
    timeout_seconds: float,
) -> list[dict[str, str]]:
    """从搜狗 HTML 中解析搜索结果。"""
    records: list[dict[str, str]] = []
    matches = re.findall(r'<h3[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html_text, flags=re.S)
    for href, title_html in matches:
        title = strip_tags(title_html)
        url = resolve_sogou_redirect(href, headers=headers, timeout_seconds=timeout_seconds)
        if not is_useful_url(url):
            continue
        records.append({"title": title, "url": url, "snippet": ""})
        if len(records) >= max_results:
            break
    return records[:max_results]


def build_search_url(query: str, engine: str) -> str:
    """根据搜索引擎生成搜索 URL。"""
    if engine == "bing":
        return f"https://www.bing.com/search?q={quote_plus(query)}&mkt=zh-CN&setlang=zh-Hans&cc=cn"
    return f"https://www.sogou.com/web?query={quote_plus(query)}"


def enrich_query(query: str, append_current_month: bool) -> str:
    """按需在检索 query 后追加当前年月，提升周报搜索时效性。"""
    if not append_current_month:
        return query
    today = pd.Timestamp.today()
    current_month = f"{today.year}年{today.month}月"
    if current_month in query:
        return query
    return f"{query} {current_month}"


def parse_search_results(
    html_text: str,
    engine: str,
    max_results: int,
    headers: dict[str, str],
    timeout_seconds: float,
) -> list[dict[str, str]]:
    """按搜索引擎解析搜索结果。"""
    if engine == "bing":
        return parse_bing_html_results(html_text, max_results=max_results)
    return parse_sogou_html_results(
        html_text,
        max_results=max_results,
        headers=headers,
        timeout_seconds=timeout_seconds,
    )


def build_rows_from_results(query_row: pd.Series, results: list[dict[str, str]], search_url: str) -> list[dict[str, object]]:
    """把单个 query 的搜索结果转成统一输出行。"""
    rows: list[dict[str, object]] = []
    for rank, result in enumerate(results, start=1):
        rows.append(
            {
                "search_date": pd.Timestamp.today().normalize(),
                "topic": query_row["topic"],
                "query": query_row["query"],
                "rank": rank,
                "title": result["title"],
                "url": result["url"],
                "domain": extract_domain(result["url"]),
                "snippet": result["snippet"],
                "driver_names": query_row["driver_names"],
                "notes": query_row["notes"],
                "search_url": search_url,
            }
        )
    return rows


def search_weekly_reports_requests(
    queries: pd.DataFrame,
    max_results: int,
    timeout_ms: int,
    sleep_seconds: float,
    engine: str,
    append_current_month: bool,
) -> pd.DataFrame:
    """使用 requests 搜索每条行业周报 query。"""
    if queries.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    timeout_seconds = max(3, timeout_ms / 1000)
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "zh-CN,zh;q=0.9"}
    rows: list[dict[str, object]] = []
    for _, query_row in queries.iterrows():
        base_query = str(query_row["query"])
        candidate_queries = [enrich_query(base_query, append_current_month=append_current_month)]
        if append_current_month and candidate_queries[0] != base_query:
            candidate_queries.append(base_query)

        results: list[dict[str, str]] = []
        used_query = candidate_queries[0]
        search_url = ""
        for candidate_query in candidate_queries:
            used_query = candidate_query
            search_url = build_search_url(candidate_query, engine=engine)
            print(f"searching weekly reports: {query_row['topic']} -> {search_url}", flush=True)
            try:
                response = requests.get(search_url, headers=headers, timeout=timeout_seconds)
                response.raise_for_status()
                results = parse_search_results(
                    response.text,
                    engine=engine,
                    max_results=max_results,
                    headers=headers,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001 - 单个 query 失败不影响其他链条
                print(f"failed search: {query_row['topic']}; {exc}", flush=True)
                results = []
            if results or candidate_query == candidate_queries[-1]:
                break

        query_row = query_row.copy()
        query_row["query"] = used_query

        rows.extend(build_rows_from_results(query_row, results, search_url))
        if sleep_seconds > 0:
            sleep(sleep_seconds)

    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def search_weekly_reports(
    queries: pd.DataFrame,
    max_results: int,
    timeout_ms: int,
    sleep_seconds: float,
    headful: bool,
    append_current_month: bool,
    engine: str,
) -> pd.DataFrame:
    """使用虚拟浏览器搜索每条行业周报 query。"""
    if queries.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "缺少 playwright，请运行: pip install -r requirements-data.txt && python -m playwright install chromium"
        ) from exc

    rows: list[dict[str, object]] = []
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "zh-CN,zh;q=0.9"}
    timeout_seconds = max(3, timeout_ms / 1000)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headful)
        page = browser.new_page(locale="zh-CN")
        page.set_default_timeout(timeout_ms)

        for _, query_row in queries.iterrows():
            base_query = str(query_row["query"])
            candidate_queries = [enrich_query(base_query, append_current_month=append_current_month)]
            if append_current_month and candidate_queries[0] != base_query:
                candidate_queries.append(base_query)

            results: list[dict[str, str]] = []
            used_query = candidate_queries[0]
            search_url = ""
            for candidate_query in candidate_queries:
                used_query = candidate_query
                search_url = build_search_url(candidate_query, engine=engine)
                print(f"searching weekly reports: {query_row['topic']} -> {search_url}", flush=True)
                try:
                    page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    page.wait_for_selector("body", timeout=timeout_ms)
                    page.wait_for_timeout(2_000)
                    results = parse_search_results(
                        page.content(),
                        engine=engine,
                        max_results=max_results,
                        headers=headers,
                        timeout_seconds=timeout_seconds,
                    )
                except Exception as exc:  # noqa: BLE001 - 单个 query 失败不影响其他链条
                    print(f"failed search: {query_row['topic']}; {exc}", flush=True)
                    results = []
                if results or candidate_query == candidate_queries[-1]:
                    break

            query_row = query_row.copy()
            query_row["query"] = used_query

            rows.extend(build_rows_from_results(query_row, results, search_url))
            if sleep_seconds > 0:
                sleep(sleep_seconds)

        browser.close()

    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def main() -> None:
    """运行行业周报候选链接检索。"""
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]

    queries = read_queries(project_root / args.query_config, limit_queries=args.limit_queries)
    if args.method == "browser":
        links = search_weekly_reports(
            queries,
            max_results=args.max_results,
            timeout_ms=args.timeout_ms,
            sleep_seconds=args.sleep_seconds,
            headful=args.headful,
            append_current_month=args.append_current_month,
            engine=args.engine,
        )
    else:
        links = search_weekly_reports_requests(
            queries,
            max_results=args.max_results,
            timeout_ms=args.timeout_ms,
            sleep_seconds=args.sleep_seconds,
            engine=args.engine,
            append_current_month=args.append_current_month,
        )

    output_path = project_root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    links.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"saved weekly report links: {output_path} ({len(links)} rows)")

    review = links.head(min(len(links), args.max_results * max(1, min(len(queries), 3)))).copy()
    review_path = project_root / args.review_output
    review_path.parent.mkdir(parents=True, exist_ok=True)
    if review.empty and review_path.exists() and review_path.stat().st_size > 200:
        print(f"empty review result; keep existing non-empty sample: {review_path}")
    else:
        review.to_csv(review_path, index=False, encoding="utf-8-sig")
        print(f"saved review sample: {review_path} ({len(review)} rows)")
    if not review.empty:
        print(review[["topic", "rank", "domain", "title"]].to_string(index=False))


if __name__ == "__main__":
    main()
