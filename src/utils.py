from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED_DIRS = [
    "data/raw",
    "data/processed",
    "data/sample",
    "config",
    "docs",
    "scripts",
    "notebooks",
    "outputs/figures",
    "outputs/tables",
    "outputs/logs",
]


def ensure_directories(project_root: Path) -> None:
    """创建项目运行所需目录。"""
    for relative_path in REQUIRED_DIRS:
        (project_root / relative_path).mkdir(parents=True, exist_ok=True)


def save_table(df: pd.DataFrame, path: Path, index: bool = False) -> None:
    """以 utf-8-sig 保存表格，方便 Excel 直接打开中文。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=index, encoding="utf-8-sig")


def get_month_end_dates(dates: pd.Series) -> list[pd.Timestamp]:
    """从交易日序列中取每个自然月的最后一个可用日期。"""
    date_series = pd.Series(pd.to_datetime(dates)).dropna().drop_duplicates().sort_values()
    if date_series.empty:
        return []
    return date_series.groupby(date_series.dt.to_period("M")).max().tolist()


def assign_quantile_groups(values: pd.Series, n_groups: int = 5) -> pd.Series:
    """根据因子值分组，G1 为低因子组，G{n_groups} 为高因子组。"""
    result = pd.Series(np.nan, index=values.index, dtype="float")
    valid = values.dropna()

    if len(valid) < n_groups or valid.nunique() < 2:
        return result

    # 使用 rank(method="first") 处理重复值，保证 qcut 可以稳定分组。
    ranks = valid.rank(method="first")
    groups = pd.qcut(ranks, q=n_groups, labels=np.arange(1, n_groups + 1))
    result.loc[valid.index] = groups.astype(float)
    return result
