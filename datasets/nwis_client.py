"""NWIS discovery and download for a Dataset.

Discovery runs one ``get_info(seriesCatalogOutput=True)`` inventory call per
state, filters the returned series by parameter code, data type, window overlap
and the wells rule, and keeps a site only when it has at least one qualifying
code in EVERY parameter group.

Downloads write per-site wide CSVs in the layout the builder expects
(``usgs_<site>_all_obs.csv`` with ``datetime, site_no, <code>_Mean, ...``).
"""

from __future__ import annotations

import time

import pandas as pd
from django.db import transaction

from .catalog import CONUS_STATES
from .models import CandidateSite, Dataset

REQUEST_SLEEP_S = 0.4  # politeness between NWIS calls
DOWNLOAD_BATCH_SITES = 10  # sites per get_dv call

# Daily-value stat code for the Mean statistic. The analysis only consumes
# *_Mean columns, so only Mean series can make a site qualify.
DV_MEAN_STAT = 3

# NWIS throttles bursts with 503s; failed states are retried with growing pauses.
RETRY_ROUNDS = (5, 20)  # seconds to wait before each retry round


def _nwis():
    """Import dataretrieval lazily.

    It prints a "Geopandas not installed" notice at import time, which is
    harmless here (this app only reads plain DataFrame columns) but noisy on
    every manage.py command if imported at module scope.
    """
    from dataretrieval import nwis

    return nwis


def _log(cb, msg: str) -> None:
    if cb:
        cb(msg)


def _norm_code(v) -> str:
    """Canonical 5-digit parameter code from an inventory cell.

    A ``seriesCatalogOutput`` frame contains rows with no parameter code at all
    (peak, site-visit and groundwater series), which makes pandas type the whole
    column float64. Left alone, ``astype(str).str.zfill(5)`` then turns 60 into
    "060.0" and nothing matches, so discovery quietly finds zero sites. Strip
    the float tail before padding.
    """
    s = str(v if v is not None else "").strip()
    if s in ("", "nan", "None", "<NA>"):
        return ""
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s.zfill(5) if s.isdigit() else s


def _norm_site_no(v) -> str:
    """One site number as text, with any float tail removed."""
    s = str(v if v is not None else "").strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


# USGS site numbers are at least eight digits.
MIN_SITE_NO_DIGITS = 8


def _site_no_series(series: pd.Series, log=None) -> pd.Series:
    """Normalize a whole site_no column, restoring zeros only when needed.

    dataretrieval normally reads site_no as text, which is what we want. If it
    ever comes back numeric, the leading zeros are already gone, and an id like
    ``01408500`` would name its download file ``usgs_1408500_all_obs.csv`` and
    be sent to NWIS seven digits long. Zero-padding back to the minimum length
    repairs the common case; ids that are natively longer than eight digits
    cannot be recovered, so say so rather than pretending.
    """
    out = series.map(_norm_site_no)
    if pd.api.types.is_numeric_dtype(series):
        short = out.str.isdigit() & (out.str.len() < MIN_SITE_NO_DIGITS)
        if short.any():
            _log(
                log,
                f"WARNING: site numbers arrived as numbers; zero-padding "
                f"{int(short.sum())} of them back to {MIN_SITE_NO_DIGITS} digits. "
                "Ids longer than that may still be wrong.",
            )
        out = out.where(~short, out.str.zfill(MIN_SITE_NO_DIGITS))
    return out


def _norm_huc(h) -> str:
    """HUC codes have even length; a numeric parse drops the leading zero."""
    s = str(h or "").split(".")[0].strip()
    if not s.isdigit():
        return ""
    if len(s) % 2 == 1:
        s = "0" + s
    return s


def _filter_inventory(
    sites: pd.DataFrame, dataset: Dataset, codes, services, start, end, st, log=None
):
    """Apply the dataset's series filters to one state's inventory frame."""
    s = sites.copy()
    s["parm_cd"] = s["parm_cd"].map(_norm_code)
    s = s[s["parm_cd"].isin(codes)]
    s = s[s["data_type_cd"].astype(str).str.lower().isin(services)]
    # A dv series must carry the Mean statistic; Max/Min/Median-only series
    # cannot feed a daily-mean analysis.
    if "stat_cd" in s.columns:
        is_dv = s["data_type_cd"].astype(str).str.lower() == "dv"
        stat = pd.to_numeric(s["stat_cd"], errors="coerce")
        s = s[~is_dv | (stat == DV_MEAN_STAT)]
    s["site_no"] = _site_no_series(s["site_no"], log)
    if dataset.exclude_wells:
        s = s[s["site_no"].str.len() != 15]
    # Window overlap: the series must intersect [start, end].
    s = s[(s["begin_date"].astype(str) <= end) & (s["end_date"].astype(str) >= start)]
    cnt = pd.to_numeric(s["count_nu"], errors="coerce").fillna(0)
    s = s[cnt >= dataset.min_count_per_series]
    s["state_cd"] = st
    return s


