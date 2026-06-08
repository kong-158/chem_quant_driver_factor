"""Fetch annual report metadata from CNINFO via AKShare.

This script saves announcement metadata only. PDF parsing and capacity
verification should be handled as a separate, auditable step.
"""

from argparse import ArgumentParser
from datetime import date
from pathlib import Path

import pandas as pd


DATE_COLUMNS = ["公告日期", "公告时间", "披露日期", "date", "announcement_date"]
TITLE_COLUMNS = ["公告标题", "标题", "title"]


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


def infer_latest_annual_report_window(today: date | None = None) -> tuple[int, str, str]:
    """推导最新年报披露查询窗口。

    A 股年报通常在报告期次年披露。以 2026-06-08 为例，最新完整年报
    是 2025 年年报，查询窗口应从 2026-01-01 到当天。
    """
    today = today or date.today()
    report_year = today.year - 1
    start_date = date(today.year, 1, 1).strftime("%Y%m%d")
    end_date = today.strftime("%Y%m%d")
    return report_year, start_date, end_date


def _find_column(columns: list[str], candidates: list[str]) -> str | None:
    """在不同数据源字段名中寻找目标列。"""
    column_list = [str(col) for col in columns]
    for candidate in candidates:
        if candidate in column_list:
            return candidate

    for col in column_list:
        if any(candidate in col for candidate in candidates):
            return col
    return None


def select_latest_reports(reports: pd.DataFrame, report_year: int | None = None) -> pd.DataFrame:
    """每家公司保留最新且最像“年报全文”的公告。"""
    if reports.empty or "ticker" not in reports.columns:
        return reports

    df = reports.copy()
    title_col = _find_column(df.columns.tolist(), TITLE_COLUMNS)
    date_col = _find_column(df.columns.tolist(), DATE_COLUMNS)

    if title_col:
        title = df[title_col].fillna("").astype(str)
        df["_report_score"] = 0
        if report_year:
            df.loc[title.str.contains(str(report_year), regex=False), "_report_score"] += 20
        df.loc[title.str.contains("年度报告", regex=False), "_report_score"] += 20
        df.loc[title.str.contains("年报", regex=False), "_report_score"] += 8
        # 优先年报全文；摘要、更正、补充、英文版通常不适合直接提取产能。
        for bad_word in ["摘要", "更正", "补充", "取消", "英文", "已取消"]:
            df.loc[title.str.contains(bad_word, regex=False), "_report_score"] -= 15
    else:
        df["_report_score"] = 0

    if date_col:
        df["_announcement_date"] = pd.to_datetime(df[date_col], errors="coerce")
    else:
        df["_announcement_date"] = pd.NaT

    sort_cols = ["ticker", "_report_score", "_announcement_date"]
    df = df.sort_values(sort_cols, ascending=[True, False, False])
    df = df.groupby("ticker", as_index=False).head(1)
    return df.drop(columns=["_report_score", "_announcement_date"], errors="ignore").reset_index(drop=True)


def fetch_reports(
    universe_path: Path,
    start_date: str,
    end_date: str,
    category: str,
    latest_only: bool = True,
    report_year: int | None = None,
) -> pd.DataFrame:
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

    reports = pd.concat(frames, ignore_index=True)
    if latest_only:
        reports = select_latest_reports(reports, report_year=report_year)
    return reports


def main() -> None:
    """命令行入口。"""
    report_year, default_start_date, default_end_date = infer_latest_annual_report_window()
    parser = ArgumentParser(description="Fetch CNINFO annual report metadata via AKShare.")
    parser.add_argument("--start-date", default=default_start_date, help="起始日期，格式 YYYYMMDD")
    parser.add_argument("--end-date", default=default_end_date, help="结束日期，格式 YYYYMMDD")
    parser.add_argument("--category", default="年报", help="公告类别，例如 年报、半年报")
    parser.add_argument("--report-year", type=int, default=report_year, help="目标报告期年份")
    parser.add_argument("--keep-all", action="store_true", help="保留查询窗口内全部公告，不做 latest-only 筛选")
    parser.add_argument("--universe", default="config/universe.csv", help="股票池文件")
    parser.add_argument("--output", default="data/raw/cninfo_latest_reports.csv", help="输出 CSV 路径")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    output_path = project_root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    reports = fetch_reports(
        universe_path=project_root / args.universe,
        start_date=args.start_date,
        end_date=args.end_date,
        category=args.category,
        latest_only=not args.keep_all,
        report_year=args.report_year,
    )
    reports.to_csv(output_path, index=False, encoding="utf-8-sig")
    latest_text = "latest-only" if not args.keep_all else "all matches"
    print(
        f"Saved {len(reports):,} rows to {output_path} "
        f"({latest_text}, report_year={args.report_year}, window={args.start_date}-{args.end_date})"
    )


if __name__ == "__main__":
    main()
