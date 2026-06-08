"""Fetch driver inventory proxy data from AkShare.

This script prioritizes AkShare's `futures_inventory_em` interface. The data is
not always the exact social inventory of each chemical product. In this project
it is treated as an exchange warehouse receipt / inventory proxy and is kept
separate from price drivers so the research logic stays auditable.

Examples:
    python scripts/fetch_driver_inventory_akshare.py --coverage-only
    python scripts/fetch_driver_inventory_akshare.py --output data/raw/driver_inventory_akshare.csv
"""

from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path
from time import sleep

import pandas as pd


SOURCE_COLUMNS = [
    "driver_name",
    "source_type",
    "source_symbol",
    "source_name",
    "source_status",
    "unit",
    "frequency",
    "is_active",
    "priority",
    "notes",
]


def parse_args() -> Namespace:
    """解析命令行参数。"""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-config",
        type=Path,
        default=Path("config/driver_inventory_sources.csv"),
        help="driver 到库存源的映射配置。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/driver_inventory_akshare.csv"),
        help="输出库存数据路径。默认写入 data/raw，不提交到 GitHub。",
    )
    parser.add_argument(
        "--coverage-output",
        type=Path,
        default=Path("data/review/abc_driver_inventory_source_coverage.csv"),
        help="ABC 池 driver 库存源覆盖率报告输出路径。",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("data/review/abc_driver_inventory_source_summary.csv"),
        help="ABC 池 driver 库存源覆盖率汇总输出路径。",
    )
    parser.add_argument(
        "--source-status",
        default="exchange_proxy",
        help="要拉取的 source_status，逗号分隔。默认只拉 exchange_proxy。",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="同时允许 is_active=0 的 source 行。通常仅用于调试 upstream_proxy。",
    )
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="只生成覆盖率报告，不请求 AkShare。",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.2,
        help="单个 AkShare symbol 请求后的暂停秒数，避免请求过密。",
    )
    return parser.parse_args()


def read_inventory_sources(path: Path) -> pd.DataFrame:
    """读取 driver 库存源映射配置。"""
    sources = pd.read_csv(path)
    missing = set(SOURCE_COLUMNS) - set(sources.columns)
    if missing:
        raise ValueError(f"{path} 缺少字段: {sorted(missing)}")

    sources = sources[SOURCE_COLUMNS].copy()
    sources["is_active"] = pd.to_numeric(sources["is_active"], errors="coerce").fillna(0).astype(int)
    sources["priority"] = pd.to_numeric(sources["priority"], errors="coerce").fillna(99).astype(int)
    return sources.sort_values(["driver_name", "priority"]).reset_index(drop=True)


def build_abc_driver_coverage(project_root: Path, sources: pd.DataFrame) -> pd.DataFrame:
    """生成 ABC 池中 ticker-driver 对库存源的覆盖率报告。"""
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

    # source 缺失的 driver 要显式暴露出来，方便后续补源。
    coverage["source_type"] = coverage["source_type"].fillna("missing_config")
    coverage["source_status"] = coverage["source_status"].fillna("missing_config")
    coverage["frequency"] = coverage["frequency"].fillna("")
    coverage["is_active"] = pd.to_numeric(coverage["is_active"], errors="coerce").fillna(0).astype(int)
    coverage["is_inventory_auto_available"] = (
        (coverage["source_type"] == "akshare_futures_inventory_em")
        & (coverage["source_status"] == "exchange_proxy")
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
        "frequency",
        "is_inventory_auto_available",
        "unit",
        "notes",
    ]
    return coverage[ordered_cols].sort_values(["pool_tier", "ticker", "driver_name"]).reset_index(drop=True)


def parse_number(series: pd.Series) -> pd.Series:
    """将可能带逗号或空格的中文网页数字列转成数值。"""
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("，", "", regex=False)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce")


