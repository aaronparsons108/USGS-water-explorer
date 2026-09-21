"""Continuous color scales for metric-colored maps and scatters.

One registry, one spelling per scale, so the sidebar picker, the interactive
figure and the exported PNG can never disagree about which gradient is in use.
All four entries are perceptually uniform and safe for the common forms of
color-vision deficiency.
"""

from __future__ import annotations

AUTO = "auto"

MAP_PALETTES = {
    "viridis": {
        "label": "Viridis (purple to yellow)",
        "plotly": "Viridis",
        "css": "#440154, #414487, #2a788e, #22a884, #7ad151, #fde725",
    },
    "plasma": {
        "label": "Plasma (blue to yellow)",
        "plotly": "Plasma",
        "css": "#0d0887, #6a00a8, #b12a90, #e16462, #fca636, #f0f921",
    },
    "cividis": {
        "label": "Cividis (blue to gold)",
        "plotly": "Cividis",
        "css": "#00224e, #123570, #3b496c, #575d6d, #88836a, #c1af59, #fee838",
    },
    "magma": {
        "label": "Magma (black to cream)",
        "plotly": "Magma",
        "css": "#000004, #3b0f70, #8c2981, #de4968, #fe9f6d, #fcfdbf",
    },
}

# Short enough not to truncate inside the sidebar's select. The gradient
# preview underneath and the hint beside it carry the detail.
PALETTE_CHOICES = [(AUTO, "Auto (per metric type)")] + [
    (key, spec["label"]) for key, spec in MAP_PALETTES.items()
]

DEFAULT_PALETTE = AUTO


def auto_palette(metric_col: str) -> str:
    """Viridis for the information metrics, plasma for everything else.

    Keeping the two metric families visually distinct means a reader can tell
    at a glance whether a map is showing a concentration or a dependence.
    """
    return "viridis" if str(metric_col).startswith(("mi_", "nmi_")) else "plasma"


def resolve(palette: str | None, metric_col: str = "") -> str:
    """Normalize a requested palette key, falling back to the auto rule."""
    key = (palette or AUTO).strip().lower()
    if key in MAP_PALETTES:
        return key
    return auto_palette(metric_col)


def plotly_scale(palette: str | None, metric_col: str = "") -> str:
    """Plotly continuous-scale name for a requested palette."""
    return MAP_PALETTES[resolve(palette, metric_col)]["plotly"]


def css_gradients() -> dict[str, str]:
    """``{key: css-gradient}`` for the sidebar preview swatches."""
    return {
        key: f"linear-gradient(90deg, {spec['css']})"
        for key, spec in MAP_PALETTES.items()
    }
