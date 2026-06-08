import pandas as pd

from src.metrics import performance_stats
from src.utils import assign_quantile_groups, get_month_end_dates


def run_monthly_group_backtest(
    factor_data: pd.DataFrame,
    stock_prices: pd.DataFrame,
    factor_col: str,
    n_groups: int = 5,
) -> pd.DataFrame:
    """月末按因子分组，持有到下一次月末，计算等权组合收益。"""
    factor_cross_sections = factor_data[["date", "ticker", factor_col]].dropna(subset=[factor_col]).copy()
    factor_cross_sections["date"] = pd.to_datetime(factor_cross_sections["date"])

    rebalance_dates = get_month_end_dates(factor_cross_sections["date"])
    price_pivot = stock_prices.pivot_table(
        index="date",
        columns="ticker",
        values="adj_close",
        aggfunc="last",
    ).sort_index()

    rows = []
    for rebalance_date, next_rebalance_date in zip(rebalance_dates[:-1], rebalance_dates[1:]):
        if rebalance_date not in price_pivot.index or next_rebalance_date not in price_pivot.index:
            continue

        cross_section = factor_cross_sections[factor_cross_sections["date"] == rebalance_date].copy()
        if cross_section.empty:
            continue

        start_price = price_pivot.loc[rebalance_date]
        end_price = price_pivot.loc[next_rebalance_date]
        period_returns = end_price / start_price - 1

        cross_section["period_ret"] = cross_section["ticker"].map(period_returns)
        cross_section = cross_section.dropna(subset=["period_ret"])
        cross_section["group"] = assign_quantile_groups(cross_section[factor_col], n_groups=n_groups).values
        cross_section = cross_section.dropna(subset=["group"])

        if cross_section.empty:
            continue

        row = {
            "date": next_rebalance_date,
            "rebalance_date": rebalance_date,
            "factor": factor_col,
            "n_groups": n_groups,
        }

        # G1 是低因子组，最高组是多头组合。
        for group_id in range(1, n_groups + 1):
            row[f"G{group_id}"] = cross_section.loc[cross_section["group"] == group_id, "period_ret"].mean()

        row["top_bottom"] = row[f"G{n_groups}"] - row["G1"]
        rows.append(row)

    group_returns = pd.DataFrame(rows)
    if group_returns.empty:
        return group_returns

    return group_returns.sort_values("date").reset_index(drop=True)


def calculate_top_bottom_performance(group_returns: pd.DataFrame, periods_per_year: int = 12) -> pd.DataFrame:
    """计算 Top-Bottom 组合的基础绩效指标。"""
    if group_returns.empty or "top_bottom" not in group_returns.columns:
        return pd.DataFrame(
            [
                {
                    "annual_return": None,
                    "annual_volatility": None,
                    "sharpe": None,
                    "max_drawdown": None,
                    "win_rate": None,
                    "n_periods": 0,
                }
            ]
        )

    stats = performance_stats(group_returns["top_bottom"], periods_per_year=periods_per_year)
    return pd.DataFrame([stats])


def run_selected_pool_backtest(
    selected_pool: pd.DataFrame,
    stock_prices: pd.DataFrame,
    portfolio_name: str = "A_pool",
) -> pd.DataFrame:
    """将动态选中的股票池等权持有到下一次调仓日。"""
    if selected_pool.empty:
        return pd.DataFrame(columns=["date", "rebalance_date", "portfolio", "period_ret", "n_holdings", "tickers"])

    selection = selected_pool[["rebalance_date", "ticker"]].dropna().copy()
    selection["rebalance_date"] = pd.to_datetime(selection["rebalance_date"])

    rebalance_dates = sorted(selection["rebalance_date"].drop_duplicates())
    price_pivot = stock_prices.pivot_table(
        index="date",
        columns="ticker",
        values="adj_close",
        aggfunc="last",
    ).sort_index()

    rows = []
    for rebalance_date, next_rebalance_date in zip(rebalance_dates[:-1], rebalance_dates[1:]):
        if rebalance_date not in price_pivot.index or next_rebalance_date not in price_pivot.index:
            continue

        tickers = selection.loc[selection["rebalance_date"] == rebalance_date, "ticker"].drop_duplicates().tolist()
        if not tickers:
            continue

        start_price = price_pivot.loc[rebalance_date, tickers]
        end_price = price_pivot.loc[next_rebalance_date, tickers]
        period_returns = (end_price / start_price - 1).dropna()
        if period_returns.empty:
            continue

        rows.append(
            {
                "date": next_rebalance_date,
                "rebalance_date": rebalance_date,
                "portfolio": portfolio_name,
                "period_ret": period_returns.mean(),
                "n_holdings": len(period_returns),
                "tickers": ";".join(period_returns.index.tolist()),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["date", "rebalance_date", "portfolio", "period_ret", "n_holdings", "tickers"])
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
