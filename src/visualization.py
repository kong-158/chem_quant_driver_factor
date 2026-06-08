from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from src.metrics import calculate_drawdown_series


def _prepare_output_path(path: Path) -> None:
    """确保图片输出目录存在。"""
    path.parent.mkdir(parents=True, exist_ok=True)


def plot_ic_series(
    ic_series: pd.DataFrame,
    output_path: Path,
    return_col: str = "future_excess_ret_20d",
) -> None:
    """绘制 IC 时间序列。"""
    _prepare_output_path(output_path)
    subset = ic_series[ic_series["return_col"] == return_col].copy()
    if subset.empty:
        return

    pivot = subset.pivot_table(index="date", columns="factor", values="rank_ic", aggfunc="mean").sort_index()

    fig, ax = plt.subplots(figsize=(12, 6))
    pivot.plot(ax=ax, linewidth=1.2)
    ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
    ax.set_title(f"Rank IC Series ({return_col})")
    ax.set_xlabel("Date")
    ax.set_ylabel("Rank IC")
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_group_cum_returns(group_returns: pd.DataFrame, output_path: Path) -> None:
    """绘制各分组累计收益。"""
    _prepare_output_path(output_path)
    if group_returns.empty:
        return

    group_cols = [col for col in group_returns.columns if col.startswith("G")]
    cumulative = (1 + group_returns.set_index("date")[group_cols].fillna(0)).cumprod()

    fig, ax = plt.subplots(figsize=(10, 6))
    cumulative.plot(ax=ax, linewidth=1.8)
    ax.set_title("Monthly Group Cumulative Returns")
    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative NAV")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_top_bottom_cum_returns(group_returns: pd.DataFrame, output_path: Path) -> None:
    """绘制 Top-Bottom 组合累计收益。"""
    _prepare_output_path(output_path)
    if group_returns.empty or "top_bottom" not in group_returns.columns:
        return

    cumulative = (1 + group_returns.set_index("date")["top_bottom"].fillna(0)).cumprod()

    fig, ax = plt.subplots(figsize=(10, 5))
    cumulative.plot(ax=ax, color="#1f77b4", linewidth=2.0)
    ax.axhline(1, color="black", linewidth=0.8, linestyle="--")
    ax.set_title("Top-Bottom Cumulative Returns")
    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative NAV")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_drawdown(group_returns: pd.DataFrame, output_path: Path) -> None:
    """绘制 Top-Bottom 组合回撤。"""
    _prepare_output_path(output_path)
    if group_returns.empty or "top_bottom" not in group_returns.columns:
        return

    drawdown = calculate_drawdown_series(group_returns.set_index("date")["top_bottom"])

    fig, ax = plt.subplots(figsize=(10, 5))
    drawdown.plot(ax=ax, color="#d62728", linewidth=1.8)
    ax.fill_between(drawdown.index, drawdown.values, 0, color="#d62728", alpha=0.2)
    ax.set_title("Top-Bottom Drawdown")
    ax.set_xlabel("Date")
    ax.set_ylabel("Drawdown")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
