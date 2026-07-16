"""Render research-style (matplotlib/cartopy) PNGs from an assembled site table.

Bridges the explorer's per-site DataFrame + metric schema to the vendored
research renderers, choosing sensible colormap / log / 1:1 defaults per metric
so the output matches the nitro-research figures.
"""

from __future__ import annotations

import pandas as pd

from .research.conus_bubble_plot import conus_bubble_png
from .research.huc2_scatter import huc2_scatter_png


def _label(schema: dict, col: str) -> str:
    return schema["labels"].get(col, col)


def effective_log(col: str, requested: bool) -> bool:
    """Only log-scale medians. MI / normalized MI include 0 (independence),
    which a log axis would silently drop — so log is ignored for those."""
    return bool(requested) and col.startswith("median_")


def _auto_log(table: pd.DataFrame, col: str) -> bool:
    """Log color scale for wide-range positive medians (e.g. streamflow)."""
    v = pd.to_numeric(table[col], errors="coerce").dropna()
    v = v[v > 0]
    return bool(len(v) and float(v.max()) / max(float(v.min()), 1e-12) > 50)


def render_map(table: pd.DataFrame, metric_col: str, schema: dict) -> bytes:
    label = _label(schema, metric_col)
    is_mi = metric_col.startswith(("mi_", "nmi_"))
    cmap = "viridis" if is_mi else "plasma"
    log_color = (metric_col in schema.get("medians", [])) and _auto_log(table, metric_col)
    return conus_bubble_png(
        table, metric_col, cmap=cmap, log_color=log_color,
        title=label, cbar_label=label,
    )


def render_scatter(
    table: pd.DataFrame, x_col: str, y_col: str, schema: dict,
    *, logx: bool = False, logy: bool = False,
) -> bytes:
    xl, yl = _label(schema, x_col), _label(schema, y_col)
    logx, logy = effective_log(x_col, logx), effective_log(y_col, logy)
    both_nmi = x_col.startswith("nmi_") and y_col.startswith("nmi_")
    both_mi = x_col.startswith("mi_") and y_col.startswith("mi_")
    return huc2_scatter_png(
        table, x_col, y_col,
        xlabel=("log " if logx else "") + xl, ylabel=("log " if logy else "") + yl,
        title=f"{yl} vs {xl} by HUC-2",
        xlog=logx, ylog=logy,
        diagonal=(both_nmi or both_mi), equal_axes=both_nmi,
    )
