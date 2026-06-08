from pathlib import Path

import numpy as np
import pandas as pd

from src.utils import get_month_end_dates


STATIC_POOL_COLUMNS = ["ticker", "company_name", "sub_industry", "pool_tier"]


def read_static_pool(path: Path) -> pd.DataFrame:
    """读取静态 B/C 股票池配置。"""
    static_pool = pd.read_csv(path)
    missing = set(STATIC_POOL_COLUMNS) - set(static_pool.columns)
    if missing:
        raise ValueError(f"{path} 缺少字段: {sorted(missing)}")

    static_pool = static_pool.copy()
    static_pool["pool_tier"] = static_pool["pool_tier"].astype(str).str.upper().str.strip()
    valid_tiers = {"B", "C"}
    invalid_tiers = sorted(set(static_pool["pool_tier"]) - valid_tiers)
    if invalid_tiers:
        raise ValueError(f"{path} 存在未知 pool_tier: {invalid_tiers}")

    if "is_active" not in static_pool.columns:
        static_pool["is_active"] = 1
    static_pool["is_active"] = pd.to_numeric(static_pool["is_active"], errors="coerce").fillna(1).astype(int)

    return static_pool.sort_values(["pool_tier", "ticker"]).reset_index(drop=True)


def _empty_a_pool() -> pd.DataFrame:
    """返回动态 A 池的空表结构。"""
    return pd.DataFrame(
        columns=[
            "rebalance_date",
            "target_pool",
            "source_pool",
            "ticker",
            "company_name",
            "sub_industry",
            "signal_rank",
            "signal_percentile",
            "factor",
            "signal_value",
            "driver_mom_value",
            "stock_mom_value",
            "pool_reason",
            "selection_rule",
        ]
    )


def build_dynamic_a_pool(
    factor_data: pd.DataFrame,
    static_pool: pd.DataFrame,
    factor_col: str = "driver_stock_gap_20d",
    driver_mom_col: str = "driver_mom_20d",
    stock_mom_col: str = "stock_mom_20d",
    eligible_pools: tuple[str, ...] = ("B",),
    top_n: int = 5,
    min_driver_mom: float | None = 0.0,
) -> pd.DataFrame:
    """按月末 driver-stock gap 从 B/C 静态池中筛选动态 A 池。

    A 池代表预计持股池。默认只从 B 池里选，并要求产品端 driver momentum
    非负，避免把“产品已经下跌但股票跌更多”的标的误选进来。
    """
    if factor_data.empty or static_pool.empty:
        return _empty_a_pool()

    required_factor_cols = {"date", "ticker", factor_col}
    if driver_mom_col:
        required_factor_cols.add(driver_mom_col)
    if stock_mom_col:
        required_factor_cols.add(stock_mom_col)
    missing = required_factor_cols - set(factor_data.columns)
    if missing:
        raise ValueError(f"factor_data 缺少字段: {sorted(missing)}")

    eligible_pool_names = {pool.upper() for pool in eligible_pools}
    active_pool = static_pool[
        (static_pool["pool_tier"].isin(eligible_pool_names)) & (static_pool["is_active"] == 1)
    ].copy()
    if active_pool.empty:
        return _empty_a_pool()

    factor_cols = ["date", "ticker", factor_col]
    if driver_mom_col:
        factor_cols.append(driver_mom_col)
    if stock_mom_col:
        factor_cols.append(stock_mom_col)

    cross_sections = factor_data[factor_cols].dropna(subset=[factor_col]).copy()
    cross_sections["date"] = pd.to_datetime(cross_sections["date"])

    pool_cols = ["ticker", "company_name", "sub_industry", "pool_tier"]
    if "pool_reason" in active_pool.columns:
        pool_cols.append("pool_reason")
    else:
        active_pool["pool_reason"] = ""
        pool_cols.append("pool_reason")

    cross_sections = cross_sections.merge(active_pool[pool_cols], on="ticker", how="inner")
    if cross_sections.empty:
        return _empty_a_pool()

    if driver_mom_col and min_driver_mom is not None:
        # 产品端动量需要不低于阈值，贴合“产品已经上涨/不弱”的研究假设。
        cross_sections = cross_sections[cross_sections[driver_mom_col] >= min_driver_mom].copy()
        if cross_sections.empty:
            return _empty_a_pool()

    rebalance_dates = get_month_end_dates(cross_sections["date"])
    rows = []
    selection_rule = (
        f"source_pool={','.join(sorted(eligible_pool_names))}; "
        f"sort={factor_col} desc; top_n={top_n}; "
        f"{driver_mom_col}>={min_driver_mom if min_driver_mom is not None else 'NA'}"
    )

    for rebalance_date in rebalance_dates:
        cross_section = cross_sections[cross_sections["date"] == rebalance_date].copy()
        if cross_section.empty:
            continue

        cross_section = cross_section.sort_values([factor_col, "ticker"], ascending=[False, True]).reset_index(drop=True)
        cross_section["signal_rank"] = np.arange(1, len(cross_section) + 1)
        cross_section["signal_percentile"] = 1 - (cross_section["signal_rank"] - 1) / max(len(cross_section), 1)

        selected = cross_section.head(top_n).copy()
        for row in selected.itertuples(index=False):
            rows.append(
                {
                    "rebalance_date": rebalance_date,
                    "target_pool": "A",
                    "source_pool": row.pool_tier,
                    "ticker": row.ticker,
                    "company_name": row.company_name,
                    "sub_industry": row.sub_industry,
                    "signal_rank": int(row.signal_rank),
                    "signal_percentile": float(row.signal_percentile),
                    "factor": factor_col,
                    "signal_value": float(getattr(row, factor_col)),
                    "driver_mom_value": float(getattr(row, driver_mom_col)) if driver_mom_col else np.nan,
                    "stock_mom_value": float(getattr(row, stock_mom_col)) if stock_mom_col else np.nan,
                    "pool_reason": row.pool_reason,
                    "selection_rule": selection_rule,
                }
            )

    if not rows:
        return _empty_a_pool()
    return pd.DataFrame(rows).sort_values(["rebalance_date", "signal_rank", "ticker"]).reset_index(drop=True)


def get_latest_a_pool(dynamic_a_pool: pd.DataFrame) -> pd.DataFrame:
    """取最近一期动态 A 池。"""
    if dynamic_a_pool.empty:
        return _empty_a_pool()
    latest_date = pd.to_datetime(dynamic_a_pool["rebalance_date"]).max()
    latest = dynamic_a_pool[pd.to_datetime(dynamic_a_pool["rebalance_date"]) == latest_date].copy()
    return latest.sort_values(["signal_rank", "ticker"]).reset_index(drop=True)
