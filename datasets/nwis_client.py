"""NWIS discovery + download for a Dataset.

Discovery mirrors the original research workflow (pulling-scripts/siteretriever.py):
one ``get_info(seriesCatalogOutput=True)`` inventory call per state, filtered by
parameter codes / data-type / window overlap / wells rule; a site qualifies when
it has at least one code with data in EVERY parameter group.

Downloads write per-site wide CSVs in the exact research1 sitedata format
(``usgs_<site>_all_obs.csv`` with ``datetime, site_no, <code>_Mean, ...``) so the
existing parsing idioms apply unchanged.
"""

from __future__ import annotations

import time
from collections import defaultdict

import pandas as pd
from dataretrieval import nwis

from .catalog import CONUS_STATES
from .models import CandidateSite, Dataset

REQUEST_SLEEP_S = 0.4  # politeness between NWIS calls
DOWNLOAD_BATCH_SITES = 10  # sites per get_dv call


def _log(cb, msg: str) -> None:
    if cb:
        cb(msg)


def _norm_huc(h) -> str:
    """HUC codes have even length; pandas may parse them numeric and drop the
    leading zero ('02040205' -> 2040205). Restore it."""
    s = str(h or "").split(".")[0].strip()
    if not s.isdigit():
        return ""
    if len(s) % 2 == 1:
        s = "0" + s
    return s


def discover_sites(dataset: Dataset, progress=None, log=None) -> dict:
    """Query NWIS inventories and populate CandidateSite rows.

    ``progress(frac, message)`` and ``log(line)`` are optional callbacks.
    Returns summary counts. Per-state failures are logged and skipped.
    """
    states = dataset.states or CONUS_STATES
    codes = dataset.all_pmcodes()
    services = [s.lower() for s in (dataset.services or ["dv"])]
    start = dataset.start_date.isoformat()
    end = dataset.end_date.isoformat()
    groups = dataset.groups_ordered()
    code_to_groups: dict[str, list[int]] = defaultdict(list)
    for g in groups:
        for c in g.codes():
            code_to_groups[c].append(g.position)

    frames: list[pd.DataFrame] = []
    failed_states: list[str] = []
    for i, st in enumerate(states):
        if progress:
            progress(i / max(1, len(states)), f"Querying {st} ({i + 1}/{len(states)})")
        try:
            sites, _ = nwis.get_info(
                stateCd=st, parameterCd=codes, seriesCatalogOutput=True
            )
        except Exception as e:
            failed_states.append(st)
            _log(log, f"{st}: FAILED ({type(e).__name__}: {str(e)[:120]})")
            time.sleep(REQUEST_SLEEP_S)
            continue

        if sites.empty:
            _log(log, f"{st}: no sites")
            time.sleep(REQUEST_SLEEP_S)
            continue

        s = sites.copy()
        s["parm_cd"] = s["parm_cd"].astype(str).str.zfill(5)
        s = s[s["parm_cd"].isin(codes)]
        s = s[s["data_type_cd"].astype(str).str.lower().isin(services)]
        s["site_no"] = s["site_no"].astype(str)
        if dataset.exclude_wells:
            s = s[s["site_no"].str.len() != 15]
        # window overlap: series must intersect [start, end]
        s = s[(s["begin_date"].astype(str) <= end) & (s["end_date"].astype(str) >= start)]
        cnt = pd.to_numeric(s["count_nu"], errors="coerce").fillna(0)
        s = s[cnt >= dataset.min_count_per_series]
        s["state_cd"] = st
        _log(log, f"{st}: {s['site_no'].nunique()} sites with qualifying series")
        if not s.empty:
            frames.append(s)
        time.sleep(REQUEST_SLEEP_S)

    dataset.sites.all().delete()
    if not frames:
        return {"candidates": 0, "qualifying": 0, "failed_states": failed_states}

    inv = pd.concat(frames, ignore_index=True)

    rows: list[CandidateSite] = []
    n_candidates = inv["site_no"].nunique()
    for site_no, sub in inv.groupby("site_no"):
        coverage: dict[str, list[str]] = defaultdict(list)
        for code in sub["parm_cd"].unique():
            for pos in code_to_groups.get(code, []):
                coverage[str(pos)].append(code)
        if len(coverage) < len(groups):
            continue  # must have >=1 code in EVERY group
        first = sub.iloc[0]
        rows.append(
            CandidateSite(
                dataset=dataset,
                site_no=str(site_no),
                station_nm=str(first.get("station_nm") or "")[:200],
                state_cd=str(first.get("state_cd") or ""),
                site_tp_cd=str(first.get("site_tp_cd") or "")[:12],
                dec_lat_va=pd.to_numeric(first.get("dec_lat_va"), errors="coerce"),
                dec_long_va=pd.to_numeric(first.get("dec_long_va"), errors="coerce"),
                huc_cd=_norm_huc(first.get("huc_cd")),
                group_coverage={k: sorted(set(v)) for k, v in coverage.items()},
                begin_date=str(sub["begin_date"].min()),
                end_date=str(sub["end_date"].max()),
                total_count=int(pd.to_numeric(sub["count_nu"], errors="coerce").fillna(0).sum()),
                selected=True,
            )
        )
    CandidateSite.objects.bulk_create(rows)
    _log(log, f"Qualifying sites (all {len(groups)} groups): {len(rows)} of {n_candidates} candidates")
    return {"candidates": int(n_candidates), "qualifying": len(rows), "failed_states": failed_states}


