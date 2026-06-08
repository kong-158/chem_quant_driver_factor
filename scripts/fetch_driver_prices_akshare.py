"""Fetch driver price history from AkShare/100ppi.

The script follows the data approach used by the open-source
chemical-dashboard project: `ak.futures_spot_price_daily` fetches daily
spot prices from 生意社/100ppi for commodity symbols with futures contracts.

Examples:
    python scripts/fetch_driver_prices_akshare.py --start-date 2025-01-01 --end-date 2025-12-31
    python scripts/fetch_driver_prices_akshare.py --source-status exact,proxy --output data/raw/driver_prices.csv
"""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import warnings

import pandas as pd


SOURCE_COLUMNS = [
    "driver_name",
    "source_type",
    "source_symbol",
    "source_name",
    "source_status",
    "price_field",
    "unit",
    "is_active",
    "priority",
    "notes",
]


def parse_args() -> ArgumentParser:
    """解析命令行参数。"""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default=None, help="开始日期，支持 YYYY-MM-DD 或 YYYYMMDD；默认按 lookback-days 回看。")
    parser.add_argument("--end-date", default=None, help="结束日期，默认使用今天。")
    parser.add_argument("--lookback-days", type=int, default=180, help="未指定 start-date 时，默认回看的日历天数。")
    parser.add_argument(
        "--source-config",
        type=Path,
        default=Path("config/driver_price_sources.csv"),
        help="driver 到价格源的映射配置。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/driver_prices_akshare.csv"),
        help="输出价格数据路径。可指定为 data/raw/driver_prices.csv 直接供 main.py 使用。",
    )
    parser.add_argument(
        "--coverage-output",
        type=Path,
        default=Path("data/review/abc_driver_price_source_coverage.csv"),
        help="ABC 池 driver 价格源覆盖率报告输出路径。",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("data/review/abc_driver_price_source_summary.csv"),
        help="ABC 池 driver 价格源覆盖率汇总输出路径。",
    )
    parser.add_argument(
        "--source-status",
        default="exact",
        help="要拉取的 source_status，逗号分隔。默认只拉 exact；可填 exact,proxy,upstream_proxy。",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="同时允许 is_active=0 的 source 行。通常仅用于调试 proxy。",
    )
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="只生成覆盖率报告，不请求 AkShare。",
    )
    return parser.parse_args()


def read_price_sources(path: Path) -> pd.DataFrame:
    """读取 driver 价格源映射配置。"""
    sources = pd.read_csv(path)
    missing = set(SOURCE_COLUMNS) - set(sources.columns)
    if missing:
        raise ValueError(f"{path} 缺少字段: {sorted(missing)}")

    sources = sources[SOURCE_COLUMNS].copy()
    sources["is_active"] = pd.to_numeric(sources["is_active"], errors="coerce").fillna(0).astype(int)
    sources["priority"] = pd.to_numeric(sources["priority"], errors="coerce").fillna(99).astype(int)
    return sources.sort_values(["driver_name", "priority"]).reset_index(drop=True)


def build_abc_driver_coverage(project_root: Path, sources: pd.DataFrame) -> pd.DataFrame:
    """生成 ABC 池中 ticker-driver 对价格源的覆盖率报告。"""
    static_pool_path = project_root / "config" / "universe_pool_static.csv"
    base_mapping_path = project_root / "config" / "driver_mapping.csv"
    candidate_mapping_path = project_root / "config" / "driver_mapping_heavy_chemical_candidates.csv"

    static_pool = pd.read_csv(static_pool_path)
    base_mapping = pd.read_csv(base_mapping_path)
    candidate_mapping = pd.read_csv(candidate_mapping_path)
    all_mapping = pd.concat([base_mapping, candidate_mapping], ignore_index=True, sort=False)
    all_mapping = all_mapping.drop_duplicates(["ticker", "driver_name"], keep="first")

    pool_cols = ["ticker", "pool_tier", "is_active", "source", "review_status"]
    pool_meta = static_pool[pool_cols].rename(columns={"is_active": "pool_is_active", "source": "pool_source"})
    coverage = all_mapping.merge(pool_meta, on="ticker", how="inner")
    coverage = coverage.merge(sources, on="driver_name", how="left")
    coverage["source_type"] = coverage["source_type"].fillna("missing_config")
    coverage["source_status"] = coverage["source_status"].fillna("missing_config")
    coverage["is_active"] = pd.to_numeric(coverage["is_active"], errors="coerce").fillna(0).astype(int)
    coverage["is_price_auto_available"] = (
        (coverage["source_type"] == "akshare_futures_spot")
        & (coverage["source_status"] == "exact")
        & (coverage["is_active"] == 1)
    )

    ordered_cols = [
        "ticker",
        "company_name",
        "sub_industry",
        "pool_tier",
        "driver_name",
        "driver_weight",
        "source_type",
        "source_symbol",
        "source_name",
        "source_status",
        "is_price_auto_available",
        "unit",
        "notes",
    ]
    return coverage[ordered_cols].sort_values(["pool_tier", "ticker", "driver_name"]).reset_index(drop=True)


