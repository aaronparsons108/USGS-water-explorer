"""Coarse geographic labels for CONUS sites.

``location_type`` is a cheap, coordinate-only bucketing used for map and
scatter coloring and for the region filter. It is intentionally crude: HUC2 is
the hydrologically meaningful grouping and is available alongside it. The boxes
below match the ones the original study used, so demo values keep matching the
published figures.
"""

from __future__ import annotations

import numpy as np

LOCATION_TYPE_MIDWEST = "Midwest"
LOCATION_TYPE_MID_ATLANTIC = "Mid Atlantic"
LOCATION_TYPE_FLORIDA = "Florida"
LOCATION_TYPE_OTHER = "Other"

# Stable ordering for legends and filter lists.
REGION_ORDER = (
    LOCATION_TYPE_MIDWEST,
    LOCATION_TYPE_MID_ATLANTIC,
    LOCATION_TYPE_FLORIDA,
    LOCATION_TYPE_OTHER,
)

# Fixed hues so a region reads identically on every figure and every export.
REGION_COLORS = {
    LOCATION_TYPE_MIDWEST: "#1f4e9c",
    LOCATION_TYPE_MID_ATLANTIC: "#ef7d18",
    LOCATION_TYPE_FLORIDA: "#d92b36",
    LOCATION_TYPE_OTHER: "#7c8794",
}

# Coordinate predicates, evaluated in order; the first match wins. The exact
# comparison operators are preserved from the original study so demo region
# assignments stay byte-identical to the published figures.
_BOXES = (
    (LOCATION_TYPE_FLORIDA, lambda la, lo: la < 31.8 and -87.6 < lo < -79.5),
    (LOCATION_TYPE_MID_ATLANTIC, lambda la, lo: 36.5 <= la <= 47.8 and -81.0 < lo <= -66.5),
    (LOCATION_TYPE_MIDWEST, lambda la, lo: 35.0 <= la <= 49.8 and -104.5 <= lo <= -81.0),
)


def assign_conus_region(lat, lon) -> str:
    """Approximate CONUS region from coordinates."""
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return LOCATION_TYPE_OTHER
    if not (np.isfinite(lat_f) and np.isfinite(lon_f)):
        return LOCATION_TYPE_OTHER
    for label, in_box in _BOXES:
        if in_box(lat_f, lon_f):
            return label
    return LOCATION_TYPE_OTHER


def site_location_type_label(site_no: str, lat, lon) -> str:
    """Human-readable ``location_type`` for a site.

    ``site_no`` is accepted so callers can pass a whole row; it is unused today
    but keeps the signature stable for per-site overrides.
    """
    del site_no  # coordinates alone decide the bucket
    return assign_conus_region(lat, lon)
