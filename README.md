# USGS Site Explorer

A Django app for end-to-end USGS water-data research, with no coding required.

The question it exists to answer is: **across the U.S., how strongly does one
water-quality parameter track another, and where?** Correlation is the wrong
tool for that, because the relationships are often nonlinear. This app measures
**mutual information** instead, per site, and lets you slice it by time window,
season, month, region and basin.

## The four steps

1. **Define parameter groups.** For example group 1 = nitrate/nitrite codes,
   group 2 = streamflow, group 3 = dissolved oxygen. A searchable picker covers
   19,000+ USGS parameter codes from an offline snapshot.
2. **Discover sites.** One NWIS inventory query per state, keeping only sites
   with data in **every** group. Filter the results by state, basin, record
   length or observation count, then choose which sites to keep.
3. **Download daily values** through
   [`dataretrieval`](https://github.com/DOI-USGS/dataretrieval-python), with
   live progress, automatic **unit normalization** inside each group (lb/day and
   tons/day nitrogen loads become mg/L via daily streamflow) and an honest unit
   report. Nothing is silently mixed.
4. **Explore.** Per-site **medians**, pairwise **mutual information**, and
   **normalized MI** `I(A;B)/H(A)`, all recomputed on the fly for any date
   range, season or month. An interactive Plotly map and scatter, a sortable
   table, and PNG and CSV downloads throughout.

A bundled **demo dataset** (the original nitrate / streamflow / dissolved-oxygen
research this tool grew out of, 169 CONUS sites) works out of the box.

## Quick start

Requires Python 3.12 or newer. Tested on 3.13 (Windows) and 3.14 (Linux).

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Open <http://127.0.0.1:8000/>. `seed_demo` builds the **Nitrate research
(demo)** dataset from the bundled CSVs: 169 CONUS sites across three parameter
groups, ready to explore. Click **New extraction** to build your own.

## How an extraction works

| Step | What happens |
|---|---|
| 1. Setup | Name, date window, states (with an all-CONUS shortcut), data-service filters, and 2 to 5 parameter groups. "Load nitrate-research example" fills in the study's configuration. |
| 2. Discover | One NWIS inventory query per state, run as a background job with a live log. A site qualifies when it has at least one matching series in **every** group. Review the coverage table and map, filter, and pick your sites. |
| 3. Download | Daily values fetched in small batches into per-site CSVs under `datasets_store/<slug>/raw/`, then combined into one daily Parquet table per group, plus a unit report. |
| 4. Explore | Filter by date, season, month, region, HUC2, site search, metric ranges and minimum observation counts. Every active filter appears as a removable chip above the results. |

Every metric is derived from the per-group daily tables at request time, so a
date-range or season change returns **freshly recomputed** values in well under
a second.

### The two dependence measures

Both are reported for every pair of groups, because they answer different
questions:

- **Mutual information** (`mi_g<i>_g<j>`), in nats, from scikit-learn's k-NN
  `mutual_info_regression`. Sensitive to nonlinear structure that Pearson's r
  misses, but unbounded above, so values are hard to compare across sites with
  very different variability.
- **Normalized MI** (`nmi_g<i>_g<j>`), the binned uncertainty coefficient
  `I(A;B)/H(A)`, bounded in [0, 1] and read as "the fraction of A's uncertainty
  that B explains". Both numerator and denominator use one self-consistent
  Freedman-Diaconis histogram, which is what keeps the ratio in range.

Any metric can drive the map color or either scatter axis.

Notes:

- Only **daily values (dv)** are downloaded. Other services (uv, qw and the
  rest) act purely as site filters. USGS retired the qw download endpoint in
  March 2024.
- HUC2 regions come from the NWIS inventory (`huc_cd`), so no shapefiles are
  needed.
- Deleting a dataset from the list page removes its downloads with it.

## The demo dataset and research parity

`data/` ships small summary CSVs from the original nitrate study. The demo's
full-window metrics match those exports to floating-point precision (median
streamflow, median NO3+NO2 as mg/L-N, median DO, MI(flow, NO3+NO2) and
MI(NO3+NO2, DO)), including two quirks of the original analysis reproduced
through per-pair rules in `Dataset.pairing_gates`.

The demo's daily tables ship with the repo (`.cache/*.parquet`, 5.4 MB), so
date, season and month recompute work as soon as `seed_demo` has run. To
rebuild them from the original research data, point `NITRO_DATA_ROOT` at a
nitro-research checkout containing `sitedata/` and run
`python manage.py build_cache`. Without those tables the demo still renders,
serving full-window values from the committed CSVs and labelling the affected
controls **inactive** in the results banner rather than returning numbers the
filters did not actually produce.

## Layout

```
config/            Django project (settings, urls)
datasets/          extraction wizard: models, NWIS client, unit planner,
                   daily-table builder, background jobs, wizard pages
explorer/          analysis UI: filter form, results/CSV/PNG endpoints
  core/            dataset-aware metrics, caching, Plotly figures, filters
  static/explorer/ theme.js (theme), charts.js (one Plotly styling path),
                   app.js (explorer page), app.css (shared design tokens)
data/              committed: demo summary CSVs + USGS parameter-code snapshot
datasets_store/    per-dataset downloads + daily tables (gitignored)
.cache/            demo daily tables (committed) + parameter-code cache
```

`explorer/static/explorer/app.css` holds the design tokens for the whole app,
wizard included. `charts.js` reads those same tokens at runtime, so figures and
page chrome cannot drift apart, and both follow the light/dark toggle.

## Dependencies

Django, pandas, numpy, scikit-learn (mutual information), plotly with kaleido
(interactive figures and PNG export), pyarrow (Parquet), and dataretrieval 1.2+
(NWIS and waterdata APIs). See `requirements.txt`.

## License

MIT. See [LICENSE](LICENSE).
