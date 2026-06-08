from pathlib import Path

import numpy as np
import pandas as pd

from src.capacity_builder import build_capacity_weight_mapping
from src.utils import ensure_directories, save_table


STOCK_COLUMNS = ["date", "ticker", "close", "adj_close", "volume"]
DRIVER_COLUMNS = ["date", "driver_name", "price"]
MAPPING_COLUMNS = ["ticker", "company_name", "sub_industry", "driver_name", "driver_weight"]
PRODUCT_CAPACITY_COLUMNS = [
    "ticker",
    "company_name",
    "sub_industry",
    "report_year",
    "report_date",
    "product_name",
    "capacity",
    "capacity_unit",
    "source_type",
    "source_url",
    "note",
]
PRODUCT_DRIVER_COLUMNS = ["product_name", "driver_name", "driver_direction", "driver_share", "exposure_type"]


def read_universe(path: Path) -> pd.DataFrame:
    """读取股票池配置。"""
    universe = pd.read_csv(path)
    required = {"ticker", "company_name", "sub_industry"}
    missing = required - set(universe.columns)
    if missing:
        raise ValueError(f"universe.csv 缺少字段: {sorted(missing)}")
    return universe.sort_values("ticker").reset_index(drop=True)


def read_driver_mapping(path: Path) -> pd.DataFrame:
    """读取公司与 driver 的映射关系。"""
    mapping = pd.read_csv(path)
    missing = set(MAPPING_COLUMNS) - set(mapping.columns)
    if missing:
        raise ValueError(f"driver_mapping.csv 缺少字段: {sorted(missing)}")

    mapping = mapping[MAPPING_COLUMNS].copy()
    mapping["driver_weight"] = pd.to_numeric(mapping["driver_weight"], errors="coerce")
    if mapping["driver_weight"].isna().any():
        raise ValueError("driver_weight 存在无法转换为数值的记录")
    mapping["weight_source"] = "manual"
    return mapping.sort_values(["ticker", "driver_name"]).reset_index(drop=True)


def read_product_driver_map(path: Path) -> pd.DataFrame:
    """读取产品与价格 driver 的映射关系。"""
    product_map = pd.read_csv(path)
    missing = set(PRODUCT_DRIVER_COLUMNS) - set(product_map.columns)
    if missing:
        raise ValueError(f"product_driver_map.csv 缺少字段: {sorted(missing)}")

    product_map = product_map[PRODUCT_DRIVER_COLUMNS].copy()
    product_map["driver_direction"] = pd.to_numeric(product_map["driver_direction"], errors="coerce").fillna(1.0)
    product_map["driver_share"] = pd.to_numeric(product_map["driver_share"], errors="coerce").fillna(1.0)
    return product_map.sort_values(["product_name", "driver_name"]).reset_index(drop=True)


def read_product_capacity(path: Path) -> pd.DataFrame:
    """读取产品产能数据，并完成日期和数值字段转换。"""
    product_capacity = pd.read_csv(path)
    missing = set(PRODUCT_CAPACITY_COLUMNS) - set(product_capacity.columns)
    if missing:
        raise ValueError(f"{path} 缺少字段: {sorted(missing)}")

    product_capacity = product_capacity[PRODUCT_CAPACITY_COLUMNS].copy()
    product_capacity["report_date"] = pd.to_datetime(product_capacity["report_date"])
    product_capacity["report_year"] = pd.to_numeric(product_capacity["report_year"], errors="coerce").astype("Int64")
    product_capacity["capacity"] = pd.to_numeric(product_capacity["capacity"], errors="coerce")
    product_capacity = product_capacity.dropna(subset=["ticker", "report_date", "product_name", "capacity"])
    return product_capacity.sort_values(["ticker", "report_date", "product_name"]).reset_index(drop=True)


def read_stock_prices(path: Path) -> pd.DataFrame:
    """读取股票价格数据，并完成日期转换、排序与基础校验。"""
    stock_prices = pd.read_csv(path)
    missing = set(STOCK_COLUMNS) - set(stock_prices.columns)
    if missing:
        raise ValueError(f"{path} 缺少字段: {sorted(missing)}")

    stock_prices = stock_prices[STOCK_COLUMNS].copy()
    stock_prices["date"] = pd.to_datetime(stock_prices["date"])
    for col in ["close", "adj_close", "volume"]:
        stock_prices[col] = pd.to_numeric(stock_prices[col], errors="coerce")

    stock_prices = stock_prices.dropna(subset=["date", "ticker", "adj_close"])
    stock_prices = stock_prices.sort_values(["date", "ticker"]).reset_index(drop=True)
    return stock_prices


