"""Create or refresh the built-in demo dataset from the bundled CSVs.

The demo wraps the original nitrate-research data so the app has a working
example on first launch. Its daily tables map onto the legacy ``.cache``
Parquet files, or onto the committed summary CSVs when those are absent; see
``explorer.core.cache``.

    python manage.py seed_demo

Everything the seed needs is read before anything is written, and the writes
run in one transaction. An earlier version created the Dataset row first and
then looked up parameter codes, so a missing catalog left behind a demo with no
groups that the caller would never retry, because the row already existed.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from datasets.catalog import EXAMPLE_GROUPS, pmcode_info
from datasets.models import CandidateSite, Dataset, ParameterGroup

DEMO_SLUG = "nitrate-research-demo"


def seed_demo_dataset() -> Dataset:
    # Read every input first: the parameter catalog and both summary CSVs.
    # Any of these can fail, and none of them should leave a partial dataset.
    group_specs = [
        {
            "label": g["label"],
            "pmcodes": pmcode_info(g["codes"]),
            "require_canonical": bool(g.get("require_canonical")),
        }
        for g in EXAMPLE_GROUPS
    ]
    merged = pd.read_csv(settings.DATA_DIR / "merged_site_data.csv", dtype={"site_no": str})
    do_med = pd.read_csv(settings.DATA_DIR / "site_median_do.csv", dtype={"site_no": str})

    with transaction.atomic():
        return _write_demo(group_specs, merged, do_med)


def _write_demo(group_specs, merged, do_med) -> Dataset:
    ds, _created = Dataset.objects.update_or_create(
        slug=DEMO_SLUG,
        defaults=dict(
            name="Nitrate research (demo)",
            status=Dataset.STATUS_READY,
            start_date=dt.date.fromisoformat(settings.DATE_START),
            end_date=dt.date.fromisoformat(settings.DATE_END),
            states=[],
            services=["dv"],
            exclude_wells=True,
            is_demo=True,
            # Two quirks of the original study, reproduced so the demo's
            # numbers match its published figures exactly:
            #   pair (1,3): DO is paired against the flow-gated NO3 series
            #   pair (1,2): flow (g2) is passed as X to the k-NN MI estimator
            pairing_gates={"1,3": {"gate": 2}, "1,2": {"x": 2}},
        ),
    )

    ds.groups.all().delete()
    for pos, g in enumerate(group_specs, start=1):
        ParameterGroup.objects.create(dataset=ds, position=pos, **g)

    # Candidate sites come from the committed summary CSVs: everything in the
    # merged table, plus the dissolved-oxygen-only sites.
    do_sites = set(do_med["site_no"].astype(str))

    ds.sites.all().delete()
    seen: set[str] = set()
    rows = []
    for _, r in merged.iterrows():
        sid = str(r["site_no"])
        seen.add(sid)
        cov = {"1": ["*"], "2": ["*"]}
        if sid in do_sites:
            cov["3"] = ["*"]
        rows.append(
            CandidateSite(
                dataset=ds,
                site_no=sid,
                station_nm=str(r.get("station_nm") or ""),
                dec_lat_va=r.get("dec_lat_va"),
                dec_long_va=r.get("dec_long_va"),
                huc_cd=str(r.get("huc2") or "").split(".")[0].zfill(2) if pd.notna(r.get("huc2")) else "",
                group_coverage=cov,
                selected=True,
            )
        )
    for _, r in do_med.iterrows():
        sid = str(r["site_no"])
        if sid in seen:
            continue
        rows.append(
            CandidateSite(
                dataset=ds,
                site_no=sid,
                station_nm=str(r.get("station_nm") or ""),
                dec_lat_va=r.get("dec_lat_va"),
                dec_long_va=r.get("dec_long_va"),
                group_coverage={"3": ["*"]},
                selected=True,
            )
        )
    CandidateSite.objects.bulk_create(rows)
    return ds


class Command(BaseCommand):
    help = "Create or refresh the built-in demo dataset from bundled CSVs."

    def handle(self, *args, **options):
        ds = seed_demo_dataset()
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo dataset '{ds.slug}' ready: "
                f"{ds.groups.count()} groups, {ds.sites.count()} sites."
            )
        )
