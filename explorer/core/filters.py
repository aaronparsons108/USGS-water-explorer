"""Apply user filters to the assembled per-site table (metadata + metrics)."""

from __future__ import annotations

import pandas as pd

from .conversions import normalize_usgs_site_no


def _site_matches(out: pd.DataFrame, query: str) -> pd.Series:
    """Case-insensitive match on site number or station name.

    Site numbers are stored canonically (leading zeros stripped, see
    ``normalize_usgs_site_no``) so that the metadata CSVs and the NWIS
    inventory join, but users copy ids straight off a USGS page, where they
    keep their leading zeros. Normalizing the query the same way means
    ``01463500`` and ``1463500`` both find the site.
    """
    q = str(query).strip().lower()
    if not q:
        return pd.Series(True, index=out.index)

    sno = out["site_no"].astype(str).str.lower()
    name = out["station_nm"].astype(str).str.lower()
    mask = sno.str.contains(q, na=False, regex=False) | name.str.contains(
        q, na=False, regex=False
    )

    canonical = normalize_usgs_site_no(q).lower()
    if canonical and canonical != q:
        mask |= sno.str.contains(canonical, na=False, regex=False)
    return mask


def apply_filters(
    df: pd.DataFrame,
    *,
    regions=None,
    huc2s=None,
    site_query: str | None = None,
    ranges: dict[str, tuple[float | None, float | None]] | None = None,
) -> pd.DataFrame:
    """Return the rows matching every active filter.

    - ``regions``: keep rows whose ``location_type`` is in this list.
    - ``huc2s``: keep rows whose ``huc2`` is in this list.
    - ``site_query``: substring match on site number or station name.
    - ``ranges``: ``{column: (min, max)}``; either bound may be None (open).

    A range filter always drops rows whose value is missing: "median between 1
    and 5" cannot honestly include a site with no median.
    """
    out = df
    if regions:
        out = out[out["location_type"].isin(list(regions))]
    if huc2s:
        out = out[out["huc2"].astype(str).isin([str(h) for h in huc2s])]
    if site_query:
        out = out[_site_matches(out, site_query)]
    if ranges:
        for col, (lo, hi) in ranges.items():
            if col not in out.columns or (lo is None and hi is None):
                continue
            vals = pd.to_numeric(out[col], errors="coerce")
            mask = vals.notna()
            if lo is not None:
                mask &= vals >= lo
            if hi is not None:
                mask &= vals <= hi
            out = out[mask]
    return out
