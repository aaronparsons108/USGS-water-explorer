"""USGS parameter-code catalog: loading, search, and the example preset.

The picker searches this catalog. The live source is
``dataretrieval.waterdata.get_reference_table(collection="parameter-codes")``
(the old ``nwis.get_pmcodes`` is defunct). A committed snapshot at
``data/pmcode_catalog.csv`` keeps the picker working offline, and a Parquet
cache under ``.cache/`` makes repeat loads fast.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
from django.conf import settings

SNAPSHOT_NAME = "pmcode_catalog.csv"
CACHE_NAME = "pmcodes.parquet"
COLUMNS = [
    "parameter_code",
    "parameter_name",
    "unit_of_measure",
    "parameter_group_code",
    "parameter_description",
]

# One-click preset matching the original nitrate study. Streamflow is
# canonical-only, because the study required the literal 00060_Mean series;
# the analyte groups accept sensor-labeled variants, as the study did.
EXAMPLE_GROUPS = [
    {
        "label": "Nitrate/Nitrite",
        "codes": ["99133", "00631", "00630", "91049", "91061", "83554"],
        "require_canonical": False,
    },
    {"label": "Streamflow", "codes": ["00060"], "require_canonical": True},
    {"label": "Dissolved Oxygen", "codes": ["00300"], "require_canonical": False},
]

# Standard WBD HUC2 region names (no shapefile needed).
HUC2_REGION_NAMES = {
    "01": "New England", "02": "Mid-Atlantic", "03": "South Atlantic-Gulf",
    "04": "Great Lakes", "05": "Ohio", "06": "Tennessee",
    "07": "Upper Mississippi", "08": "Lower Mississippi", "09": "Souris-Red-Rainy",
    "10": "Missouri", "11": "Arkansas-White-Red", "12": "Texas-Gulf",
    "13": "Rio Grande", "14": "Upper Colorado", "15": "Lower Colorado",
    "16": "Great Basin", "17": "Pacific Northwest", "18": "California",
    "19": "Alaska", "20": "Hawaii", "21": "Caribbean", "22": "Pacific Islands",
}

CONUS_STATES = [
    "AL", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA",
    "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]
ALL_STATES = CONUS_STATES + ["AK", "HI", "DC", "PR"]

# data_type_cd values seen in NWIS series catalogs. Only dv is downloadable.
SERVICE_CHOICES = [
    ("dv", "Daily values (dv), downloadable"),
    ("uv", "Instantaneous (uv), filter only"),
    ("qw", "Water-quality samples (qw), filter only, endpoint retired"),
    ("gw", "Groundwater levels (gw), filter only"),
    ("ad", "Annual data (ad), filter only"),
    ("pk", "Peaks (pk), filter only"),
    ("sv", "Site visits (sv), filter only"),
]


def _snapshot_path() -> Path:
    return Path(settings.DATA_DIR) / SNAPSHOT_NAME


def refresh_catalog_from_nwis() -> pd.DataFrame:
    """Fetch the live reference table and cache it; raises on network failure."""
    from dataretrieval import waterdata

    df, _ = waterdata.get_reference_table(collection="parameter-codes")
    df = df[[c for c in COLUMNS if c in df.columns]].copy()
    df["parameter_code"] = df["parameter_code"].astype(str).str.zfill(5)
    cache = Path(settings.CACHE_DIR) / CACHE_NAME
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache, index=False)
    return df


@lru_cache(maxsize=1)
def load_catalog() -> pd.DataFrame:
    """Parquet cache, then committed snapshot, then live fetch. First hit wins.

    A corrupt Parquet cache falls through to the snapshot rather than taking
    the picker down; the cache is a speed-up, never the only copy.
    """
    cache = Path(settings.CACHE_DIR) / CACHE_NAME
    if cache.is_file():
        try:
            return pd.read_parquet(cache)
        except Exception:
            pass
    snap = _snapshot_path()
    if snap.is_file():
        df = pd.read_csv(snap, dtype={"parameter_code": str})
        df["parameter_code"] = df["parameter_code"].astype(str).str.zfill(5)
        return df
    return refresh_catalog_from_nwis()


def search_pmcodes(q: str, limit: int = 25) -> list[dict]:
    """Code-prefix or name/description substring search for the picker."""
    q = (q or "").strip()
    if not q:
        return []
    df = load_catalog()

    def col(name: str) -> pd.Series:
        """A column as lowercase text, or blanks if this snapshot lacks it.

        Read-only on purpose: ``load_catalog`` is memoized, and adding a column
        here would mutate the frame every later caller shares.
        """
        if name not in df.columns:
            return pd.Series("", index=df.index)
        return df[name].astype(str).str.lower()

    ql = q.lower()
    if q.isdigit():
        hits = df[df["parameter_code"].astype(str).str.startswith(q)]
    else:
        name = col("parameter_name")
        desc = col("parameter_description")
        hits = df[
            name.str.contains(ql, na=False, regex=False)
            | desc.str.contains(ql, na=False, regex=False)
        ]
    out = []
    for _, r in hits.head(limit).iterrows():
        out.append(
            {
                "code": r["parameter_code"],
                "name": str(r.get("parameter_name") or ""),
                "unit": str(r.get("unit_of_measure") or ""),
                "group": str(r.get("parameter_group_code") or ""),
                "description": str(r.get("parameter_description") or "")[:160],
            }
        )
    return out


def pmcode_info(codes: list[str]) -> list[dict]:
    """Picker dicts for known codes, used by the example preset.

    Duplicate parameter codes do occur in the reference table, so the first row
    wins rather than ``.loc`` handing back a DataFrame that ``.get`` would
    silently turn into a Series of values.
    """
    df = load_catalog().drop_duplicates(subset=["parameter_code"]).set_index("parameter_code")
    out = []
    for c in codes:
        c = str(c).zfill(5)
        if c in df.index:
            r = df.loc[c]
            out.append(
                {
                    "code": c,
                    "name": str(r.get("parameter_name") or ""),
                    "unit": str(r.get("unit_of_measure") or ""),
                }
            )
        else:
            out.append({"code": c, "name": "", "unit": ""})
    return out