def discover_sites(dataset: Dataset, progress=None, log=None) -> dict:
    """Query NWIS inventories and populate CandidateSite rows.

    ``progress(frac, message)`` and ``log(line)`` are optional callbacks.
    Failed states are retried automatically, since NWIS often 503s under load.

    The existing site list is only replaced once at least one state has
    returned data. A total outage must not silently wipe a selection the user
    spent time building.
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

            s = _filter_inventory(sites, dataset, codes, services, start, end, st, log)
            _log(log, f"{st}: {s['site_no'].nunique()} sites with qualifying series")
            if not s.empty:
                frames.append(s)
            time.sleep(REQUEST_SLEEP_S)
        return failed

    failed_states = query_states(list(states), "Querying ")
    for wait in RETRY_ROUNDS:
        if not failed_states:
            break
        _log(
            log,
            f"Retrying {len(failed_states)} failed states in {wait}s: "
            f"{', '.join(failed_states)}",
        )
        if progress:
            progress(0.0, f"Waiting {wait}s before retrying {len(failed_states)} states")
        time.sleep(wait)
        failed_states = query_states(failed_states, "Retry ")

    if not frames:
        # Every state either failed or genuinely had nothing. Either way there
        # is no new truth to write, so leave the previous results alone.
        raise RuntimeError(
            "No state inventory returned any qualifying series. "
            + (
                f"{len(failed_states)} states failed even after retries "
                f"({', '.join(failed_states)}); NWIS may be unavailable. "
                if failed_states
                else "Check the parameter codes, services and date window. "
            )
            + "The previously discovered sites were left untouched."
        )

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
            continue  # a site must have at least one qualifying code in every group
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

    # Swap the old list for the new one atomically: a crash between the two
    # statements would otherwise leave the dataset with no sites at all.
    with transaction.atomic():
        dataset.sites.all().delete()
        CandidateSite.objects.bulk_create(rows)

    _log(
        log,
        f"Qualifying sites (present in all {len(groups)} groups): "
        f"{len(rows)} of {n_candidates} candidates",
    )
    return {
        "candidates": int(n_candidates),
        "qualifying": len(rows),
        "failed_states": failed_states,
    }


def download_dv(dataset: Dataset, progress=None, log=None, sites=None) -> dict:
    """Download daily values for the selected sites and write per-site CSVs.

    Failed batches are retried on the same schedule as discovery. ``sites``
    overrides the selected-site list for a targeted re-fetch.
    """
    if sites is None:
        sites = list(dataset.sites.filter(selected=True).values_list("site_no", flat=True))
    codes = dataset.all_pmcodes()
    start = dataset.start_date.isoformat()
    end = dataset.end_date.isoformat()

    raw = dataset.raw_dir
    raw.mkdir(parents=True, exist_ok=True)

    counts = {"ok": 0, "empty": 0}
    written: set[str] = set()

    def fetch_batches(todo: list[str], round_label: str) -> list[str]:
        failed: list[str] = []
        batches = [
            todo[i : i + DOWNLOAD_BATCH_SITES]
            for i in range(0, len(todo), DOWNLOAD_BATCH_SITES)
        ]
        done = 0
        for batch in batches:
            if progress:
                progress(
                    done / max(1, len(todo)),
                    f"{round_label}sites {done + 1} to "
                    f"{min(done + len(batch), len(todo))} of {len(todo)}",
                )
            try:
                df, _ = _nwis().get_dv(
                    sites=batch, parameterCd=codes, start=start, end=end, multi_index=False
                )
            except Exception as e:
                failed.extend(batch)
                _log(
                    log,
                    f"batch {batch[0]} to {batch[-1]}: FAILED "
                    f"({type(e).__name__}: {str(e)[:120]})",
                )
                done += len(batch)
                time.sleep(REQUEST_SLEEP_S)
                continue

            if df is None or df.empty:
                counts["empty"] += len(batch)
                _log(log, f"batch {batch[0]} to {batch[-1]}: no data")
                done += len(batch)
                time.sleep(REQUEST_SLEEP_S)
                continue

            df = df.reset_index()
            tcol = next(
                (c for c in ("datetime", "dateTime", "index") if c in df.columns), None
            )
            if tcol is None:
                # Without a time column the frame cannot be interpreted; treat
                # the batch as failed rather than aborting the whole job.
                failed.extend(batch)
                _log(
                    log,
                    f"batch {batch[0]} to {batch[-1]}: no recognizable date column "
                    f"(saw {list(df.columns)[:6]})",
                )
                done += len(batch)
                time.sleep(REQUEST_SLEEP_S)
                continue
            if tcol != "datetime":
                df = df.rename(columns={tcol: "datetime"})

            if "site_no" not in df.columns:
                if len(batch) != 1:
                    # A multi-site response with no site column cannot be split
                    # safely: attributing it to batch[0] would file one site's
                    # measurements under another site's id.
                    failed.extend(batch)
                    _log(
                        log,
                        f"batch {batch[0]} to {batch[-1]}: response omitted site_no "
                        "for a multi-site request; retrying these sites singly",
                    )
                    done += len(batch)
                    time.sleep(REQUEST_SLEEP_S)
                    continue
                df["site_no"] = batch[0]
            df["site_no"] = _site_no_series(df["site_no"], log)

            for site_no, sub in df.groupby("site_no"):
                sub = sub.dropna(axis=1, how="all")
                value_cols = [c for c in sub.columns if c not in ("datetime", "site_no")]
                if not value_cols:
                    counts["empty"] += 1
                    continue
                sub[["datetime", "site_no"] + value_cols].to_csv(
                    raw / f"usgs_{site_no}_all_obs.csv", index=False
                )
                written.add(str(site_no))
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
            progress(0.0, f"Waiting {wait}s before retrying {len(failed)} sites")
        time.sleep(wait)
        # Retry one site at a time: a batch usually fails because of a single
        # bad site, and singly-fetched frames are also unambiguous to attribute.
        previous, failed = failed, []
        for i in range(0, len(previous), 1):
            failed.extend(fetch_batches(previous[i : i + 1], "Retry "))

    if progress:
        progress(
            1.0,
            f"Downloaded {counts['ok']} sites "
            f"({counts['empty']} empty, {len(failed)} failed)",
        )
    return {
        "ok": counts["ok"],
        "empty": counts["empty"],
        "failed": failed,
        "written": sorted(written),
    }
