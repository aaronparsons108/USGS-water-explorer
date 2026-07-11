# USGS Site Explorer

A Django web app for **end-to-end USGS water-data research — no coding required**:

1. **Define parameter groups** (e.g. Group 1 = nitrate/nitrite codes, Group 2 =
   streamflow, Group 3 = dissolved oxygen) with a searchable USGS parameter-code
   picker (19k+ codes, offline snapshot included).
2. **Discover sites** — state-by-state NWIS inventory queries keep only sites that
   have data in **every** group (filter by data service, date window, wells,
   minimum observations; deselect sites you don't want).
3. **Download daily values** via [`dataretrieval`](https://github.com/DOI-USGS/dataretrieval-python)
   with live progress, automatic **unit normalization** inside each group (e.g.
   lb/day and tons/day nitrogen loads → mg/L via daily streamflow) and an honest
   unit report — nothing is silently mixed.
4. **Explore** — interactive CONUS map, scatterplots, and a sortable table of
   per-site **medians** and pairwise **mutual information** between your groups,
   recomputed on the fly for any date range, season, or month. PNG + CSV downloads.

A bundled **demo dataset** (the original nitrate/streamflow/dissolved-oxygen
research this tool grew out of, 169 CONUS sites) works out of the box.

## Quick start

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open **http://127.0.0.1:8000/** → the demo dataset is ready to explore; click
**+ New extraction** to start your own.

## How an extraction works

| Step | What happens |
|---|---|
| 1 · Setup | Name, date window, states (All-CONUS shortcut), data-service filters, 2–5 parameter groups. "Load example" fills the nitrate-research config. |
| 2 · Discover | One NWIS inventory query per state (background job, live log). A site qualifies with ≥1 series matching your filters in **every** group. Review the coverage table + map, deselect sites. |
| 3 · Download | Daily values fetched in small batches → per-site CSVs under `datasets_store/<slug>/raw/` → per-group daily Parquet tables → unit report. |
| 4 · Explore | Filters (date/season/month, region, HUC2, site search, value/MI ranges, min observation counts), map + scatter with region or metric-gradient coloring, presets, log axes. |

Every metric is derived from the per-group daily tables at request time, so
date-range and season filters return **freshly recomputed medians and MI**
(scikit-learn k-NN estimator, nats) in well under a second.

Notes:
- Only **daily values (dv)** are downloaded; other services (uv, qw, …) act as
  site filters. USGS retired the qw download endpoint in March 2024.
- HUC2 regions come from the NWIS inventory (`huc_cd`) — no shapefiles needed.
- Delete a dataset from the list page; its downloads are removed with it.

## The demo dataset & research parity

`data/` ships small summary CSVs from the original
[nitro-research](../nitro-research) study. The demo's full-window metrics match
those research exports to floating-point precision (median streamflow, median
NO3+NO2 mg/L-as-N, median DO, MI(flow, NO3+NO2), MI(NO3+NO2, DO)) — including two
research quirks reproduced via per-pair rules (`Dataset.pairing_gates`).

To enable date/season recompute for the demo, point `NITRO_DATA_ROOT` at a
nitro-research checkout (with `sitedata/`) and run `python manage.py build_cache`.
Without it the demo serves full-window values from the committed CSVs.

## Layout

```
config/            Django project (settings, urls)
datasets/          extraction wizard: models, NWIS client, units, builder,
                   background jobs, wizard pages (list/setup/sites/download)
explorer/          analysis UI: dataset-aware metrics/cache/figures (Plotly),
                   filter form, map/scatter/table endpoints
data/              committed: demo summary CSVs + USGS parameter-code snapshot
datasets_store/    per-dataset downloads + daily tables (gitignored)
.cache/            demo daily tables + parameter-code cache (gitignored)
```

## Dependencies

Django, pandas, numpy, scikit-learn (mutual information), plotly + kaleido
(interactive figures / PNG export), pyarrow (Parquet), dataretrieval ≥ 1.2
(NWIS + waterdata APIs). See `requirements.txt`.
