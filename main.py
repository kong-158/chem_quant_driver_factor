from pathlib import Path

from src.backtester import calculate_top_bottom_performance, run_monthly_group_backtest
from src.data_loader import load_all_data
from src.factor_builder import build_factors
from src.metrics import calculate_rank_ic_batch, summarize_ic
from src.return_builder import compute_forward_returns, merge_factors_and_returns
from src.utils import ensure_directories, save_table
from src.visualization import (
    plot_drawdown,
    plot_group_cum_returns,
    plot_ic_series,
    plot_top_bottom_cum_returns,
)


def main() -> None:
    """一键运行 driver 因子 MVP 研究流程。"""
    project_root = Path(__file__).resolve().parent
    ensure_directories(project_root)

    stock_prices, driver_prices, mapping, universe = load_all_data(project_root)
    print(f"Loaded stock prices: {len(stock_prices):,} rows, universe: {len(universe)} stocks")
    print(f"Loaded driver prices: {len(driver_prices):,} rows, drivers: {driver_prices['driver_name'].nunique()}")
    mapping_source = ",".join(sorted(mapping["weight_source"].dropna().unique())) if "weight_source" in mapping else "manual"
    print(f"Loaded driver mapping: {len(mapping):,} rows, source: {mapping_source}")
    save_table(mapping, project_root / "data" / "processed" / "driver_mapping_effective.csv")

    factors = build_factors(stock_prices, driver_prices, mapping, windows=(20, 60))
    forward_returns = compute_forward_returns(stock_prices, horizons=(20, 60))
    factor_dataset = merge_factors_and_returns(factors, forward_returns)

    save_table(factor_dataset, project_root / "data" / "processed" / "factor_dataset.csv")

    factor_cols = [
        "driver_mom_20d",
        "driver_mom_60d",
        "stock_mom_20d",
        "stock_mom_60d",
        "driver_stock_gap_20d",
        "driver_stock_gap_60d",
    ]
    return_cols = [
        "future_ret_20d",
        "future_ret_60d",
        "future_excess_ret_20d",
        "future_excess_ret_60d",
    ]

    ic_series = calculate_rank_ic_batch(factor_dataset, factor_cols, return_cols, min_count=5)
    ic_summary = summarize_ic(ic_series)

    save_table(ic_series, project_root / "outputs" / "tables" / "factor_ic_series.csv")
    save_table(ic_summary, project_root / "outputs" / "tables" / "factor_ic_summary.csv")

    backtest_factor = "driver_stock_gap_20d"
    monthly_group_returns = run_monthly_group_backtest(
        factor_dataset,
        stock_prices,
        factor_col=backtest_factor,
        n_groups=5,
    )
    top_bottom_performance = calculate_top_bottom_performance(monthly_group_returns, periods_per_year=12)
    top_bottom_performance.insert(0, "factor", backtest_factor)

    save_table(monthly_group_returns, project_root / "outputs" / "tables" / "monthly_group_returns.csv")
    save_table(top_bottom_performance, project_root / "outputs" / "tables" / "top_bottom_performance.csv")

    plot_ic_series(ic_series, project_root / "outputs" / "figures" / "ic_series.png")
    plot_group_cum_returns(monthly_group_returns, project_root / "outputs" / "figures" / "group_cum_returns.png")
    plot_top_bottom_cum_returns(
        monthly_group_returns,
        project_root / "outputs" / "figures" / "top_bottom_cum_returns.png",
    )
    plot_drawdown(monthly_group_returns, project_root / "outputs" / "figures" / "drawdown.png")

    print("Done.")
    print("Tables saved to:", project_root / "outputs" / "tables")
    print("Figures saved to:", project_root / "outputs" / "figures")


if __name__ == "__main__":
    main()
