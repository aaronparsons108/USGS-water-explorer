# Nitro Research Explorer

A Django web frontend for exploring USGS daily-value metrics — **median streamflow
(00060)**, **median NO3+NO2 (mg/L as N)**, **median dissolved oxygen (00300)**, and the
**mutual information** between (streamflow, NO3+NO2) and (NO3+NO2, dissolved oxygen) —
across qualifying sites. Type filter values into a form, press **Apply filters**, and get
a filtered data table plus an interactive CONUS bubble map and scatterplot. Every figure
can be downloaded as a PNG and the table as CSV.

This is the interactive companion to the script-based analysis in the sibling
`nitro-research` repo; the metric logic here is a faithful port of that repo's
`nitro` / `dissolved_oxygen` packages (see *Parity* below).

## How it works

The heavy raw data (≈436 MB, 756 CSVs) never gets committed. Instead:

1. **`python manage.py build_cache`** parses the raw sitedata **once** into three small
   Parquet tables of per-day, per-site values (flow, NO3+NO2, DO) under `.cache/`.
2. Each filter request slices those cached tables by date/season **in memory** and
   recomputes medians + mutual information — so date-range and season filters return
   correct, freshly-derived numbers in well under a second.
3. Site metadata (coordinates, station name, region, HUC2) comes from the small
   committed CSVs in `data/`, so no cartopy/geopandas is needed at runtime.

**Offline fallback:** if the raw data / cache aren't present, the app serves the
full-window numbers straight from the committed `data/` CSVs. Location, value, and MI
filters still work; date/season filters are disabled with an on-screen banner.

## Setup

```bash
pip install -r requirements.txt
python manage.py migrate            # first run only (Django's own tables)
```

Point the app at your `nitro-research` checkout (the one with `sitedata/`). Only needed
for recompute / building the cache:

```bash
# PowerShell
$env:NITRO_DATA_ROOT = "C:\path\to\nitro-research"
# bash
export NITRO_DATA_ROOT=/c/path/to/nitro-research
```

If unset, it defaults to `../nitro-research` next to this repo.

Build the cache (enables date/season recompute), then run the server:

```bash
python manage.py build_cache        # ~1-2 min; prints row/site counts
python manage.py runserver
```

Open **http://127.0.0.1:8000/** (the explorer is also at `/explorer/`).

## Filters

- **Time window** — start/end date, meteorological season (spring/summer/fall/winter),
  or a single calendar month. Recomputes all medians & MI over just those days.
  `Min paired days for MI` sets the minimum overlapping observations required to
  estimate a mutual-information value (default 30).
- **Location** — region (Florida / Mid Atlantic / Midwest / Big Midwest cluster /
  Other), HUC2 region, and a free-text site number / station name search.
- **Value & MI ranges** — min/max on each median and MI metric, plus minimum
  observation-count thresholds.
- **Charts** — map color (region or any metric), scatter X/Y axes (any metric),
  log axes, and one-click presets (log E(Q) vs MI; NO3+NO2 vs DO; E(Q) vs E(C)).

## Layout

```
config/            Django project (settings, urls)
explorer/
  core/            vendored compute: conversions, loader, metrics, cache,
                   metadata, filters, service, figures (Plotly)
  management/commands/build_cache.py
  forms.py views.py urls.py
  templates/ static/
data/              committed summary CSVs (metadata + offline fallback)
.cache/            Parquet daily tables (gitignored; built by build_cache)
```

## Parity with nitro-research

Full-window recompute matches the research1 exports to floating-point precision:

| metric | vs source | max abs diff |
|---|---|---|
| median streamflow | `merged_site_data.csv` | 0 |
| median NO3+NO2 | `merged_site_data.csv` | 9e-16 |
| MI(flow, NO3+NO2) | `merged_site_data.csv` | 1e-16 |
| median DO | `site_median_do.csv` | 0 |
| MI(NO3+NO2, DO) | `sites_mutual_information_no3_do.csv` | 2e-16 |

To refresh the committed metadata, re-copy the three CSVs from `nitro-research`
(`qualifying_sites_map_export/merged_site_data.csv`,
`dissolved_oxygen/site_median_do.csv`,
`dissolved_oxygen/sites_mutual_information_no3_do.csv`) into `data/`, then rerun
`build_cache`.

## Dependencies

Django, pandas, numpy, scikit-learn (MI), plotly + kaleido (interactive figures and PNG
export), pyarrow (Parquet). See `requirements.txt`.
