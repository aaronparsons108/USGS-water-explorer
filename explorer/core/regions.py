"""Regional labels for sites (port of research1 nitro/site_regions.py).

Coordinate boxes match the bubble/scatter maps. ``location_type`` strings match
the CSV exports and figure legends.
"""

from __future__ import annotations

import numpy as np

from .conversions import normalize_usgs_site_no

# Values written to the combined CSV column ``location_type``.
LOCATION_TYPE_BIG_MIDWEST = "Big Midwest cluster"
LOCATION_TYPE_MIDWEST = "Midwest"
LOCATION_TYPE_MID_ATLANTIC = "Mid Atlantic"
LOCATION_TYPE_FLORIDA = "Florida"
LOCATION_TYPE_OTHER = "Other"

# Optional explicit cluster membership (research1 ships this empty).
BIG_MIDWEST_CLUSTER_RAW: list[str] = []

# Stable ordering used in legends / dropdowns.
REGION_ORDER = (
    LOCATION_TYPE_BIG_MIDWEST,
    LOCATION_TYPE_MIDWEST,
    LOCATION_TYPE_MID_ATLANTIC,
    LOCATION_TYPE_FLORIDA,
    LOCATION_TYPE_OTHER,
)

# Hex colors for map/scatter coloring by region (light blue / dark blue / orange
# / red / gray), matching the scheme described in research1's scatterplots.
REGION_COLORS = {
    LOCATION_TYPE_BIG_MIDWEST: "#7fbfff",
    LOCATION_TYPE_MIDWEST: "#1f4e9c",
    LOCATION_TYPE_MID_ATLANTIC: "#ff8c1a",
    LOCATION_TYPE_FLORIDA: "#e8202a",
    LOCATION_TYPE_OTHER: "#888888",
}


def _big_midwest_id_set() -> set[str]:
    return {normalize_usgs_site_no(s) for s in BIG_MIDWEST_CLUSTER_RAW}


def assign_conus_region(lat, lon) -> str:
    """Approximate CONUS region from coordinates (same boxes as the maps)."""
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return "Others"
    if not (np.isfinite(lat_f) and np.isfinite(lon_f)):
        return "Others"
    if lat_f < 31.8 and lon_f > -87.6 and lon_f < -79.5:
        return "Florida"
    if 36.5 <= lat_f <= 47.8 and lon_f > -81.0 and lon_f <= -66.5:
        return "Mid Atlantic"
    if 35.0 <= lat_f <= 49.8 and -104.5 <= lon_f <= -81.0:
        return "Midwest"
    return "Others"


def site_location_type_label(site_no: str, lat, lon) -> str:
    """Human-readable ``location_type`` for a site."""
    if normalize_usgs_site_no(site_no) in _big_midwest_id_set():
        return LOCATION_TYPE_BIG_MIDWEST
    reg = assign_conus_region(lat, lon)
    if reg == "Florida":
        return LOCATION_TYPE_FLORIDA
    if reg == "Mid Atlantic":
        return LOCATION_TYPE_MID_ATLANTIC
    if reg == "Midwest":
        return LOCATION_TYPE_MIDWEST
    return LOCATION_TYPE_OTHER
