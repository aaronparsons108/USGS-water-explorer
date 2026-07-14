"""Dataset models: an extraction is a Dataset with ParameterGroups, discovered
CandidateSites, and background Jobs.

Metric naming convention (used by the builder, metrics, and explorer):
  median_g<pos>, n_g<pos>            per-group median / observation days
  mi_g<i>_g<j>, n_paired_g<i>_g<j>   pairwise mutual information (i < j)
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Dataset(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_DISCOVERING = "discovering"
    STATUS_SITES_READY = "sites_ready"
    STATUS_DOWNLOADING = "downloading"
    STATUS_READY = "ready"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_DISCOVERING, "Discovering sites"),
        (STATUS_SITES_READY, "Sites ready"),
        (STATUS_DOWNLOADING, "Downloading"),
        (STATUS_READY, "Ready"),
        (STATUS_ERROR, "Error"),
    ]

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    start_date = models.DateField()
    end_date = models.DateField()
    # State codes for discovery, e.g. ["DE", "MD"]. Empty = all CONUS.
    states = models.JSONField(default=list)
    # data_type_cd values a site series must have to count in discovery.
    services = models.JSONField(default=list)  # e.g. ["dv"]
    exclude_wells = models.BooleanField(default=True)  # drop 15-digit site ids
    min_count_per_series = models.PositiveIntegerField(default=1)

    is_demo = models.BooleanField(default=False)
    error_message = models.TextField(blank=True, default="")
    # Unit-normalization report from the build step: list of dicts
    # {"group": pos, "code": ..., "action": "kept|converted|excluded", "detail": ...}
    unit_report = models.JSONField(default=list, blank=True)
    # Demo-parity quirk: {"i,j": gate_pos} — when pairing groups i & j for MI,
    # first restrict group i's days to those also paired with group gate_pos.
    # Research1 paired DO against the flow-gated NO3 series; new datasets: {}.
    pairing_gates = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "dataset"
            slug, n = base, 2
            while Dataset.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    # --- storage ---
    @property
    def store_dir(self) -> Path:
        return Path(settings.DATASETS_STORE_DIR) / self.slug

    @property
    def raw_dir(self) -> Path:
        return self.store_dir / "raw"

    def daily_parquet(self, position: int) -> Path:
        return self.store_dir / f"daily_g{position}.parquet"

    # --- schema ---
    def groups_ordered(self):
        return list(self.groups.order_by("position"))

    def all_pmcodes(self) -> list[str]:
        codes: list[str] = []
        for g in self.groups_ordered():
            codes.extend(p["code"] for p in g.pmcodes)
        return sorted(set(codes))

    def metric_schema(self) -> dict:
        """Column names + labels derived from this dataset's groups.

        Returns {"columns": [...], "labels": {col: label}, "numeric": [...],
                 "medians": [...], "mis": [...], "pairs": [(i, j), ...]}.
        """
        groups = self.groups_ordered()
        labels: dict[str, str] = {}
        medians, counts, mis, paired = [], [], [], []
        for g in groups:
            unit = g.display_unit()
            med, cnt = f"median_g{g.position}", f"n_g{g.position}"
            medians.append(med)
            counts.append(cnt)
            labels[med] = f"Median {g.label}" + (f" ({unit})" if unit else "")
            labels[cnt] = f"# {g.label} days"
        pairs = list(combinations([g.position for g in groups], 2))
        by_pos = {g.position: g for g in groups}
        for i, j in pairs:
            mi, np_ = f"mi_g{i}_g{j}", f"n_paired_g{i}_g{j}"
            mis.append(mi)
            paired.append(np_)
            labels[mi] = f"MI({by_pos[i].label}; {by_pos[j].label}) (nats)"
            labels[np_] = f"# paired days ({by_pos[i].label}, {by_pos[j].label})"
        numeric = medians + mis + counts + paired
        meta_cols = [
            "site_no", "station_nm", "location_type", "huc2", "huc2_region_name",
            "dec_lat_va", "dec_long_va",
        ]
        columns = meta_cols + medians + counts + mis + paired
        return {
            "columns": columns,
            "labels": labels,
            "numeric": numeric,
            "medians": medians,
            "mis": mis,
            "pairs": pairs,
        }


class ParameterGroup(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="groups")
    position = models.PositiveSmallIntegerField()  # 1..5
    label = models.CharField(max_length=80)
    # [{"code": "99133", "name": "NO3+NO2,water,insitu", "unit": "mg/l as N"}, ...]
    pmcodes = models.JSONField(default=list)
    # Only count/use primary (unlabeled) series for this group. NWIS marks
    # auxiliary series via loc_web_ds ("index velocity", "dam tailwater", ...),
    # which download as "<code>_<label>_Mean" columns. Strict is right for e.g.
    # streamflow; permissive groups also accept sensor-labeled variants
    # ("suna", "corrected nitrate", intake locations).
    require_canonical = models.BooleanField(default=False)

    class Meta:
        ordering = ["position"]
        unique_together = [("dataset", "position")]

    def __str__(self) -> str:
        return f"{self.dataset.slug} g{self.position} {self.label}"

    def codes(self) -> list[str]:
        return [p["code"] for p in self.pmcodes]

    def display_unit(self) -> str:
        """Most common unit among member codes (the group's target unit)."""
        units = [str(p.get("unit") or "").strip() for p in self.pmcodes]
        units = [u for u in units if u]
        if not units:
            return ""
        return max(set(units), key=units.count)


class CandidateSite(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="sites")
    site_no = models.CharField(max_length=24)
    station_nm = models.CharField(max_length=200, blank=True, default="")
    state_cd = models.CharField(max_length=4, blank=True, default="")
    site_tp_cd = models.CharField(max_length=12, blank=True, default="")
    dec_lat_va = models.FloatField(null=True, blank=True)
    dec_long_va = models.FloatField(null=True, blank=True)
    huc_cd = models.CharField(max_length=16, blank=True, default="")
    # {"1": ["99133"], "2": ["00060"], ...} codes with qualifying series per group
    group_coverage = models.JSONField(default=dict)
    begin_date = models.CharField(max_length=12, blank=True, default="")
    end_date = models.CharField(max_length=12, blank=True, default="")
    total_count = models.PositiveIntegerField(default=0)
    selected = models.BooleanField(default=True)

    class Meta:
        ordering = ["site_no"]
        unique_together = [("dataset", "site_no")]

    @property
    def huc2(self) -> str:
        h = (self.huc_cd or "").strip()
        return h[:2] if len(h) >= 2 else ""


class Job(models.Model):
    KIND_DISCOVER = "discover"
    KIND_DOWNLOAD = "download"
    KIND_CHOICES = [(KIND_DISCOVER, "Discover sites"), (KIND_DOWNLOAD, "Download data")]

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_DONE, "Done"),
        (STATUS_ERROR, "Error"),
    ]

    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="jobs")
    kind = models.CharField(max_length=12, choices=KIND_CHOICES)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    progress = models.FloatField(default=0.0)  # 0..1
    message = models.CharField(max_length=300, blank=True, default="")
    log = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def append_log(self, line: str) -> None:
        self.log = (self.log + "\n" + line).strip()
