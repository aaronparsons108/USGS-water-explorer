"""The explorer filter form, built dynamically from a dataset's metric schema.

Every control the UI offers is declared here, so the sidebar, the JSON results
endpoint and the CSV/PNG downloads can never drift apart: they all go through
one validated form.

Choices are narrowed to what the dataset actually contains. Offering a region
or a HUC2 that no site belongs to just invites a user to filter their way to an
empty table and wonder what they did wrong.
"""

from __future__ import annotations

from django import forms

from .core.figures import SCALE_AUTO, SCALE_LINEAR, SCALE_LOG
from .core.metadata import load_dataset_metadata
from .core.palettes import DEFAULT_PALETTE, PALETTE_CHOICES
from .core.regions import REGION_ORDER
from .core.seasons import CALENDAR_MONTHS

SEASON_CHOICES = [
    ("", "Any season"),
    ("spring", "Spring (Mar to May)"),
    ("summer", "Summer (Jun to Aug)"),
    ("fall", "Fall (Sep to Nov)"),
    ("winter", "Winter (Dec to Feb)"),
]
MONTH_CHOICES = [("", "Any month")] + [(slug, slug.title()) for slug, _ in CALENDAR_MONTHS]

DEFAULT_MIN_PAIRED_DAYS = 30

COLOR_SCALE_CHOICES = [
    (SCALE_AUTO, "Auto (log for wide-ranging values)"),
    (SCALE_LINEAR, "Linear"),
    (SCALE_LOG, "Log"),
]

# Groupings used to lay out the range filters in the sidebar.
GROUP_VALUES = "values"
GROUP_MI = "mi"
GROUP_NMI = "nmi"
GROUP_COUNTS = "counts"


