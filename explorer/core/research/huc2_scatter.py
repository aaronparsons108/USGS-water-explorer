"""HUC-2-colored scatter -> PNG bytes (research style).

Vendored from nitro-research (nitro/huc2_scatter.py), adapted for the web:
Agg backend, returns PNG bytes, self-contained rc (no nitro import). Square
figure by default.
"""

from __future__ import annotations

import io
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HUC2_COLORBLIND_PALETTE = [
    "#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9",
    "#F0E442", "#882255", "#44AA99", "#999933", "#AA4499", "#117733",
    "#332288", "#88CCEE", "#661100", "#DDAA33", "#6699CC", "#AA4639",
    "#228833", "#DC0073", "#004488", "#EE7733", "#997700", "#C44E52",
    "#4CAF50", "#6A3D9A", "#FF7F00", "#A65628", "#F781BF", "#66C2A5",
    "#FC8D62", "#8DA0CB", "#E78AC3",
]
HUC2_MISSING_COLOR = "#5C5C5C"

_RC = {
    "font.size": 15.0, "axes.titlesize": 17.0, "axes.labelsize": 17.0,
    "xtick.labelsize": 13.0, "ytick.labelsize": 13.0, "legend.fontsize": 13.0,
}


def huc2_plot_label(val: object) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "Missing"
    s = str(val).strip()
    if not s or s.lower() in ("nan", "<na>"):
        return "Missing"
    try:
        return f"{int(float(s)):02d}"
    except ValueError:
        return s


def huc2_color_map(labels: list[str]) -> dict[str, str]:
    ordered = sorted({lb for lb in labels if lb != "Missing"})
    out = {lb: HUC2_COLORBLIND_PALETTE[i % len(HUC2_COLORBLIND_PALETTE)] for i, lb in enumerate(ordered)}
    out["Missing"] = HUC2_MISSING_COLOR
    return out


def huc2_scatter_png(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    *,
    xlabel: str,
    ylabel: str,
    title: str,
    huc2_col: str = "huc2",
    xlog: bool = False,
    ylog: bool = False,
    diagonal: bool = False,
    equal_axes: bool = False,
    figsize: tuple[float, float] = (8.0, 8.0),
) -> bytes:
    """Render a research-style HUC-2-colored scatter to PNG bytes (square)."""
    work = df.dropna(subset=[x_col, y_col]).copy()
    if xlog:
        work = work[work[x_col] > 0]
    if ylog:
        work = work[work[y_col] > 0]

    with plt.rc_context(_RC):
        fig, ax = plt.subplots(figsize=figsize)
        if work.empty:
            ax.text(0.5, 0.5, "No sites have values for both axes.", ha="center", va="center")
            ax.axis("off")
        else:
            work["_huc2_lbl"] = (
                work[huc2_col].map(huc2_plot_label) if huc2_col in work.columns else "Missing"
            )
            cmap = huc2_color_map(work["_huc2_lbl"].tolist())
            for huc in sorted(cmap.keys(), key=lambda x: (x == "Missing", x)):
                sub = work[work["_huc2_lbl"] == huc]
                if sub.empty:
                    continue
                ax.scatter(
                    sub[x_col], sub[y_col], s=56, alpha=0.9, edgecolors="black",
                    linewidths=0.45, c=cmap[huc], label=f"HUC {huc} (n={len(sub)})", zorder=3,
                )
            if xlog:
                ax.set_xscale("log")
            if ylog:
                ax.set_yscale("log")
            if diagonal:
                lo = float(min(work[x_col].min(), work[y_col].min()))
                hi = float(max(work[x_col].max(), work[y_col].max()))
                ax.plot([lo, hi], [lo, hi], color="0.4", linestyle="--", linewidth=1.2,
                        zorder=1, label="1:1")
            if equal_axes:
                ax.set_aspect("equal", adjustable="box")
            ax.grid(True, which="both", linestyle=":", alpha=0.45)
            ax.set_xlabel(textwrap.fill(xlabel, 42))
            ax.set_ylabel(textwrap.fill(ylabel, 42))
            ax.set_title(textwrap.fill(title, 50))
            ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), framealpha=0.95, fontsize=11)
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", pad_inches=0.3)
        plt.close(fig)
        return buf.getvalue()
