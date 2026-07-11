"""Unit normalization inside a parameter group.

Each group has a target unit (its most common member unit). Codes already in the
target unit pass through; codes with a known conversion are converted; anything
else is EXCLUDED from the group's daily mean and reported — never silently mixed.

The conversion registry ports the two research1 conversions
(explorer/core/conversions.py::convert_no3no2_to_mg_per_l_as_n): nitrogen loads
divided by daily streamflow (00060, cfs) with the standard factors.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# lb/day -> mg/L divides by flow_cfs * 5.3937; short tons/day by flow_cfs * 0.002697.
FACTOR_LBS = 5.3937
FACTOR_TONS = 0.002697


def norm_unit(u: str) -> str:
    return " ".join(str(u or "").strip().lower().split())


@dataclass(frozen=True)
class Conversion:
    factor: float  # value / (flow * factor)
    needs_flow: bool = True


# (from_unit, to_unit) -> Conversion. All current entries are flow-normalized
# nitrogen loads; extend here as new needs come up.
CONVERSIONS: dict[tuple[str, str], Conversion] = {
    ("lb/d as n", "mg/l as n"): Conversion(FACTOR_LBS),
    ("lbs/day as n", "mg/l as n"): Conversion(FACTOR_LBS),
    ("ton/d as n", "mg/l as n"): Conversion(FACTOR_TONS),
    ("tons/day as n", "mg/l as n"): Conversion(FACTOR_TONS),
}


def plan_group_units(group_pmcodes: list[dict], flow_available: bool) -> tuple[str, dict, list]:
    """Decide per-code handling for one group.

    Returns (target_unit, actions, report) where actions maps code ->
    {"action": "keep"|"convert"|"exclude", "conversion": Conversion|None} and
    report is a list of human-readable dicts for the dataset's unit report.
    """
    units = [norm_unit(p.get("unit")) for p in group_pmcodes]
    units_nonempty = [u for u in units if u]
    target = max(set(units_nonempty), key=units_nonempty.count) if units_nonempty else ""

    actions: dict[str, dict] = {}
    report: list[dict] = []
    for p in group_pmcodes:
        code = str(p["code"])
        u = norm_unit(p.get("unit"))
        if not u or u == target:
            actions[code] = {"action": "keep", "conversion": None}
            if u:
                report.append({"code": code, "action": "kept", "detail": f"already {target}"})
            else:
                report.append({"code": code, "action": "kept", "detail": "unit unknown; used as-is"})
            continue
        conv = CONVERSIONS.get((u, target))
        if conv is not None:
            if conv.needs_flow and not flow_available:
                actions[code] = {"action": "exclude", "conversion": None}
                report.append(
                    {
                        "code": code,
                        "action": "excluded",
                        "detail": f"{u} -> {target} needs streamflow 00060 in the dataset",
                    }
                )
            else:
                actions[code] = {"action": "convert", "conversion": conv}
                report.append(
                    {"code": code, "action": "converted", "detail": f"{u} -> {target} (÷ flow·factor)"}
                )
        else:
            actions[code] = {"action": "exclude", "conversion": None}
            report.append(
                {"code": code, "action": "excluded", "detail": f"no conversion {u} -> {target}"}
            )
    return target, actions, report


def apply_conversion(values: pd.Series, flow_cfs: pd.Series | None, conv: Conversion) -> pd.Series:
    """value / (flow * factor); non-positive/missing flow -> NaN."""
    out = pd.to_numeric(values, errors="coerce").astype(float)
    if conv.needs_flow:
        flow = pd.to_numeric(flow_cfs, errors="coerce").astype(float) if flow_cfs is not None else None
        if flow is None:
            return pd.Series(np.nan, index=out.index)
        bad = (~np.isfinite(flow)) | (flow <= 0)
        res = out / (flow * conv.factor)
        res[bad] = np.nan
        return res
    return out / conv.factor
