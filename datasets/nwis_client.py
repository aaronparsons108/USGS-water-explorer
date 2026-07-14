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

import pandas as pd

from .catalog import CONUS_STATES
from .models import CandidateSite, Dataset

# dataretrieval prints a "Geopandas not installed" notice on import (harmless —
# this app only uses plain-DataFrame columns). Import lazily so manage.py
# commands don't print it; it surfaces once when the first NWIS job runs.


def _nwis():
    from dataretrieval import nwis

    return nwis

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


# Daily-value stat code for the Mean statistic; the analysis pipeline only uses
# *_Mean columns, so only Mean series make a site qualify.
DV_MEAN_STAT = 3
# NWIS throttles bursts with 503s; retry failed states with growing pauses.
RETRY_ROUNDS = (5, 20)  # seconds to wait before each retry round


def _filter_inventory(sites: pd.DataFrame, dataset: Dataset, codes, services, start, end, st):
    """Apply the dataset's series filters to one state's inventory frame."""
    s = sites.copy()
    s["parm_cd"] = s["parm_cd"].astype(str).str.zfill(5)
    s = s[s["parm_cd"].isin(codes)]
    s = s[s["data_type_cd"].astype(str).str.lower().isin(services)]
    # dv series must carry the Mean statistic (00003) — Max/Min/Median-only
    # series can't feed the daily-mean analysis.
    if "stat_cd" in s.columns:
        is_dv = s["data_type_cd"].astype(str).str.lower() == "dv"
        stat = pd.to_numeric(s["stat_cd"], errors="coerce")
        s = s[~is_dv | (stat == DV_MEAN_STAT)]
    s["site_no"] = s["site_no"].astype(str)
    if dataset.exclude_wells:
        s = s[s["site_no"].str.len() != 15]
    # window overlap: series must intersect [start, end]
    s = s[(s["begin_date"].astype(str) <= end) & (s["end_date"].astype(str) >= start)]
    cnt = pd.to_numeric(s["count_nu"], errors="coerce").fillna(0)
    s = s[cnt >= dataset.min_count_per_series]
    s["state_cd"] = st
    return s


def discover_sites(dataset: Dataset, progress=None, log=None) -> dict:
    """Query NWIS inventories and populate CandidateSite rows.

    ``progress(frac, message)`` and ``log(line)`` are optional callbacks.
    Failed states are automatically retried (NWIS often 503s under load);
    anything that still fails is reported in the summary.
    """
    states = dataset.states or CONUS_STATES
    codes = dataset.all_pmcodes()
    services = [s.lower() for s in (dataset.services or ["dv"])]
    start = dataset.start_date.isoformat()
    end = dataset.end_date.isoformat()
    groups = dataset.groups_ordered()
    group_codes = {g.position: set(g.codes()) for g in groups}
    group_canonical = {g.position: g.require_canonical for g in groups}

    frames: list[pd.DataFrame] = []

    def query_states(todo: list[str], round_label: str) -> list[str]:
        failed: list[str] = []
        for i, st in enumerate(todo):
            if progress:
                progress(i / max(1, len(todo)), f"{round_label}{st} ({i + 1}/{len(todo)})")
            try:
                sites, _ = _nwis().get_info(
                    stateCd=st, parameterCd=codes, seriesCatalogOutput=True
                )
            except Exception as e:
                failed.append(st)
                _log(log, f"{st}: FAILED ({type(e).__name__}: {str(e)[:120]})")
                time.sleep(REQUEST_SLEEP_S)
                continue

            if sites.empty:
                _log(log, f"{st}: no sites")
                time.sleep(REQUEST_SLEEP_S)
                continue

            s = _filter_inventory(sites, dataset, codes, services, start, end, st)
            _log(log, f"{st}: {s['site_no'].nunique()} sites with qualifying series")
            if not s.empty:
                frames.append(s)
            time.sleep(REQUEST_SLEEP_S)
        return failed

    failed_states = query_states(list(states), "Querying ")
    for wait in RETRY_ROUNDS:
        if not failed_states:
            break
        _log(log, f"Retrying {len(failed_states)} failed states in {wait}s: {', '.join(failed_states)}")
        if progress:
            progress(0.0, f"Waiting {wait}s before retrying {len(failed_states)} states…")
        time.sleep(wait)
        failed_states = query_states(failed_states, "Retry ")

    dataset.sites.all().delete()
    if not frames:
        return {"candidates": 0, "qualifying": 0, "failed_states": failed_states}

    inv = pd.concat(frames, ignore_index=True)

    # A series is "canonical" when NWIS gives it no web label (loc_web_ds);
    # labeled series download as "<code>_<label>_Mean" auxiliary columns.
    if "loc_web_ds" in inv.columns:
        lab = inv["loc_web_ds"]
        inv["is_canonical"] = lab.isna() | (lab.astype(str).str.strip().isin(["", "nan"]))
    else:
        inv["is_canonical"] = True

    rows: list[CandidateSite] = []
    n_candidates = inv["site_no"].nunique()
    for site_no, sub in inv.groupby("site_no"):
        coverage: dict[str, list[str]] = {}
        for pos, gcodes in group_codes.items():
            g_rows = sub[sub["parm_cd"].isin(gcodes)]
            if group_canonical[pos]:
                g_rows = g_rows[g_rows["is_canonical"]]
            if not g_rows.empty:
                coverage[str(pos)] = sorted(g_rows["parm_cd"].unique())
        if len(coverage) < len(groups):
            continue  # must have >=1 qualifying code in EVERY group
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
                group_coverage=coverage,
                begin_date=str(sub["begin_date"].min()),
                end_date=str(sub["end_date"].max()),
                total_count=int(pd.to_numeric(sub["count_nu"], errors="coerce").fillna(0).sum()),
                selected=True,
            )
        )
    CandidateSite.objects.bulk_create(rows)
    _log(log, f"Qualifying sites (all {len(groups)} groups): {len(rows)} of {n_candidates} candidates")
    return {"candidates": int(n_candidates), "qualifying": len(rows), "failed_states": failed_states}


