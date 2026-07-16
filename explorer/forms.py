"""The explorer filter form, built dynamically from a dataset's metric schema."""

from __future__ import annotations

from django import forms

from .core.metadata import load_dataset_metadata
from .core.seasons import CALENDAR_MONTHS
from .core.regions import REGION_ORDER

SEASON_CHOICES = [
    ("", "(any season)"),
    ("spring", "Spring (Mar-May)"),
    ("summer", "Summer (Jun-Aug)"),
    ("fall", "Fall (Sep-Nov)"),
    ("winter", "Winter (Dec-Feb)"),
]
MONTH_CHOICES = [("", "(any month)")] + [(slug, slug.title()) for slug, _ in CALENDAR_MONTHS]
REGION_CHOICES = [(r, r) for r in REGION_ORDER]


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
    # Checkboxes so options toggle on/off individually (a multi-select list
    # required ctrl-click and made deselection unclear).
    huc2 = forms.MultipleChoiceField(
        required=False, choices=[], widget=forms.CheckboxSelectMultiple
    )
    site_query = forms.CharField(required=False, max_length=120)

    # --- visualization controls (choices filled per dataset) ---
    scatter_x = forms.ChoiceField(required=False, choices=[])
    scatter_y = forms.ChoiceField(required=False, choices=[])
    log_x = forms.BooleanField(required=False, initial=True)
    log_y = forms.BooleanField(required=False, initial=False)
    scatter_color = forms.ChoiceField(required=False, choices=[])
    map_color = forms.ChoiceField(required=False, choices=[])

    def __init__(self, dataset, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dataset = dataset
        self.schema = dataset.metric_schema()
        labels = self.schema["labels"]

        # Value/MI range metrics + count thresholds from the schema.
        self.range_metrics = (
            self.schema["medians"] + self.schema["mis"] + self.schema.get("nmis", [])
        )
        self.count_cols = [
            c for c in self.schema["numeric"] if c.startswith(("n_g", "n_paired_"))
        ]
        for col in self.range_metrics:
            self.fields[f"{col}__min"] = forms.FloatField(required=False)
            self.fields[f"{col}__max"] = forms.FloatField(required=False)
        for col in self.count_cols:
            self.fields[f"{col}__min"] = forms.IntegerField(required=False, min_value=0)

        axis_choices = [(c, labels.get(c, c)) for c in self.schema["numeric"]]
        color_choices = [("location_type", "Region")] + [
            (c, labels.get(c, c)) for c in self.range_metrics
        ]
        self.fields["scatter_x"].choices = axis_choices
        self.fields["scatter_y"].choices = axis_choices
        self.fields["scatter_color"].choices = color_choices
        self.fields["map_color"].choices = color_choices

        self._default_x = self.schema["medians"][0] if self.schema["medians"] else ""
        self._default_y = (
            self.schema["mis"][0]
            if self.schema["mis"]
            else (self.schema["medians"][-1] if self.schema["medians"] else "")
        )
        self.fields["scatter_x"].initial = self._default_x
        self.fields["scatter_y"].initial = self._default_y
        self.fields["scatter_color"].initial = "location_type"
        self.fields["map_color"].initial = "location_type"

        # HUC2 choices from whatever metadata this dataset has.
        meta = load_dataset_metadata(dataset)
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
        name_map: dict[str, str] = {}
        if "huc2_region_name" in meta.columns:
            for _, r in meta.dropna(subset=["huc2"]).iterrows():
                nm = r.get("huc2_region_name")
                if nm is not None and str(nm) not in ("nan", "<NA>"):
                    name_map.setdefault(str(r["huc2"]), str(nm))
        self.fields["huc2"].choices = [
            (h, f"{h} - {name_map[h]}" if name_map.get(h) else h) for h in huc_vals
        ]

    # --- accessors the views use ---
    def ranges(self) -> dict:
        cd = self.cleaned_data
        out: dict[str, tuple] = {}
        for col in self.range_metrics:
            lo, hi = cd.get(f"{col}__min"), cd.get(f"{col}__max")
            if lo is not None or hi is not None:
                out[col] = (lo, hi)
        for col in self.count_cols:
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
            "scatter_x": cd.get("scatter_x") or self._default_x,
            "scatter_y": cd.get("scatter_y") or self._default_y,
            "log_x": bool(cd.get("log_x")),
            "log_y": bool(cd.get("log_y")),
            "scatter_color": cd.get("scatter_color") or "location_type",
            "map_color": cd.get("map_color") or "location_type",
        }