class FilterForm(forms.Form):
    # --- time window (drives recompute) ---
    start_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    end_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    season = forms.ChoiceField(required=False, choices=SEASON_CHOICES)
    month = forms.ChoiceField(required=False, choices=MONTH_CHOICES)
    min_paired_days = forms.IntegerField(
        required=False, min_value=4, max_value=10000, initial=DEFAULT_MIN_PAIRED_DAYS
    )

    # --- location ---
    regions = forms.MultipleChoiceField(
        required=False, choices=[], widget=forms.CheckboxSelectMultiple
    )
    # Checkboxes rather than a multi-select list: a list box needs ctrl-click to
    # add and makes deselection genuinely hard to discover.
    huc2 = forms.MultipleChoiceField(
        required=False, choices=[], widget=forms.CheckboxSelectMultiple
    )
    site_query = forms.CharField(
        required=False,
        max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Site number or station name"}),
    )

    # --- visualization controls (choices filled per dataset) ---
    map_color = forms.ChoiceField(required=False, choices=[])
    map_palette = forms.ChoiceField(
        required=False, choices=PALETTE_CHOICES, initial=DEFAULT_PALETTE
    )
    # How metric values map onto that scale. Applies to the map and to a
    # metric-colored scatter, so one metric reads the same on both.
    color_scale = forms.ChoiceField(
        required=False, choices=COLOR_SCALE_CHOICES, initial=SCALE_AUTO
    )
    scatter_x = forms.ChoiceField(required=False, choices=[])
    scatter_y = forms.ChoiceField(required=False, choices=[])
    log_x = forms.BooleanField(required=False, initial=True)
    log_y = forms.BooleanField(required=False, initial=False)
    scatter_color = forms.ChoiceField(required=False, choices=[])

    def __init__(self, dataset, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dataset = dataset
        self.schema = dataset.metric_schema()
        labels = self.schema["labels"]

        self.median_cols = list(self.schema["medians"])
        self.mi_cols = list(self.schema["mis"])
        self.nmi_cols = list(self.schema.get("nmis", []))
        self.range_metrics = self.median_cols + self.mi_cols + self.nmi_cols
        self.count_cols = [
            c for c in self.schema["numeric"] if c.startswith(("n_g", "n_paired_"))
        ]

        for col in self.range_metrics:
            self.fields[f"{col}__min"] = forms.FloatField(
                required=False, widget=forms.NumberInput(attrs={"step": "any"})
            )
            self.fields[f"{col}__max"] = forms.FloatField(
                required=False, widget=forms.NumberInput(attrs={"step": "any"})
            )
        for col in self.count_cols:
            self.fields[f"{col}__min"] = forms.IntegerField(required=False, min_value=0)

        axis_choices = [(c, labels.get(c, c)) for c in self.schema["numeric"]]
        color_choices = [("location_type", "Region (categorical)")] + [
            (c, labels.get(c, c)) for c in self.range_metrics
        ]
        self.fields["scatter_x"].choices = axis_choices
        self.fields["scatter_y"].choices = axis_choices
        self.fields["scatter_color"].choices = color_choices
        self.fields["map_color"].choices = color_choices

        self._default_x = self.median_cols[0] if self.median_cols else ""
        self._default_y = (
            self.mi_cols[0]
            if self.mi_cols
            else (self.median_cols[-1] if self.median_cols else "")
        )
        self.fields["scatter_x"].initial = self._default_x
        self.fields["scatter_y"].initial = self._default_y
        self.fields["scatter_color"].initial = "location_type"
        self.fields["map_color"].initial = "location_type"

        meta = load_dataset_metadata(dataset)
        self.fields["regions"].choices = self._region_choices(meta)
        self.fields["huc2"].choices = self._huc2_choices(meta)

    # --- choice builders ---
    @staticmethod
    def _region_choices(meta) -> list[tuple[str, str]]:
        """Only regions that at least one site in this dataset belongs to."""
        present = set()
        if "location_type" in meta.columns:
            present = {
                str(v).strip()
                for v in meta["location_type"].dropna().tolist()
                if str(v).strip() not in ("", "nan", "<NA>")
            }
        ordered = [r for r in REGION_ORDER if r in present]
        extras = sorted(present - set(REGION_ORDER))
        return [(r, r) for r in ordered + extras]

    @staticmethod
    def _huc2_choices(meta) -> list[tuple[str, str]]:
        if "huc2" not in meta.columns:
            return []
        values = sorted(
            {
                str(h)
                for h in meta["huc2"].dropna().tolist()
                if str(h).strip() not in ("", "nan", "<NA>")
            }
        )
        names: dict[str, str] = {}
        if "huc2_region_name" in meta.columns:
            for _, r in meta.dropna(subset=["huc2"]).iterrows():
                nm = r.get("huc2_region_name")
                if nm is not None and str(nm) not in ("nan", "<NA>", ""):
                    names.setdefault(str(r["huc2"]), str(nm))
        return [(h, f"{h} {names[h]}" if names.get(h) else h) for h in values]

    # --- validation ---
    def clean(self):
        """Catch contradictory input here rather than returning a blank table.

        An inverted date window or an inverted numeric range silently produces
        an all-False mask downstream, which looks exactly like "no sites match"
        and gives the user nothing to act on.
        """
        cd = super().clean()
        start, end = cd.get("start_date"), cd.get("end_date")
        if start and end and start > end:
            self.add_error("end_date", "End date must be on or after the start date.")

        for col in self.range_metrics:
            lo, hi = cd.get(f"{col}__min"), cd.get(f"{col}__max")
            if lo is not None and hi is not None and lo > hi:
                label = self.schema["labels"].get(col, col)
                self.add_error(
                    f"{col}__max", f"{label}: maximum must be at least the minimum."
                )
        return cd

    # --- rows the template renders ---
    def range_rows(self, columns) -> list[dict]:
        labels = self.schema["labels"]
        return [
            {
                "key": c,
                "label": labels.get(c, c),
                "min": self[f"{c}__min"],
                "max": self[f"{c}__max"],
            }
            for c in columns
        ]

    def count_rows(self) -> list[dict]:
        labels = self.schema["labels"]
        return [
            {"key": c, "label": labels.get(c, c), "min": self[f"{c}__min"]}
            for c in self.count_cols
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
            "min_paired_days": cd.get("min_paired_days") or DEFAULT_MIN_PAIRED_DAYS,
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
            "map_palette": cd.get("map_palette") or DEFAULT_PALETTE,
            "color_scale": cd.get("color_scale") or SCALE_AUTO,
        }

    def active_filters(self) -> list[dict]:
        """Human-readable chips for every filter currently narrowing the table.

        Returned to the browser so the results header can show what is in
        effect, and let the user drop any one of them without hunting through
        the sidebar for the control that set it.
        """
        cd = self.cleaned_data
        labels = self.schema["labels"]
        chips: list[dict] = []

        def add(fields, text):
            chips.append({"fields": list(fields), "label": text})

        if cd.get("start_date") or cd.get("end_date"):
            lo = cd["start_date"].isoformat() if cd.get("start_date") else "start"
            hi = cd["end_date"].isoformat() if cd.get("end_date") else "today"
            add(["start_date", "end_date"], f"{lo} to {hi}")
        if cd.get("season"):
            add(["season"], dict(SEASON_CHOICES)[cd["season"]])
        if cd.get("month"):
            add(["month"], dict(MONTH_CHOICES)[cd["month"]])
        if (cd.get("min_paired_days") or DEFAULT_MIN_PAIRED_DAYS) != DEFAULT_MIN_PAIRED_DAYS:
            add(["min_paired_days"], f"MI needs {cd['min_paired_days']}+ paired days")
        for r in cd.get("regions") or []:
            add([f"regions:{r}"], f"Region: {r}")
        for h in cd.get("huc2") or []:
            add([f"huc2:{h}"], f"HUC2 {h}")
        if cd.get("site_query"):
            add(["site_query"], f'Search "{cd["site_query"]}"')

        for col in self.range_metrics + self.count_cols:
            lo, hi = cd.get(f"{col}__min"), cd.get(f"{col}__max")
            if lo is None and hi is None:
                continue
            name = labels.get(col, col)
            if lo is not None and hi is not None:
                text = f"{name}: {_num(lo)} to {_num(hi)}"
            elif lo is not None:
                text = f"{name}: at least {_num(lo)}"
            else:
                text = f"{name}: at most {_num(hi)}"
            add([f"{col}__min", f"{col}__max"], text)
        return chips


def _num(v) -> str:
    if v is None:
        return ""
    f = float(v)
    return str(int(f)) if f.is_integer() else f"{f:g}"