def normalize_inventory_frame(raw: pd.DataFrame, source_symbol: str) -> pd.DataFrame:
    """标准化 AkShare 库存返回结果。"""
    if raw.empty:
        return pd.DataFrame(columns=["date", "source_symbol", "inventory", "inventory_change"])

    rename_map = {
        "日期": "date",
        "库存": "inventory",
        "增减": "inventory_change",
    }
    df = raw.rename(columns=rename_map).copy()
    required = {"date", "inventory"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"AkShare 库存字段缺失: {sorted(missing)}; columns={df.columns.tolist()}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["inventory"] = parse_number(df["inventory"])
    if "inventory_change" in df.columns:
        df["inventory_change"] = parse_number(df["inventory_change"])
    else:
        df["inventory_change"] = pd.NA
    df["source_symbol"] = source_symbol
    df = df.dropna(subset=["date", "inventory"])
    return df[["date", "source_symbol", "inventory", "inventory_change"]].drop_duplicates(["date", "source_symbol"])


def fetch_akshare_inventory(source_rows: pd.DataFrame, sleep_seconds: float = 0.2) -> pd.DataFrame:
    """逐个调用 AkShare 拉取东方财富期货库存。"""
    if source_rows.empty:
        return pd.DataFrame(columns=["date", "source_symbol", "inventory", "inventory_change"])

    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError("缺少 akshare，请先运行: pip install -r requirements-data.txt") from exc

    frames = []
    symbols = sorted(source_rows["source_symbol"].dropna().astype(str).unique().tolist())
    for symbol in symbols:
        try:
            raw = ak.futures_inventory_em(symbol=symbol)
            frame = normalize_inventory_frame(raw, symbol)
            frames.append(frame)
            print(f"fetched inventory: {symbol} ({len(frame)} rows)")
        except Exception as exc:  # noqa: BLE001 - 数据源脚本要继续抓其他品种
            print(f"failed inventory: {symbol}; {exc}")
        if sleep_seconds > 0:
            sleep(sleep_seconds)

    if not frames:
        return pd.DataFrame(columns=["date", "source_symbol", "inventory", "inventory_change"])
    return pd.concat(frames, ignore_index=True).sort_values(["date", "source_symbol"]).reset_index(drop=True)


def build_driver_inventory_table(inventory: pd.DataFrame, source_rows: pd.DataFrame) -> pd.DataFrame:
    """将 source_symbol 库存展开为项目 driver_inventory 格式。"""
    output_cols = [
        "date",
        "driver_name",
        "inventory",
        "inventory_change",
        "source_type",
        "source_symbol",
        "source_name",
        "source_status",
        "unit",
        "frequency",
    ]
    if inventory.empty or source_rows.empty:
        return pd.DataFrame(columns=output_cols)

    meta_cols = [
        "driver_name",
        "source_type",
        "source_symbol",
        "source_name",
        "source_status",
        "unit",
        "frequency",
    ]
    source_meta = source_rows[meta_cols].drop_duplicates()
    source_meta["source_symbol"] = source_meta["source_symbol"].astype(str)

    result = inventory.merge(source_meta, on="source_symbol", how="inner")
    result = result.sort_values(["date", "driver_name"]).reset_index(drop=True)
    return result[output_cols]


def write_summary(coverage: pd.DataFrame, summary_path: Path) -> pd.DataFrame:
    """输出库存源覆盖率汇总。"""
    summary = (
        coverage.groupby(["pool_tier", "source_status"], dropna=False)
        .agg(
            rows=("driver_name", "size"),
            unique_drivers=("driver_name", "nunique"),
            unique_tickers=("ticker", "nunique"),
            auto_rows=("is_inventory_auto_available", "sum"),
        )
        .reset_index()
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    return summary


def main() -> None:
    """运行 AkShare driver 库存抓取。"""
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]

    sources = read_inventory_sources(project_root / args.source_config)
    coverage = build_abc_driver_coverage(project_root, sources)

    coverage_path = project_root / args.coverage_output
    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(coverage_path, index=False, encoding="utf-8-sig")
    print(f"saved coverage: {coverage_path} ({len(coverage)} rows)")

    summary = write_summary(coverage, project_root / args.summary_output)
    print(f"saved summary: {project_root / args.summary_output}")
    print(summary.to_string(index=False))

    if args.coverage_only:
        return

    allowed_status = {item.strip() for item in args.source_status.split(",") if item.strip()}
    fetch_rows = sources[
        (sources["source_type"] == "akshare_futures_inventory_em")
        & (sources["source_status"].isin(allowed_status))
        & (sources["source_symbol"].fillna("").astype(str).str.len() > 0)
    ].copy()
    if not args.include_inactive:
        fetch_rows = fetch_rows[fetch_rows["is_active"] == 1].copy()

    print(f"fetching {fetch_rows['source_symbol'].nunique()} AkShare inventory symbols")
    inventory = fetch_akshare_inventory(fetch_rows, sleep_seconds=args.sleep_seconds)
    driver_inventory = build_driver_inventory_table(inventory, fetch_rows)

    output_path = project_root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    driver_inventory.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"saved driver inventory: {output_path} ({len(driver_inventory)} rows)")
    if not driver_inventory.empty:
        stats = driver_inventory.groupby("driver_name").agg(
            start=("date", "min"),
            end=("date", "max"),
            rows=("inventory", "size"),
        )
        print(stats.to_string())


if __name__ == "__main__":
    main()
