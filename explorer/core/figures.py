"""Plotly figures: a CONUS bubble map and an X/Y scatter.

Both figures are built through one shared layout pass (``_apply_common_layout``)
so they read as a single visual system: same fonts, same margins, same legend
and colorbar placement, same marker treatment. The browser only adjusts colors
for the active theme; nothing about the geometry changes between light and dark.

Labels travel with the call. An earlier version stashed them in module globals,
which meant two concurrent requests for different datasets could swap each
other's axis titles; ``FigureSchema`` makes that impossible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .palettes import DEFAULT_PALETTE, plotly_scale
from .regions import REGION_COLORS, REGION_ORDER

# Missing values render as this everywhere: hover text, table cells, CSV notes.
MISSING = "n/a"

# Every figure is laid out at this aspect so the map and the scatter occupy
# identical space in the results column. The browser sets the pixel height; the
# server only fixes the proportions that Plotly bakes into the JSON.
FIGURE_HEIGHT = 520

# Continuous color scales are clipped to this percentile window so a handful of
# extreme sites cannot wash out the gradient for everyone else.
COLOR_PCT_LO, COLOR_PCT_HI = 5, 95

# How a continuous metric is mapped onto the color scale.
SCALE_AUTO = "auto"
SCALE_LINEAR = "linear"
SCALE_LOG = "log"
SCALE_CHOICES = (SCALE_AUTO, SCALE_LINEAR, SCALE_LOG)

# Auto switches to log once a metric spans more than this many multiples.
# Streamflow across CONUS covers four orders of magnitude, where a linear ramp
# paints all but the largest handful of rivers the same color.
AUTO_LOG_SPAN = 50.0

HOVER_TEMPLATE = "%{customdata[0]}<extra></extra>"


@dataclass(frozen=True)
class FigureSchema:
    """Per-dataset labelling passed explicitly into every figure call."""

    labels: dict[str, str] = field(default_factory=dict)
    hover_cols: tuple[str, ...] = ()

    def label(self, col: str) -> str:
        return self.labels.get(col, col)


EMPTY_SCHEMA = FigureSchema()


def schema_from_metrics(labels: dict[str, str], hover_cols) -> FigureSchema:
    return FigureSchema(labels=dict(labels), hover_cols=tuple(hover_cols))


def only_log_makes_sense(col: str) -> bool:
    """True when a log axis is meaningful for this column.

    Medians are strictly positive quantities and often span orders of
    magnitude, so a log axis helps. Mutual information and normalized MI both
    include exactly 0 (independence), which a log axis would silently drop, so
    log is refused for those regardless of what the form asked for.
    """
    return str(col).startswith("median_")


def effective_log(col: str, requested: bool) -> bool:
    return bool(requested) and only_log_makes_sense(col)


# --------------------------------------------------------------------------
# shared layout
# --------------------------------------------------------------------------

def _apply_common_layout(fig: go.Figure, *, title: str = "", legend_at: str = "top") -> go.Figure:
    """The single place figure chrome is decided.

    Two rules keep the map and the scatter looking like one system:

    * A title is drawn only when the figure has no axis labels to carry its
      meaning. The scatter's axes already name both metrics, so a title there
      would just repeat them; the map has no axes, so it needs one.
    * The legend never shares a band with the title. A figure with a title
      docks its legend under the plot, a figure without one docks it above.
      Letting both sit at the top is what made them overlap.

    Colors are left to the client so one payload renders correctly in both
    themes; everything geometric is pinned here and is therefore identical
    between the browser and the exported PNG.
    """
    top = 52 if title else 40
    bottom = 84 if legend_at == "bottom" else 56

    if legend_at == "bottom":
        legend = {
            "orientation": "h",
            "yanchor": "top",
            "y": -0.04,
            "xanchor": "center",
            "x": 0.5,
        }
    else:
        legend = {
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.01,
            "xanchor": "left",
            "x": 0,
        }
    legend["title"] = {"text": ""}

    fig.update_layout(
        height=FIGURE_HEIGHT,
        autosize=True,
        title={
            "text": title,
            "x": 0,
            "xanchor": "left",
            "yref": "container",
            "y": 0.97,
            "yanchor": "top",
            "font": {"size": 15},
            "pad": {"l": 4},
        },
        font={"family": "Inter, system-ui, sans-serif", "size": 13},
        margin={"l": 68, "r": 24, "t": top, "b": bottom},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel={"font": {"family": "Inter, system-ui, sans-serif", "size": 12}},
        legend=legend,
        coloraxis_colorbar={
            "thickness": 12,
            "len": 0.8,
            "y": 0.5,
            "yanchor": "middle",
            "outlinewidth": 0,
            "title": {"side": "right"},
        },
        # Carried through to the client (for the card caption) and to the PNG
        # exporter, which re-adds a title so a downloaded figure stands alone.
        meta={"caption": title},
    )
    return fig


def _empty(message: str) -> go.Figure:
    """A placeholder that still occupies the figure's normal footprint.

    Keeping the box the same size matters: if an empty result collapsed, the
    page would jump every time a filter excluded everything.
    """
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        showarrow=False,
        font={"size": 14},
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
    )
    fig.update_layout(xaxis={"visible": False}, yaxis={"visible": False})
    _apply_common_layout(fig)
    fig.update_layout(margin={"l": 24, "r": 24, "t": 24, "b": 24}, meta={"caption": ""})
    return fig


def _fmt(v) -> str:
    """Human-readable value for hover text."""
    if v is None:
        return MISSING
    if isinstance(v, (float, np.floating)):
        if not np.isfinite(v):
            return MISSING
        return f"{v:,.4g}"
    if isinstance(v, (int, np.integer)):
        return f"{v:,}"
    s = str(v)
    return s if s not in ("", "nan", "<NA>", "None") else MISSING


def _hover_strings(df: pd.DataFrame, schema: FigureSchema) -> pd.Series:
    """Pre-render hover HTML per site.

    Values are formatted server-side so the browser never sees a raw
    ``%{customdata[i]}`` template, which Plotly leaves unsubstituted whenever
    the underlying value is missing.
    """
    lines = []
    for _, r in df.iterrows():
        head = f"<b>{_fmt(r.get('station_nm'))}</b>"
        sub = f"site {_fmt(r.get('site_no'))} &middot; {_fmt(r.get('location_type'))}"
        if _fmt(r.get("huc2")) != MISSING:
            sub += f" &middot; HUC2 {r.get('huc2')}"
        parts = [head, sub]
        for c in schema.hover_cols:
            if c in df.columns:
                parts.append(f"{schema.label(c)}: {_fmt(r.get(c))}")
        lines.append("<br>".join(parts))
    return pd.Series(lines, index=df.index)


def _robust_range(values, lo: int = COLOR_PCT_LO, hi: int = COLOR_PCT_HI):
    """[p_lo, p_hi] for a continuous color scale, falling back to min/max."""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return None
    a = float(np.nanpercentile(v, lo))
    b = float(np.nanpercentile(v, hi))
    if not (np.isfinite(a) and np.isfinite(b)) or b <= a:
        a, b = float(v.min()), float(v.max())
        if b <= a:
            b = a + 1e-9
    return [a, b]


def log_color_wanted(values, col: str, mode: str = SCALE_AUTO) -> bool:
    """Should this metric's color scale be logarithmic?

    Log is only ever offered for medians. Mutual information and normalized MI
    both include exactly 0 (independence), and log would silently drop those
    sites from the map rather than showing the most interesting thing about
    them. ``only_log_makes_sense`` is the same rule the scatter axes use.

    Under ``auto`` the decision follows the data: log once the positive values
    span more than ``AUTO_LOG_SPAN``, which reproduces the behavior of the
    original study's bubble maps.
    """
    mode = (mode or SCALE_AUTO).strip().lower()
    if mode == SCALE_LINEAR or not only_log_makes_sense(col):
        return False

    v = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    v = v[v > 0]
    if v.empty:
        return False
    if mode == SCALE_LOG:
        return True
    return float(v.max()) / max(float(v.min()), 1e-12) > AUTO_LOG_SPAN


# Sub-decade tick positions, the 1-2-5 grid a log axis conventionally uses.
# Only needed when the data spans too few decades to label decades alone.
_LOG_MANTISSAS = (1, 2, 5)


def _sci_label(value: float) -> str:
    """Render a real value in powers-of-ten form, as a LogNorm colorbar does.

    A mantissa of 1 prints bare (10^3), anything else prints as m x 10^n
    (2 x 10^0). Keeping every log tick in this form means the colorbar reads
    the same whether the data happens to span four decades or one and a half;
    plain decimals mixed in would look like a different kind of axis.
    """
    if not np.isfinite(value) or value <= 0:
        return ""
    exponent = int(np.floor(np.log10(value)))
    mantissa = value / (10.0**exponent)
    # Float error can leave 1000 as 9.999...e2; promote it rather than print that.
    if mantissa >= 9.9995:
        mantissa, exponent = 1.0, exponent + 1
    # Decide on the *rendered* mantissa, not the raw one. Rounding to two
    # significant digits can turn 1.02 into "1" and 9.99 into "10", and both
    # of those belong in bare power-of-ten form rather than as "1x10^n" or
    # the plainly wrong "10x10^n".
    text = f"{mantissa:.2g}"
    if text == "10":
        text, exponent = "1", exponent + 1
    if text == "1":
        return f"10<sup>{exponent}</sup>"
    return f"{text}\u00d710<sup>{exponent}</sup>"


def _log_ticks(lo: float, hi: float) -> tuple[list[float], list[str]]:
    """Colorbar ticks for a log10 color axis, given log10 bounds.

    Whole decades when at least three fall inside the range, which is the
    familiar 10^1, 10^2, 10^3 colorbar. A narrower range may contain one decade
    boundary or none, so it subdivides on the 1-2-5 grid instead. Either way
    the labels stay in powers-of-ten form.
    """
    # A single site, or a set sharing one value, collapses the range; five
    # ticks all reading the same number is worse than one honest tick.
    if not np.isfinite(lo) or not np.isfinite(hi) or (hi - lo) < 0.05:
        mid = (lo + hi) / 2.0
        return [float(mid)], [_sci_label(10.0**mid)]

    first, last = int(np.floor(lo)), int(np.ceil(hi))

    decades = [d for d in range(first, last + 1) if lo - 1e-9 <= d <= hi + 1e-9]
    if len(decades) >= 3:
        return [float(d) for d in decades], [_sci_label(10.0**d) for d in decades]

    positions = [
        float(np.log10(m * 10.0**e))
        for e in range(first, last + 1)
        for m in _LOG_MANTISSAS
        if lo - 1e-9 <= np.log10(m * 10.0**e) <= hi + 1e-9
    ]
    if len(positions) >= 2:
        return positions, [_sci_label(10.0**p) for p in positions]

    # Narrower than one step of the 1-2-5 grid: label the two ends.
    return [float(lo), float(hi)], [_sci_label(10.0**lo), _sci_label(10.0**hi)]


LOG_COLOR_COL = "_log_color"


def _prepare_continuous(
    plot: pd.DataFrame, color_col: str, palette: str, scale: str
) -> tuple[pd.DataFrame, dict, dict, int, bool]:
    """Work out the color argument, px kwargs and colorbar for one metric.

    Plotly has no logarithmic color axis, so a log scale is done by coloring on
    log10(value) and relabelling the colorbar with the original values. Both
    figures go through here so the map and the scatter cannot end up scaling
    the same metric two different ways.

    Returns (frame, px kwargs, colorbar update, sites dropped, is_log).
    """
    use_log = log_color_wanted(plot[color_col], color_col, scale)

    if not use_log:
        return (
            plot,
            {
                "color": color_col,
                "color_continuous_scale": plotly_scale(palette, color_col),
                "range_color": _robust_range(plot[color_col]),
            },
            {},
            0,
            False,
        )

    values = pd.to_numeric(plot[color_col], errors="coerce")
    positive = values > 0
    dropped = int((~positive).sum())
    plot = plot[positive].copy()
    plot[LOG_COLOR_COL] = np.log10(pd.to_numeric(plot[color_col], errors="coerce"))

    rng = _robust_range(plot[LOG_COLOR_COL]) or [0.0, 1.0]
    tickvals, ticktext = _log_ticks(rng[0], rng[1])
    return (
        plot,
        {
            "color": LOG_COLOR_COL,
            "color_continuous_scale": plotly_scale(palette, color_col),
            "range_color": rng,
        },
        {"tickvals": tickvals, "ticktext": ticktext},
        dropped,
        True,
    )


def _dropped_note(dropped: int) -> str:
    """Say so when a log scale had to leave sites out, rather than hiding it."""
    if dropped <= 0:
        return ""
    site = "site" if dropped == 1 else "sites"
    return f", {dropped} {site} omitted (value not above zero)"


# --------------------------------------------------------------------------
# figures
# --------------------------------------------------------------------------

def map_figure(
    df: pd.DataFrame,
    color_col: str = "location_type",
    *,
    schema: FigureSchema = EMPTY_SCHEMA,
    palette: str = DEFAULT_PALETTE,
    color_scale: str = SCALE_AUTO,
) -> go.Figure:
    """CONUS bubble map, colored by region (discrete) or any metric (continuous).

    ``palette`` selects the continuous scale and is ignored when coloring by
    region, which always uses the fixed region colors so the same region reads
    the same on every figure.

    ``color_scale`` is auto, linear or log. See ``log_color_wanted``.
    """
    if df is None or df.empty:
        return _empty("No sites match the current filters.")

    plot = df.dropna(subset=["dec_lat_va", "dec_long_va"]).copy()
    if plot.empty:
        return _empty("No sites have coordinates to map.")

    by_region = color_col == "location_type" or color_col not in plot.columns
    if not by_region:
        plot = plot.dropna(subset=[color_col]).copy()
        if plot.empty:
            return _empty(f"No sites have a value for {schema.label(color_col)}.")

    plot["hover_html"] = _hover_strings(plot, schema)
    common = {
        "lat": "dec_lat_va",
        "lon": "dec_long_va",
        "scope": "usa",
        "custom_data": ["hover_html"],
    }

    if by_region:
        fig = px.scatter_geo(
            plot,
            color="location_type",
            category_orders={"location_type": list(REGION_ORDER)},
            color_discrete_map=REGION_COLORS,
            **common,
        )
        title = "Sites by region"
    else:
        plot, color_kw, bar_kw, dropped, is_log = _prepare_continuous(
            plot, color_col, palette, color_scale
        )
        if plot.empty:
            return _empty(
                f"No sites have a positive value for {schema.label(color_col)}, "
                "which a log color scale requires."
            )
        fig = px.scatter_geo(plot, **color_kw, **common)
        fig.update_coloraxes(colorbar_title_text=schema.label(color_col))
        if bar_kw:
            # Merged in its own call: tickvals live on coloraxis.colorbar, and
            # _apply_common_layout adds the bar's geometry afterwards.
            fig.update_coloraxes(colorbar=bar_kw)
        title = (
            f"Sites by {schema.label(color_col)}"
            + (", log color scale" if is_log else "")
            + _dropped_note(dropped)
        )

    fig.update_traces(
        marker={"size": 8, "line": {"width": 0.6, "color": "rgba(0,0,0,0.55)"}},
        hovertemplate=HOVER_TEMPLATE,
    )
    fig.update_geos(
        showland=True,
        showlakes=True,
        showsubunits=True,
        showcountries=False,
        showcoastlines=False,
        showframe=False,
        fitbounds=False,
    )
    # The map carries a title (it has no axes to explain it), so its legend
    # docks underneath rather than fighting the title for the top band.
    _apply_common_layout(fig, title=title, legend_at="bottom" if by_region else "top")
    # A geo figure needs no cartesian gutters; give the basemap the full card.
    fig.update_layout(
        margin={"l": 8, "r": 8, "t": 52, "b": 56 if by_region else 12}
    )
    fig.update_geos(domain={"x": [0, 1], "y": [0, 1]})
    return fig


def scatter_figure(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    *,
    schema: FigureSchema = EMPTY_SCHEMA,
    log_x: bool = False,
    log_y: bool = False,
    color_col: str = "location_type",
    palette: str = DEFAULT_PALETTE,
    color_scale: str = SCALE_AUTO,
) -> go.Figure:
    """X/Y scatter, colored by region or by any metric, with optional log axes.

    ``color_scale`` follows the same auto/linear/log rule as the map, so a
    metric shown on both figures is scaled identically on both.
    """
    if df is None or df.empty:
        return _empty("No sites match the current filters.")
    for c in (x_col, y_col):
        if not c or c not in df.columns:
            return _empty("Pick an X and a Y metric to draw the scatter.")

    plot = df.dropna(subset=[x_col, y_col])
    if log_x:
        plot = plot[plot[x_col] > 0]
    if log_y:
        plot = plot[plot[y_col] > 0]
    plot = plot.copy()
    if plot.empty:
        return _empty("No sites have values on both axes for this selection.")

    by_region = color_col == "location_type" or color_col not in plot.columns
    if not by_region:
        plot = plot.dropna(subset=[color_col]).copy()
        if plot.empty:
            return _empty(f"No sites have a value for {schema.label(color_col)}.")

    plot["hover_html"] = _hover_strings(plot, schema)
    common = {
        "x": x_col,
        "y": y_col,
        "custom_data": ["hover_html"],
        "log_x": log_x,
        "log_y": log_y,
    }

    color_note = ""
    if by_region:
        fig = px.scatter(
            plot,
            color="location_type" if "location_type" in plot.columns else None,
            category_orders={"location_type": list(REGION_ORDER)},
            color_discrete_map=REGION_COLORS,
            **common,
        )
    else:
        plot, color_kw, bar_kw, dropped, is_log = _prepare_continuous(
            plot, color_col, palette, color_scale
        )
        if plot.empty:
            return _empty(
                f"No sites have a positive value for {schema.label(color_col)}, "
                "which a log color scale requires."
            )
        fig = px.scatter(plot, **color_kw, **common)
        fig.update_coloraxes(colorbar_title_text=schema.label(color_col))
        if bar_kw:
            fig.update_coloraxes(colorbar=bar_kw)
        color_note = ", colored by " + schema.label(color_col)
        if is_log:
            color_note += " on a log scale"
        color_note += _dropped_note(dropped)

    fig.update_traces(
        marker={"size": 9, "line": {"width": 0.6, "color": "rgba(0,0,0,0.55)"}},
        hovertemplate=HOVER_TEMPLATE,
    )
    # No title: both axis labels are already spelled out in full, so a title
    # would only repeat them and crowd the legend.
    _apply_common_layout(fig)
    fig.update_layout(
        xaxis_title=("log " if log_x else "") + schema.label(x_col),
        yaxis_title=("log " if log_y else "") + schema.label(y_col),
        meta={
            "caption": f"{schema.label(y_col)} against {schema.label(x_col)}"
            + color_note
        },
    )
    # Plotly's default log ticks interleave labelled minor ticks, which reads as
    # a jumble ("5  0.1  2  5  1  2  5  10"). One label per decade is the whole
    # point of a log axis.
    if log_x:
        fig.update_xaxes(dtick=1, minor={"showgrid": False, "ticks": ""})
    if log_y:
        fig.update_yaxes(dtick=1, minor={"showgrid": False, "ticks": ""})
    return fig


def to_png(fig: go.Figure, *, width: int = 1200, height: int = 700, scale: int = 3) -> bytes:
    """Static PNG via kaleido, at print resolution.

    scale=3 on a 1200x700 canvas yields 3600x2100 px, roughly 300 dpi at a
    12-inch figure width: good enough to drop straight into a manuscript.

    A downloaded figure has no card header around it, so the caption the page
    was showing is drawn into the image, with the top margin opened up to make
    room for it above the legend.
    """
    export = go.Figure(fig)
    caption = ""
    meta = fig.layout.meta
    if isinstance(meta, dict):
        caption = meta.get("caption") or ""

    if caption and not (fig.layout.title and fig.layout.title.text):
        current_top = (fig.layout.margin.t or 40) if fig.layout.margin else 40
        export.update_layout(
            title={
                "text": caption,
                "x": 0,
                "xanchor": "left",
                "yref": "container",
                "y": 0.97,
                "yanchor": "top",
                "font": {"size": 16, "color": "#16202c"},
                "pad": {"l": 4},
            },
            margin={"t": current_top + 34},
        )

    export.update_layout(
        paper_bgcolor="white",
        plot_bgcolor="white",
        font={"color": "#16202c"},
        height=height,
    )
    export.update_xaxes(gridcolor="#e2e8f0", zerolinecolor="#cbd5e1", linecolor="#94a3b8")
    export.update_yaxes(gridcolor="#e2e8f0", zerolinecolor="#cbd5e1", linecolor="#94a3b8")
    export.update_geos(
        landcolor="#eef1f4",
        lakecolor="#dce7f1",
        subunitcolor="#9aa5b1",
        bgcolor="white",
    )
    return export.to_image(format="png", width=width, height=height, scale=scale)