def read_driver_prices(path: Path) -> pd.DataFrame:
    """读取化工品 driver 价格数据，并完成日期转换、排序与基础校验。"""
    driver_prices = pd.read_csv(path)
    missing = set(DRIVER_COLUMNS) - set(driver_prices.columns)
    if missing:
        raise ValueError(f"{path} 缺少字段: {sorted(missing)}")

    driver_prices = driver_prices[DRIVER_COLUMNS].copy()
    driver_prices["date"] = pd.to_datetime(driver_prices["date"])
    driver_prices["price"] = pd.to_numeric(driver_prices["price"], errors="coerce")

    driver_prices = driver_prices.dropna(subset=["date", "driver_name", "price"])
    driver_prices = driver_prices.sort_values(["date", "driver_name"]).reset_index(drop=True)
    return driver_prices


def _existing_file(path: Path) -> bool:
    """判断文件是否存在且非空。"""
    return path.exists() and path.stat().st_size > 0


def generate_sample_product_capacity(project_root: Path, seed: int = 2026) -> pd.DataFrame:
    """生成示例产品产能数据，用于演示产能权重构建流程。"""
    ensure_directories(project_root)
    rng = np.random.default_rng(seed)
    mapping = read_driver_mapping(project_root / "config" / "driver_mapping.csv")

    rows = []
    base_capacity = {
        (row.ticker, row.driver_name): rng.uniform(10, 250) * max(row.driver_weight, 0.05)
        for row in mapping.itertuples(index=False)
    }

    # 2018 年报在 2019 年披露，覆盖样本起点，避免 2020 年初没有权重。
    for report_year in range(2018, 2025):
        report_date = pd.Timestamp(year=report_year + 1, month=4, day=30)
        for row in mapping.itertuples(index=False):
            annual_growth = 1 + 0.04 * (report_year - 2018) + rng.normal(0, 0.025)
            capacity = max(base_capacity[(row.ticker, row.driver_name)] * annual_growth, 1.0)
            rows.append(
                {
                    "ticker": row.ticker,
                    "company_name": row.company_name,
                    "sub_industry": row.sub_industry,
                    "report_year": report_year,
                    "report_date": report_date.date().isoformat(),
                    "product_name": row.driver_name,
                    "capacity": round(float(capacity), 2),
                    "capacity_unit": "万吨/年",
                    "source_type": "sample_generated",
                    "source_url": "",
                    "note": "示例数据，仅用于打通产能权重流程",
                }
            )

    product_capacity = pd.DataFrame(rows)
    save_table(product_capacity, project_root / "data" / "sample" / "product_capacity.csv")
    return product_capacity


