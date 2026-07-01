"""Parse the raw research1 sitedata into the explorer's Parquet daily caches.

Run once (and whenever the raw data changes):

    python manage.py build_cache

Requires NITRO_DATA_ROOT to point at a nitro-research checkout containing
sitedata/. After this, the date-range and season filters are enabled.
"""

from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from explorer.core import cache


class Command(BaseCommand):
    help = "Parse raw sitedata into Parquet daily caches (flow, NO3+NO2, DO)."

    def handle(self, *args, **options):
        if not cache.raw_sitedata_available():
            raise CommandError(
                f"Raw sitedata not found at {settings.SITEDATA_DIR}.\n"
                "Set NITRO_DATA_ROOT to your nitro-research checkout, e.g.\n"
                '  PowerShell:  $env:NITRO_DATA_ROOT = "C:\\path\\to\\nitro-research"\n'
                "  bash:        export NITRO_DATA_ROOT=/c/path/to/nitro-research"
            )

        self.stdout.write(
            f"Parsing sitedata under {settings.SITEDATA_DIR} "
            f"({settings.DATE_START} .. {settings.DATE_END}) ..."
        )
        t0 = time.perf_counter()
        stats = cache.build_caches()
        dt = time.perf_counter() - t0

        self.stdout.write(self.style.SUCCESS(f"Built caches in {dt:.1f}s -> {settings.CACHE_DIR}"))
        for k, v in stats.items():
            self.stdout.write(f"  {k}: {v}")
