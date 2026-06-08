"""Fetch annual report metadata from CNINFO via AKShare.

This script saves announcement metadata only. PDF parsing and capacity
verification should be handled as a separate, auditable step.
"""

from argparse import ArgumentParser
from pathlib import Path

import pandas as pd


def _load_akshare():
    """按需导入 AKShare，避免主流程依赖数据采集包。"""
    try:
        import akshare as ak
    except ImportError as exc:
        raise SystemExit("请先运行: pip install -r requirements-data.txt") from exc
    return ak


def _to_cn_stock_code(ticker: str) -> str:
    """将 600309.SH 转换为 AKShare 所需的 600309。"""
    return str(ticker).split(".")[0]


def fetch_reports(universe_path: Path, start_date: str, end_date: str, category: str) -> pd.DataFrame:
    """抓取股票池内公司的巨潮资讯公告元数据。"""
    ak = _load_akshare()
    universe = pd.read_csv(universe_path)
    frames = []

    for row in universe.itertuples(index=False):
        symbol = _to_cn_stock_code(row.ticker)
        try:
            reports = ak.stock_zh_a_disclosure_report_cninfo(
                symbol=symbol,
                market="沪深京",
                category=category,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as exc:  # noqa: BLE001 - 数据接口偶发失败时继续抓其他公司
            print(f"[WARN] {row.ticker} {row.company_name} 抓取失败: {exc}")
            continue

        if reports.empty:
            continue

        reports = reports.copy()
        reports.insert(0, "ticker", row.ticker)
        reports.insert(1, "company_name", row.company_name)
        frames.append(reports)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    """命令行入口。"""
    parser = ArgumentParser(description="Fetch CNINFO annual report metadata via AKShare.")
    parser.add_argument("--start-date", default="20200101", help="起始日期，格式 YYYYMMDD")
    parser.add_argument("--end-date", default="20251231", help="结束日期，格式 YYYYMMDD")
    parser.add_argument("--category", default="年报", help="公告类别，例如 年报、半年报")
    parser.add_argument("--universe", default="config/universe.csv", help="股票池文件")
    parser.add_argument("--output", default="data/raw/cninfo_reports.csv", help="输出 CSV 路径")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    output_path = project_root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    reports = fetch_reports(
        universe_path=project_root / args.universe,
        start_date=args.start_date,
        end_date=args.end_date,
        category=args.category,
    )
    reports.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"Saved {len(reports):,} rows to {output_path}")


if __name__ == "__main__":
    main()
