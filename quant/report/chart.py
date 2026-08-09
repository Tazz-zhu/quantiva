"""????????matplotlib??????????"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# ? matplotlib ???????????????
os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "matplotlib_quant"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from quant.analytics.metrics import max_drawdown  # noqa: E402


def plot_backtest(
    data: pd.DataFrame,
    equity_curve: pd.Series,
    trades: list,
    output_path: str | Path,
) -> Path:
    """???? + ???????????????? PNG?"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(
        3,
        1,
        figsize=(12, 11),
        sharex=True,
        gridspec_kw={"height_ratios": [3, 1.2, 1]},
    )
    fig.suptitle("Backtest Report", fontsize=14, fontweight="bold")

    ax_price = axes[0]
    ax_price.plot(data.index, data["close"], lw=0.9, color="#4C72B0", label="Close")
    for t in trades:
        color = "#55A868" if t.side == "long" else "#C44E52"
        marker = "^" if t.side == "long" else "v"
        ax_price.scatter(t.entry_time, t.entry_price, marker=marker, s=45, color=color, zorder=5)
        ax_price.scatter(
            t.exit_time,
            t.exit_price,
            marker=("v" if t.side == "long" else "^"),
            s=45,
            color="#8172B3",
            zorder=5,
        )
    ax_price.set_ylabel("Price")
    ax_price.legend(loc="upper left")
    ax_price.grid(alpha=0.3)

    ax_eq = axes[1]
    ax_eq.plot(equity_curve.index, equity_curve, lw=1.2, color="#55A868")
    ax_eq.set_ylabel("Equity")
    ax_eq.grid(alpha=0.3)

    dd, _ = max_drawdown(equity_curve)
    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1.0
    ax_dd = axes[2]
    ax_dd.fill_between(drawdown.index, drawdown * 100, 0.0, color="#C44E52", alpha=0.5)
    ax_dd.set_ylabel("Drawdown %")
    ax_dd.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path
