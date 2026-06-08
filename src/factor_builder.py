import pandas as pd


def compute_driver_momentum(driver_prices: pd.DataFrame, windows: tuple[int, ...] = (20, 60)) -> pd.DataFrame:
    """计算 driver 价格过去 N 个交易日涨幅。"""
    df = driver_prices.copy()
    df = df.sort_values(["driver_name", "date"]).reset_index(drop=True)

    for window in windows:
        # pct_change(window) 只使用 t 日及之前的价格，不引入未来数据。
        df[f"driver_mom_{window}d"] = df.groupby("driver_name")["price"].pct_change(window)

    return df.sort_values(["date", "driver_name"]).reset_index(drop=True)


def build_company_driver_momentum(
    driver_prices: pd.DataFrame,
    mapping: pd.DataFrame,
    windows: tuple[int, ...] = (20, 60),
) -> pd.DataFrame:
    """按 driver_weight 将多个 driver 合成为公司层面的 driver momentum。"""
    driver_momentum = compute_driver_momentum(driver_prices, windows=windows)
    mom_cols = [f"driver_mom_{window}d" for window in windows]

    mapping = mapping.copy()
    if "effective_date" in mapping.columns:
        mapping["effective_date"] = pd.to_datetime(mapping["effective_date"])
    if "end_date" in mapping.columns:
        mapping["end_date"] = pd.to_datetime(mapping["end_date"])

    merged = driver_momentum.merge(mapping, on="driver_name", how="inner")
    if "effective_date" in merged.columns:
        # 产能权重只能在年报披露日之后使用，避免 look-ahead bias。
        valid_start = merged["date"] >= merged["effective_date"]
        if "end_date" in merged.columns:
            valid_end = merged["end_date"].isna() | (merged["date"] < merged["end_date"])
        else:
            valid_end = True
        merged = merged[valid_start & valid_end].copy()

    weighted_cols = []

    for col in mom_cols:
        weighted_col = f"weighted_{col}"
        merged[weighted_col] = merged[col] * merged["driver_weight"]
        weighted_cols.append(weighted_col)

    company_driver = (
        merged.groupby(["date", "ticker"], as_index=False)[weighted_cols]
        .sum(min_count=1)
        .rename(columns={f"weighted_driver_mom_{window}d": f"driver_mom_{window}d" for window in windows})
    )

    stock_meta = mapping[["ticker", "company_name", "sub_industry"]].drop_duplicates("ticker")
    company_driver = company_driver.merge(stock_meta, on="ticker", how="left")
    return company_driver.sort_values(["date", "ticker"]).reset_index(drop=True)


def compute_stock_momentum(stock_prices: pd.DataFrame, windows: tuple[int, ...] = (20, 60)) -> pd.DataFrame:
    """计算股票价格过去 N 个交易日涨幅。"""
    df = stock_prices[["date", "ticker", "adj_close"]].copy()
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

    for window in windows:
        # 使用复权价计算历史收益，作为股票自身动量。
        df[f"stock_mom_{window}d"] = df.groupby("ticker")["adj_close"].pct_change(window)

    cols = ["date", "ticker"] + [f"stock_mom_{window}d" for window in windows]
    return df[cols].sort_values(["date", "ticker"]).reset_index(drop=True)


def build_factors(
    stock_prices: pd.DataFrame,
    driver_prices: pd.DataFrame,
    mapping: pd.DataFrame,
    windows: tuple[int, ...] = (20, 60),
) -> pd.DataFrame:
    """构建公司层面的 driver momentum、stock momentum 和 driver-stock gap 因子。"""
    company_driver = build_company_driver_momentum(driver_prices, mapping, windows=windows)
    stock_momentum = compute_stock_momentum(stock_prices, windows=windows)

    factors = stock_momentum.merge(company_driver, on=["date", "ticker"], how="left")

    for window in windows:
        factors[f"driver_stock_gap_{window}d"] = (
            factors[f"driver_mom_{window}d"] - factors[f"stock_mom_{window}d"]
        )

    ordered_cols = ["date", "ticker", "company_name", "sub_industry"]
    for window in windows:
        ordered_cols.extend(
            [
                f"driver_mom_{window}d",
                f"stock_mom_{window}d",
                f"driver_stock_gap_{window}d",
            ]
        )

    return factors[ordered_cols].sort_values(["date", "ticker"]).reset_index(drop=True)
