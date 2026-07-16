"""CONUS bubble-map rendering (Cartopy + simple fallback) -> PNG bytes.

Vendored from nitro-research (dissolved_oxygen/conus_bubble_plot.py) and adapted
for the web app: Agg backend, returns PNG bytes, and a self-contained cached
US-states loader (no nitro import). Style matches the research figures.
"""

from __future__ import annotations

import io
import os
import textwrap
from functools import lru_cache
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless server rendering
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LogNorm, Normalize  # noqa: E402

CONUS_EXTENT = (-130, -65, 24, 50)
MARKER_SIZE = 85
# Research-style text sizing (numeric, so it never trips int() on rcParams).
_MAP_RC = {
    "font.size": 15.0, "axes.titlesize": 20.0, "axes.labelsize": 16.0,
    "xtick.labelsize": 13.0, "ytick.labelsize": 13.0,
}
_CENSUS_STATES_URL = (
    "https://www2.census.gov/geo/tiger/GENZ2022/shp/cb_2022_us_state_500k.zip"
)
_STATES_CACHE = Path(__file__).resolve().parent / "_us_states_conus.gpkg"


@lru_cache(maxsize=1)
def load_states_conus():
    """CONUS state polygons (EPSG:4326), cached to disk then in-memory."""
    import geopandas as gpd

    if _STATES_CACHE.is_file():
        try:
            return gpd.read_file(_STATES_CACHE)
        except Exception:  # corrupt/partial cache -> drop it and re-download
            try:
                _STATES_CACHE.unlink()
            except OSError:
                pass
    gdf = gpd.read_file(_CENSUS_STATES_URL)
    gdf = gdf[~gdf["STUSPS"].isin(["PR", "VI", "GU", "MP", "AS"])].to_crs("EPSG:4326")
    try:  # atomic write: temp file then replace, so a kill never corrupts the cache
        tmp = _STATES_CACHE.with_suffix(".gpkg.tmp")
        gdf.to_file(tmp, driver="GPKG")
        os.replace(tmp, _STATES_CACHE)
    except Exception:  # pragma: no cover - caching is best-effort
        pass
    return gdf


def _make_norm(vals: np.ndarray, *, log: bool) -> Normalize:
    """5th-95th percentile color scale (matches the research maps)."""
    v = np.asarray(vals, dtype=float)
    v = v[np.isfinite(v)]
    if log:
        v = v[v > 0]
    if v.size == 0:
        return Normalize(0, 1)
    vmin = float(np.nanpercentile(v, 5))
    vmax = float(np.nanpercentile(v, 95))
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax <= vmin:
        vmin, vmax = float(v.min()), float(v.max())
        if vmax <= vmin:
            vmax = vmin + 1e-9
    if log:
        return LogNorm(vmin=max(vmin, 1e-9), vmax=vmax)
    return Normalize(vmin=vmin, vmax=vmax)


def _fig_to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", pad_inches=0.35)
    plt.close(fig)
    return buf.getvalue()


def _cbar_fontsize(label: str) -> int:
    n = len(label)
    return 11 if n > 42 else 12 if n > 30 else 14


def _plot_cartopy(plot_df, color_col, *, cmap, norm, title, cbar_label, figsize, marker_size):
    import cartopy.crs as ccrs
    import geopandas as gpd

    gdf_states = load_states_conus()
    gdf = gpd.GeoDataFrame(
        plot_df,
        geometry=gpd.points_from_xy(plot_df["dec_long_va"], plot_df["dec_lat_va"]),
        crs="EPSG:4326",
    )
    fig, ax = plt.subplots(figsize=figsize, subplot_kw={"projection": ccrs.PlateCarree()})
    try:  # if any cartopy/basemap step fails, close this fig before falling back
        ax.set_extent(CONUS_EXTENT)
        gdf_states.boundary.plot(ax=ax, linewidth=0.6, edgecolor="gray", zorder=1)
        gdf_states.plot(ax=ax, facecolor="lightgray", edgecolor="gray", linewidth=0.4, alpha=0.5, zorder=0)
        sc = ax.scatter(
            gdf["dec_long_va"], gdf["dec_lat_va"], c=gdf[color_col], s=marker_size,
            cmap=cmap, norm=norm, alpha=0.85, edgecolors="black", linewidths=0.35,
            transform=ccrs.PlateCarree(), zorder=5,
        )
        ax.coastlines(resolution="50m", linewidth=0.6)
        cbar = plt.colorbar(sc, ax=ax, shrink=0.7, pad=0.02)
        cbar.ax.tick_params(labelsize=13)
        cbar.set_label(cbar_label, fontsize=_cbar_fontsize(cbar_label))
        ax.set_title(title)
    except Exception:
        plt.close(fig)
        raise
    return fig


def _plot_simple_latlon(plot_df, color_col, *, cmap, norm, title, cbar_label, figsize, marker_size):
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_xlim(CONUS_EXTENT[0], CONUS_EXTENT[1])
    ax.set_ylim(CONUS_EXTENT[2], CONUS_EXTENT[3])
    ax.set_facecolor("0.92")
    ax.set_aspect("equal", adjustable="box")
    sc = ax.scatter(
        plot_df["dec_long_va"], plot_df["dec_lat_va"], c=plot_df[color_col], s=marker_size,
        cmap=cmap, norm=norm, alpha=0.85, edgecolors="black", linewidths=0.35, zorder=5,
    )
    cbar = plt.colorbar(sc, ax=ax, shrink=0.7, pad=0.02)
    cbar.set_label(cbar_label, fontsize=_cbar_fontsize(cbar_label))
    ax.set_title(title)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    return fig


def conus_bubble_png(
    df: pd.DataFrame,
    value_col: str,
    *,
    cmap: str = "viridis",
    log_color: bool = False,
    title: str = "",
    cbar_label: str = "",
    marker_size: float = MARKER_SIZE,
    figsize: tuple[float, float] = (12.0, 6.5),
) -> bytes:
    """Render a research-style CONUS bubble map to PNG bytes."""
    plot = df.dropna(subset=["dec_lat_va", "dec_long_va", value_col]).copy()
    if plot.empty:
        fig, ax = plt.subplots(figsize=figsize)
        ax.text(0.5, 0.5, "No sites with values to map.", ha="center", va="center")
        ax.axis("off")
        return _fig_to_png(fig)
    norm = _make_norm(plot[value_col].to_numpy(float), log=log_color)
    if len(title) > 46:  # wrap long titles so they never overflow the width
        title = textwrap.fill(title, 46)
    kw = dict(cmap=cmap, norm=norm, title=title, cbar_label=cbar_label,
              figsize=figsize, marker_size=marker_size)
    with plt.rc_context(_MAP_RC):
        try:
            fig = _plot_cartopy(plot, value_col, **kw)
        except Exception as exc:  # cartopy/basemap unavailable
            print(f"Cartopy basemap unavailable ({exc}); using simple lat/lon plot.")
            fig = _plot_simple_latlon(plot, value_col, **kw)
        return _fig_to_png(fig)
