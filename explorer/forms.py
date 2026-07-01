"""The filter form: dates, season/month, location, value/MI ranges, and the
scatter axis / map color selectors."""

from __future__ import annotations

from django import forms

from .core.metadata import load_site_metadata
from .core.seasons import CALENDAR_MONTHS
from .core.regions import REGION_ORDER
from .core.service import METRIC_LABELS, NUMERIC_COLUMNS

# Metrics that get a (min, max) range pair.
RANGE_METRICS = [
    "median_00060_Mean",
    "median_no3no2",
    "median_do_mg_l",
    "mutual_information_flow_no3",
    "mutual_information_no3_do",
]
# Observation-count columns that get a min-only threshold.
COUNT_COLS = [
    "n_flow_obs",
    "n_combined_days",
    "n_do_days",
    "n_paired_days_flow_no3",
    "n_paired_days_no3_do",
]

SEASON_CHOICES = [
    ("", "(any season)"),
    ("spring", "Spring (Mar-May)"),
    ("summer", "Summer (Jun-Aug)"),
    ("fall", "Fall (Sep-Nov)"),
    ("winter", "Winter (Dec-Feb)"),
]
MONTH_CHOICES = [("", "(any month)")] + [(slug, slug.title()) for slug, _ in CALENDAR_MONTHS]
REGION_CHOICES = [(r, r) for r in REGION_ORDER]
AXIS_CHOICES = [(c, METRIC_LABELS.get(c, c)) for c in NUMERIC_COLUMNS]
MAP_COLOR_CHOICES = [("location_type", "Region")] + [
    (c, METRIC_LABELS[c]) for c in RANGE_METRICS
]


class FilterForm(forms.Form):
    # --- time window (recompute) ---
    start_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    season = forms.ChoiceField(required=False, choices=SEASON_CHOICES)
    month = forms.ChoiceField(required=False, choices=MONTH_CHOICES)
    min_paired_days = forms.IntegerField(required=False, min_value=4, initial=30)

    # --- location ---
    regions = forms.MultipleChoiceField(
        required=False, choices=REGION_CHOICES, widget=forms.CheckboxSelectMultiple
    )
    huc2 = forms.MultipleChoiceField(required=False, choices=[])  # populated in __init__
    site_query = forms.CharField(required=False, max_length=120)

    # --- visualization controls ---
    scatter_x = forms.ChoiceField(required=False, choices=AXIS_CHOICES, initial="median_00060_Mean")
    scatter_y = forms.ChoiceField(
        required=False, choices=AXIS_CHOICES, initial="mutual_information_flow_no3"
    )
    log_x = forms.BooleanField(required=False, initial=True)
    log_y = forms.BooleanField(required=False, initial=False)
    scatter_color = forms.ChoiceField(
        required=False, choices=MAP_COLOR_CHOICES, initial="location_type"
    )
    map_color = forms.ChoiceField(required=False, choices=MAP_COLOR_CHOICES, initial="location_type")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # HUC2 choices come from whatever metadata is available.
        meta = load_site_metadata()
        huc_vals = (
            sorted(
                {
                    str(h)
                    for h in meta["huc2"].dropna().tolist()
                    if str(h).strip() not in ("", "nan", "<NA>")
                }
            )
            if "huc2" in meta.columns
            else []
        )
        name_map = {}
        if "huc2_region_name" in meta.columns:
            for _, r in meta.dropna(subset=["huc2"]).iterrows():
                name_map.setdefault(str(r["huc2"]), str(r.get("huc2_region_name") or ""))
        self.fields["huc2"].choices = [
            (h, f"{h} - {name_map.get(h)}" if name_map.get(h) else h) for h in huc_vals
        ]

        # Range fields, added dynamically so the template can iterate them.
        for col in RANGE_METRICS:
            self.fields[f"{col}__min"] = forms.FloatField(required=False)
            self.fields[f"{col}__max"] = forms.FloatField(required=False)
        for col in COUNT_COLS:
            self.fields[f"{col}__min"] = forms.IntegerField(required=False, min_value=0)

    # --- accessors the view uses to build service / figure kwargs ---
    def ranges(self) -> dict:
        cd = self.cleaned_data
        out: dict[str, tuple] = {}
        for col in RANGE_METRICS:
            lo, hi = cd.get(f"{col}__min"), cd.get(f"{col}__max")
            if lo is not None or hi is not None:
                out[col] = (lo, hi)
        for col in COUNT_COLS:
            lo = cd.get(f"{col}__min")
            if lo is not None:
                out[col] = (lo, None)
        return out

    def service_kwargs(self) -> dict:
        cd = self.cleaned_data
        return {
            "start": cd.get("start_date").isoformat() if cd.get("start_date") else None,
            "end": cd.get("end_date").isoformat() if cd.get("end_date") else None,
            "season": cd.get("season") or None,
            "month": cd.get("month") or None,
            "min_paired_days": cd.get("min_paired_days") or 30,
            "regions": cd.get("regions") or None,
            "huc2s": cd.get("huc2") or None,
            "site_query": cd.get("site_query") or None,
            "ranges": self.ranges(),
        }

    def figure_kwargs(self) -> dict:
        cd = self.cleaned_data
        return {
            "scatter_x": cd.get("scatter_x") or "median_00060_Mean",
            "scatter_y": cd.get("scatter_y") or "mutual_information_flow_no3",
            "log_x": bool(cd.get("log_x")),
            "log_y": bool(cd.get("log_y")),
            "scatter_color": cd.get("scatter_color") or "location_type",
            "map_color": cd.get("map_color") or "location_type",
        }
