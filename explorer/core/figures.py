"""Plotly figures: a CONUS bubble map and an X/Y scatter.

Both are built with plotly.express so one code path yields the interactive
in-app view (``to_html``) and the downloadable static PNG (``to_png`` via
kaleido). The US basemap comes from Plotly's ``scope="usa"`` -- no cartopy /
shapefile downloads needed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .regions import REGION_COLORS, REGION_ORDER
from .service import METRIC_LABELS

HOVER_METRICS = [
    "median_00060_Mean",
    "median_no3no2",
    "median_do_mg_l",
    "mutual_information_flow_no3",
    "mutual_information_no3_do",
]


def label(col: str) -> str:
    return METRIC_LABELS.get(col, col)


def _empty(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, font=dict(size=16))
    fig.update_layout(
        xaxis={"visible": False},
        yaxis={"visible": False},
        margin=dict(l=10, r=10, t=30, b=10),
    )
    return fig


def _hover_data(df: pd.DataFrame) -> dict:
    cols = {"site_no": True, "location_type": True}
    for c in HOVER_METRICS:
        if c in df.columns:
            cols[c] = ":.4g"
    return cols


def map_figure(df: pd.DataFrame, color_col: str = "location_type") -> go.Figure:
    """CONUS bubble map. Color by region (discrete) or any metric (continuous)."""
    if df is None or df.empty:
        return _empty("No sites match the current filters.")

    plot = df.dropna(subset=["dec_lat_va", "dec_long_va"]).copy()
    if plot.empty:
        return _empty("No sites with coordinates to map.")

    common = dict(
        lat="dec_lat_va",
        lon="dec_long_va",
        scope="usa",
        hover_name="station_nm",
        hover_data=_hover_data(plot),
    )

    if color_col == "location_type":
        fig = px.scatter_geo(
            plot,
            color="location_type",
            category_orders={"location_type": list(REGION_ORDER)},
            color_discrete_map=REGION_COLORS,
            **common,
        )
    else:
        plot = plot.dropna(subset=[color_col]) if color_col in plot.columns else plot
        if plot.empty:
            return _empty(f"No sites have a value for {label(color_col)}.")
        fig = px.scatter_geo(
            plot,
            color=color_col,
            color_continuous_scale="Viridis",
            **common,
        )
        fig.update_coloraxes(colorbar_title_text=label(color_col))

    fig.update_traces(marker=dict(size=8, line=dict(width=0.5, color="black")))
    fig.update_geos(
        showland=True, landcolor="#eef0f2",
        showlakes=True, lakecolor="#dfe7ef",
        subunitcolor="#9aa3ad",
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=40, b=0),
        title=("Sites colored by region" if color_col == "location_type"
               else f"Sites colored by {label(color_col)}"),
        legend_title_text="Region",
    )
    return fig


def scatter_figure(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    *,
    log_x: bool = False,
    log_y: bool = False,
    color_col: str = "location_type",
) -> go.Figure:
    """X/Y scatter colored by region, with optional log axes."""
    if df is None or df.empty:
        return _empty("No sites match the current filters.")
    for c in (x_col, y_col):
        if c not in df.columns:
            return _empty(f"Unknown column: {c}")

    plot = df.dropna(subset=[x_col, y_col]).copy()
    if log_x:
        plot = plot[plot[x_col] > 0]
    if log_y:
        plot = plot[plot[y_col] > 0]
    if plot.empty:
        return _empty("No sites have values for both axes (after log filtering).")

    fig = px.scatter(
        plot,
        x=x_col,
        y=y_col,
        color=color_col if color_col in plot.columns else None,
        category_orders={"location_type": list(REGION_ORDER)},
        color_discrete_map=REGION_COLORS,
        hover_name="station_nm",
        hover_data=_hover_data(plot),
        log_x=log_x,
        log_y=log_y,
    )
    fig.update_traces(marker=dict(size=9, line=dict(width=0.5, color="black")))
    fig.update_layout(
        margin=dict(l=60, r=20, t=50, b=50),
        xaxis_title=("log " if log_x else "") + label(x_col),
        yaxis_title=("log " if log_y else "") + label(y_col),
        title=f"{label(y_col)} vs {label(x_col)}",
        legend_title_text="Region",
    )
    return fig


def to_html(fig: go.Figure, div_id: str) -> str:
    """Interactive figure as an embeddable <div> (plotly.js loaded once in template)."""
    return fig.to_html(full_html=False, include_plotlyjs=False, div_id=div_id)


def to_png(fig: go.Figure, *, width: int = 1100, height: int = 650, scale: int = 2) -> bytes:
    """Static PNG via kaleido."""
    return fig.to_image(format="png", width=width, height=height, scale=scale)
