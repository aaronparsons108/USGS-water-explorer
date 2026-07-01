"""Apply user filters to the assembled per-site table (metadata + metrics)."""

from __future__ import annotations

import pandas as pd


def apply_filters(
    df: pd.DataFrame,
    *,
    regions=None,
    huc2s=None,
    site_query: str | None = None,
    ranges: dict[str, tuple[float | None, float | None]] | None = None,
) -> pd.DataFrame:
    """Return rows matching every active filter.

    - ``regions``: keep rows whose ``location_type`` is in this list.
    - ``huc2s``: keep rows whose ``huc2`` is in this list.
    - ``site_query``: case-insensitive substring match on site_no or station_nm.
    - ``ranges``: ``{column: (min, max)}``; either bound may be None (open).
    """
    out = df
    if regions:
        out = out[out["location_type"].isin(list(regions))]
    if huc2s:
        out = out[out["huc2"].astype(str).isin([str(h) for h in huc2s])]
    if site_query:
        q = str(site_query).strip().lower()
        if q:
            sno = out["site_no"].astype(str).str.lower()
            name = out["station_nm"].astype(str).str.lower()
            out = out[sno.str.contains(q, na=False) | name.str.contains(q, na=False)]
    if ranges:
        for col, (lo, hi) in ranges.items():
            if col not in out.columns:
                continue
            if lo is None and hi is None:
                continue
            vals = pd.to_numeric(out[col], errors="coerce")
            mask = vals.notna()
            if lo is not None:
                mask &= vals >= lo
            if hi is not None:
                mask &= vals <= hi
            out = out[mask]
    return out