def normalize_akshare_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """兼容不同 AkShare 版本返回的列名。"""
    if raw.empty:
        return pd.DataFrame(columns=["date", "source_symbol", "price"])

    df = raw.copy()
    rename_map = {}
    if "var" in df.columns and "symbol" not in df.columns:
        rename_map["var"] = "symbol"
    if "sp" in df.columns and "spot_price" not in df.columns:
        rename_map["sp"] = "spot_price"
    df = df.rename(columns=rename_map)

    required = {"date", "symbol", "spot_price"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"AkShare 返回字段缺失: {sorted(missing)}; columns={df.columns.tolist()}")

    normalized = df[["date", "symbol", "spot_price"]].copy()
    normalized["date"] = pd.to_datetime(normalized["date"])
    normalized["source_symbol"] = normalized["symbol"].astype(str).str.upper()
    normalized["price"] = pd.to_numeric(normalized["spot_price"], errors="coerce")
    normalized = normalized.dropna(subset=["date", "source_symbol", "price"])
    return normalized[["date", "source_symbol", "price"]].drop_duplicates(["date", "source_symbol"])


def fetch_akshare_prices(start_date: str, end_date: str | None, symbols: list[str]) -> pd.DataFrame:
    """调用 AkShare 拉取生意社期现日频现货价格。"""
    if not symbols:
        return pd.DataFrame(columns=["date", "source_symbol", "price"])

    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError("缺少 akshare，请先运行: pip install -r requirements-data.txt") from exc

    end = end_date or pd.Timestamp.today().strftime("%Y-%m-%d")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=r".*非交易日.*", category=UserWarning)
        raw = ak.futures_spot_price_daily(
            start_day=start_date,
            end_day=end,
            vars_list=symbols,
        )
    return normalize_akshare_frame(raw)


def build_driver_price_table(prices: pd.DataFrame, source_rows: pd.DataFrame) -> pd.DataFrame:
    """将 source_symbol 价格展开为项目 driver_prices 格式。"""
    if prices.empty or source_rows.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "driver_name",
                "price",
                "source_type",
                "source_symbol",
                "source_name",
                "source_status",
                "unit",
            ]
        )

    meta_cols = ["driver_name", "source_type", "source_symbol", "source_name", "source_status", "unit"]
    source_meta = source_rows[meta_cols].drop_duplicates()
    source_meta["source_symbol"] = source_meta["source_symbol"].astype(str).str.upper()

    result = prices.merge(source_meta, on="source_symbol", how="inner")
    result = result.sort_values(["date", "driver_name"]).reset_index(drop=True)
    return result[["date", "driver_name", "price", "source_type", "source_symbol", "source_name", "source_status", "unit"]]


def main() -> None:
    """运行 AkShare driver 价格抓取。"""
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]

    sources = read_price_sources(project_root / args.source_config)
    coverage = build_abc_driver_coverage(project_root, sources)
    coverage_path = project_root / args.coverage_output
    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(coverage_path, index=False, encoding="utf-8-sig")
    print(f"saved coverage: {coverage_path} ({len(coverage)} rows)")

    summary = (
        coverage.groupby(["pool_tier", "source_status"], dropna=False)
        .agg(rows=("driver_name", "size"), unique_drivers=("driver_name", "nunique"), unique_tickers=("ticker", "nunique"))
        .reset_index()
    )
    summary_path = project_root / args.summary_output
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"saved summary: {summary_path}")
    print(summary.to_string(index=False))

    if args.coverage_only:
        return

    allowed_status = {item.strip() for item in args.source_status.split(",") if item.strip()}
    fetch_rows = sources[
        (sources["source_type"] == "akshare_futures_spot")
        & (sources["source_status"].isin(allowed_status))
        & (sources["source_symbol"].fillna("").astype(str).str.len() > 0)
    ].copy()
    if not args.include_inactive:
        fetch_rows = fetch_rows[fetch_rows["is_active"] == 1].copy()

    symbols = sorted(fetch_rows["source_symbol"].astype(str).str.upper().unique().tolist())
    print(f"fetching {len(symbols)} AkShare symbols: {symbols}")

    end_date = args.end_date or pd.Timestamp.today().strftime("%Y-%m-%d")
    start_date = args.start_date or (pd.to_datetime(end_date) - pd.Timedelta(days=args.lookback_days)).strftime("%Y-%m-%d")
    print(f"date range: {start_date} to {end_date}")

    prices = fetch_akshare_prices(start_date, end_date, symbols)
    driver_prices = build_driver_price_table(prices, fetch_rows)

    output_path = project_root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    driver_prices.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"saved driver prices: {output_path} ({len(driver_prices)} rows)")
    if not driver_prices.empty:
        print(driver_prices.groupby("driver_name").agg(start=("date", "min"), end=("date", "max"), rows=("price", "size")).to_string())


if __name__ == "__main__":
    main()
