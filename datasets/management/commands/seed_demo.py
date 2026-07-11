"""Create (or refresh) the built-in demo dataset from the bundled CSVs.

The demo wraps the original nitro-research data so the app shows a working
example on first launch. Its daily tables map to the legacy ``.cache`` parquet
files (or the committed summary CSVs when those are absent) — see
``explorer.core.cache``.

    python manage.py seed_demo
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand

from datasets.catalog import EXAMPLE_GROUPS, pmcode_info
from datasets.models import CandidateSite, Dataset, ParameterGroup

DEMO_SLUG = "nitrate-research-demo"


def seed_demo_dataset() -> Dataset:
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
            # Research1 quirks, reproduced for exact parity:
            #  - pair (1,3): DO paired against the flow-gated NO3 series (gate=2)
            #  - pair (1,2): flow (g2) passed as X to the kNN MI estimator
            pairing_gates={"1,3": {"gate": 2}, "1,2": {"x": 2}},
        ),
    )

    ds.groups.all().delete()
    for pos, g in enumerate(EXAMPLE_GROUPS, start=1):
        ParameterGroup.objects.create(
            dataset=ds, position=pos, label=g["label"], pmcodes=pmcode_info(g["codes"])
        )

    # Candidate sites from the committed summary CSVs (merged + DO-only sites).
    merged = pd.read_csv(settings.DATA_DIR / "merged_site_data.csv", dtype={"site_no": str})
    do_med = pd.read_csv(settings.DATA_DIR / "site_median_do.csv", dtype={"site_no": str})
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
