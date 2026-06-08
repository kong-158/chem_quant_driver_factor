import pandas as pd


def compute_forward_returns(stock_prices: pd.DataFrame, horizons: tuple[int, ...] = (20, 60)) -> pd.DataFrame:
    """计算未来 N 个交易日收益和相对股票池等权基准的超额收益。"""
    df = stock_prices[["date", "ticker", "adj_close"]].copy()
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

    for horizon in horizons:
        future_price = df.groupby("ticker")["adj_close"].shift(-horizon)
        df[f"future_ret_{horizon}d"] = future_price / df["adj_close"] - 1

    result_cols = ["date", "ticker"] + [f"future_ret_{horizon}d" for horizon in horizons]
    result = df[result_cols].copy()

    for horizon in horizons:
        ret_col = f"future_ret_{horizon}d"
        excess_col = f"future_excess_ret_{horizon}d"
        # 每个截面日期上，用股票池等权未来收益作为简单基准。
        benchmark_ret = result.groupby("date")[ret_col].transform("mean")
        result[excess_col] = result[ret_col] - benchmark_ret

    return result.sort_values(["date", "ticker"]).reset_index(drop=True)


def merge_factors_and_returns(factors: pd.DataFrame, forward_returns: pd.DataFrame) -> pd.DataFrame:
    """将 t 日因子与 t 日对应的未来收益标签合并。"""
    dataset = factors.merge(forward_returns, on=["date", "ticker"], how="left")
    return dataset.sort_values(["date", "ticker"]).reset_index(drop=True)
