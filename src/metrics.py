import numpy as np
import pandas as pd
from scipy.stats import spearmanr


def calculate_rank_ic(
    data: pd.DataFrame,
    factor_col: str,
    return_col: str,
    min_count: int = 5,
) -> pd.DataFrame:
    """逐日计算因子与未来收益的 Spearman Rank IC。"""
    rows = []
    use_cols = ["date", "ticker", factor_col, return_col]
    clean = data[use_cols].dropna(subset=[factor_col, return_col]).copy()

    for date, group in clean.groupby("date"):
        if len(group) < min_count or group[factor_col].nunique() < 2 or group[return_col].nunique() < 2:
            ic = np.nan
        else:
            ic = spearmanr(group[factor_col], group[return_col]).correlation

        rows.append(
            {
                "date": date,
                "factor": factor_col,
                "return_col": return_col,
                "rank_ic": ic,
                "n_stocks": len(group),
            }
        )

    return pd.DataFrame(rows)


def calculate_rank_ic_batch(
    data: pd.DataFrame,
    factor_cols: list[str],
    return_cols: list[str],
    min_count: int = 5,
) -> pd.DataFrame:
    """批量计算多个因子和多个收益标签的 Rank IC。"""
    ic_frames = []
    for factor_col in factor_cols:
        for return_col in return_cols:
            ic_frames.append(calculate_rank_ic(data, factor_col, return_col, min_count=min_count))

    if not ic_frames:
        return pd.DataFrame(columns=["date", "factor", "return_col", "rank_ic", "n_stocks"])
    return pd.concat(ic_frames, ignore_index=True)


def summarize_ic(ic_series: pd.DataFrame) -> pd.DataFrame:
    """汇总 IC 均值、标准差、ICIR、正 IC 占比等指标。"""
    rows = []

    for (factor, return_col), group in ic_series.groupby(["factor", "return_col"]):
        values = group["rank_ic"].dropna()
        if values.empty:
            mean_ic = std_ic = icir = positive_ratio = np.nan
            count = 0
        else:
            mean_ic = values.mean()
            std_ic = values.std(ddof=1)
            icir = mean_ic / std_ic if std_ic and not np.isnan(std_ic) else np.nan
            positive_ratio = (values > 0).mean()
            count = len(values)

        rows.append(
            {
                "factor": factor,
                "return_col": return_col,
                "ic_mean": mean_ic,
                "ic_std": std_ic,
                "icir": icir,
                "positive_ic_ratio": positive_ratio,
                "n_periods": count,
            }
        )

    return pd.DataFrame(rows).sort_values(["return_col", "factor"]).reset_index(drop=True)


def calculate_drawdown_series(returns: pd.Series) -> pd.Series:
    """根据收益序列计算回撤序列。"""
    ret = pd.Series(returns).dropna()
    cumulative = (1 + ret).cumprod()
    running_max = cumulative.cummax()
    return cumulative / running_max - 1


def performance_stats(returns: pd.Series, periods_per_year: int = 12) -> dict:
    """计算年化收益、年化波动、夏普比率、最大回撤和胜率。"""
    ret = pd.Series(returns).dropna()
    if ret.empty:
        return {
            "annual_return": np.nan,
            "annual_volatility": np.nan,
            "sharpe": np.nan,
            "max_drawdown": np.nan,
            "win_rate": np.nan,
            "n_periods": 0,
        }

    total_return = (1 + ret).prod() - 1
    annual_return = (1 + total_return) ** (periods_per_year / len(ret)) - 1
    annual_volatility = ret.std(ddof=1) * np.sqrt(periods_per_year)
    sharpe = annual_return / annual_volatility if annual_volatility and not np.isnan(annual_volatility) else np.nan
    drawdown = calculate_drawdown_series(ret)

    return {
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe": sharpe,
        "max_drawdown": drawdown.min() if not drawdown.empty else np.nan,
        "win_rate": (ret > 0).mean(),
        "n_periods": len(ret),
    }