def download_dv(dataset: Dataset, progress=None, log=None, sites=None) -> dict:
    """Download daily values for the selected sites; write research1-format CSVs.

    Failed batches are retried (same rounds as discovery). ``sites`` overrides
    the selected-site list for targeted re-fetches.
    """
    if sites is None:
        sites = list(dataset.sites.filter(selected=True).values_list("site_no", flat=True))
    codes = dataset.all_pmcodes()
    start = dataset.start_date.isoformat()
    end = dataset.end_date.isoformat()

    raw = dataset.raw_dir
    raw.mkdir(parents=True, exist_ok=True)

    counts = {"ok": 0, "empty": 0}

    def fetch_batches(todo: list[str], round_label: str) -> list[str]:
        failed: list[str] = []
        batches = [todo[i : i + DOWNLOAD_BATCH_SITES] for i in range(0, len(todo), DOWNLOAD_BATCH_SITES)]
        done = 0
        for batch in batches:
            if progress:
                progress(
                    done / max(1, len(todo)),
                    f"{round_label}sites {done + 1}-{min(done + len(batch), len(todo))} of {len(todo)}",
                )
            try:
                df, _ = _nwis().get_dv(
                    sites=batch, parameterCd=codes, start=start, end=end, multi_index=False
                )
            except Exception as e:
                failed.extend(batch)
                _log(log, f"batch {batch[0]}..{batch[-1]}: FAILED ({type(e).__name__}: {str(e)[:120]})")
                done += len(batch)
                time.sleep(REQUEST_SLEEP_S)
                continue

            if df is None or df.empty:
                counts["empty"] += len(batch)
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
                    counts["empty"] += 1
                    continue
                cols = ["datetime", "site_no"] + value_cols
                sub[cols].to_csv(raw / f"usgs_{site_no}_all_obs.csv", index=False)
                counts["ok"] += 1
                _log(log, f"{site_no}: {len(sub)} days, {len(value_cols)} columns")
            done += len(batch)
            time.sleep(REQUEST_SLEEP_S)
        return failed

    failed = fetch_batches(list(sites), "Downloading ")
    for wait in RETRY_ROUNDS:
        if not failed:
            break
        _log(log, f"Retrying {len(failed)} failed sites in {wait}s")
        if progress:
            progress(0.0, f"Waiting {wait}s before retrying {len(failed)} sites…")
        time.sleep(wait)
        failed = fetch_batches(failed, "Retry ")

    if progress:
        progress(1.0, f"Downloaded {counts['ok']} sites ({counts['empty']} empty, {len(failed)} failed)")
    return {"ok": counts["ok"], "empty": counts["empty"], "failed": failed}