def generate_sample_data(
    project_root: Path,
    start_date: str = "2020-01-01",
    end_date: str = "2025-12-31",
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """生成可复现的 sample 股票价格与 driver 价格数据。

    样本数据只用于打通研究流程。生成逻辑中让股票收益对 driver 变化存在一定滞后反应，
    方便 MVP 阶段观察 IC 和分组回测是否能正常工作。
    """
    ensure_directories(project_root)
    rng = np.random.default_rng(seed)

    universe = read_universe(project_root / "config" / "universe.csv")
    mapping = read_driver_mapping(project_root / "config" / "driver_mapping.csv")
    dates = pd.bdate_range(start=start_date, end=end_date)
    n_days = len(dates)

    driver_rows = []
    driver_returns = {}
    unique_drivers = sorted(mapping["driver_name"].unique())

    for driver_name in unique_drivers:
        base_price = rng.uniform(2000, 18000)
        phase = rng.uniform(0, 2 * np.pi)
        drift = rng.normal(0.00005, 0.00004)
        cycle = 0.0012 * np.sin(np.arange(n_days) / 60 + phase)
        shock = rng.normal(0, 0.010, n_days)
        log_ret = drift + cycle + shock
        price = base_price * np.exp(np.cumsum(log_ret))
        driver_returns[driver_name] = pd.Series(log_ret, index=dates)

        for date, value in zip(dates, price):
            driver_rows.append(
                {
                    "date": date,
                    "driver_name": driver_name,
                    "price": round(float(value), 2),
                }
            )

    driver_prices = pd.DataFrame(driver_rows)
    market_log_ret = rng.normal(0.0001, 0.008, n_days)
    stock_rows = []

    for _, stock in universe.iterrows():
        ticker = stock["ticker"]
        stock_mapping = mapping[mapping["ticker"] == ticker]
        weighted_driver_ret = pd.Series(0.0, index=dates)

        for _, row in stock_mapping.iterrows():
            weighted_driver_ret += row["driver_weight"] * driver_returns[row["driver_name"]]

        # 股票对 driver 的反应设置为滞后项，模拟“价格先动，股价后动”。
        lagged_driver_ret = weighted_driver_ret.shift(7).rolling(5, min_periods=1).mean().fillna(0.0)

        beta = rng.uniform(0.75, 1.10)
        driver_exposure = rng.uniform(0.25, 0.45)
        idiosyncratic_ret = rng.normal(0, 0.014, n_days)
        alpha = rng.normal(0.00002, 0.00004)
        stock_log_ret = alpha + beta * market_log_ret + driver_exposure * lagged_driver_ret.values + idiosyncratic_ret

        start_price = rng.uniform(8, 80)
        adj_close = start_price * np.exp(np.cumsum(stock_log_ret))
        close = adj_close * (1 + rng.normal(0, 0.001, n_days))
        volume = rng.integers(2_000_000, 80_000_000, n_days)

        for date, close_value, adj_value, vol in zip(dates, close, adj_close, volume):
            stock_rows.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "close": round(float(close_value), 2),
                    "adj_close": round(float(adj_value), 4),
                    "volume": int(vol),
                }
            )

    stock_prices = pd.DataFrame(stock_rows)

    save_table(stock_prices, project_root / "data" / "sample" / "stock_prices.csv")
    save_table(driver_prices, project_root / "data" / "sample" / "driver_prices.csv")
    generate_sample_product_capacity(project_root, seed=seed + 1)
    return stock_prices, driver_prices


def load_stock_prices(project_root: Path) -> pd.DataFrame:
    """优先读取 raw 股票数据；若不存在则读取或生成 sample 数据。"""
    raw_path = project_root / "data" / "raw" / "stock_prices.csv"
    sample_path = project_root / "data" / "sample" / "stock_prices.csv"

    if _existing_file(raw_path):
        return read_stock_prices(raw_path)

    if not _existing_file(sample_path):
        generate_sample_data(project_root)

    return read_stock_prices(sample_path)


def load_driver_prices(project_root: Path) -> pd.DataFrame:
    """优先读取 raw driver 数据；若不存在则读取或生成 sample 数据。"""
    raw_path = project_root / "data" / "raw" / "driver_prices.csv"
    sample_path = project_root / "data" / "sample" / "driver_prices.csv"

    if _existing_file(raw_path):
        return read_driver_prices(raw_path)

    if not _existing_file(sample_path):
        generate_sample_data(project_root)

    return read_driver_prices(sample_path)


def load_product_capacity(project_root: Path) -> pd.DataFrame:
    """优先读取 raw 产品产能数据；若不存在则读取或生成 sample 数据。"""
    raw_path = project_root / "data" / "raw" / "product_capacity.csv"
    sample_path = project_root / "data" / "sample" / "product_capacity.csv"

    if _existing_file(raw_path):
        return read_product_capacity(raw_path)

    if not _existing_file(sample_path):
        generate_sample_product_capacity(project_root)

    return read_product_capacity(sample_path)


def load_effective_driver_mapping(project_root: Path, fallback_mapping: pd.DataFrame) -> pd.DataFrame:
    """优先用产品产能生成 driver 权重；没有产能数据时退回手工映射。"""
    product_map_path = project_root / "config" / "product_driver_map.csv"
    if not _existing_file(product_map_path):
        return fallback_mapping

    product_capacity = load_product_capacity(project_root)
    product_driver_map = read_product_driver_map(product_map_path)
    capacity_mapping = build_capacity_weight_mapping(product_capacity, product_driver_map)

    if capacity_mapping.empty:
        return fallback_mapping

    return capacity_mapping


def load_all_data(project_root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """一次性读取研究所需的股票价格、driver 价格、映射关系和股票池。"""
    ensure_directories(project_root)
    universe = read_universe(project_root / "config" / "universe.csv")
    fallback_mapping = read_driver_mapping(project_root / "config" / "driver_mapping.csv")
    stock_prices = load_stock_prices(project_root)
    driver_prices = load_driver_prices(project_root)
    mapping = load_effective_driver_mapping(project_root, fallback_mapping)
    return stock_prices, driver_prices, mapping, universe