def download_dv(dataset: Dataset, progress=None, log=None) -> dict:
    """Download daily values for every selected site; write research1-format CSVs."""
    sites = list(dataset.sites.filter(selected=True).values_list("site_no", flat=True))
    codes = dataset.all_pmcodes()
    start = dataset.start_date.isoformat()
    end = dataset.end_date.isoformat()

    raw = dataset.raw_dir
    raw.mkdir(parents=True, exist_ok=True)

    ok, empty, failed = 0, 0, []
    batches = [sites[i : i + DOWNLOAD_BATCH_SITES] for i in range(0, len(sites), DOWNLOAD_BATCH_SITES)]
    done = 0
    for batch in batches:
        if progress:
            progress(done / max(1, len(sites)), f"Downloading sites {done + 1}-{min(done + len(batch), len(sites))} of {len(sites)}")
        try:
            df, _ = nwis.get_dv(
                sites=batch, parameterCd=codes, start=start, end=end, multi_index=False
            )
        except Exception as e:
            failed.extend(batch)
            _log(log, f"batch {batch[0]}..{batch[-1]}: FAILED ({type(e).__name__}: {str(e)[:120]})")
            done += len(batch)
            time.sleep(REQUEST_SLEEP_S)
            continue

        if df is None or df.empty:
            empty += len(batch)
            _log(log, f"batch {batch[0]}..{batch[-1]}: no data")
            done += len(batch)
            time.sleep(REQUEST_SLEEP_S)
            continue

        df = df.reset_index()
        # normalize the time column name to research1's 'datetime'
        tcol = next((c for c in ("datetime", "dateTime", "index") if c in df.columns), None)
        if tcol and tcol != "datetime":
            df = df.rename(columns={tcol: "datetime"})
        if "site_no" not in df.columns:  # single-site frames may drop it
            df["site_no"] = batch[0]
        df["site_no"] = df["site_no"].astype(str)

        for site_no, sub in df.groupby("site_no"):
            sub = sub.dropna(axis=1, how="all")
            value_cols = [c for c in sub.columns if c not in ("datetime", "site_no")]
            if not value_cols:
                empty += 1
                continue
            cols = ["datetime", "site_no"] + value_cols
            sub[cols].to_csv(raw / f"usgs_{site_no}_all_obs.csv", index=False)
            ok += 1
            _log(log, f"{site_no}: {len(sub)} days, {len(value_cols)} columns")
        done += len(batch)
        time.sleep(REQUEST_SLEEP_S)

    if progress:
        progress(1.0, f"Downloaded {ok} sites ({empty} empty, {len(failed)} failed)")
    return {"ok": ok, "empty": empty, "failed": failed}
