"""Meteorological seasons & calendar months (port of research1 nitro/season_defs.py)."""

from __future__ import annotations

SEASON_ORDER: tuple[str, ...] = ("spring", "summer", "fall", "winter")

SEASON_MONTHS: dict[str, frozenset[int]] = {
    "spring": frozenset({3, 4, 5}),
    "summer": frozenset({6, 7, 8}),
    "fall": frozenset({9, 10, 11}),
    "winter": frozenset({12, 1, 2}),
}

CALENDAR_MONTHS: tuple[tuple[str, int], ...] = (
    ("january", 1),
    ("february", 2),
    ("march", 3),
    ("april", 4),
    ("may", 5),
    ("june", 6),
    ("july", 7),
    ("august", 8),
    ("september", 9),
    ("october", 10),
    ("november", 11),
    ("december", 12),
)
_MONTH_BY_SLUG = dict(CALENDAR_MONTHS)


def months_for_period(season: str | None, month: str | None) -> frozenset[int] | None:
    """Return the set of calendar months for a season or single month, else None.

    ``month`` (a slug like "january") takes precedence over ``season``. Returns
    ``None`` when neither is set, meaning "all months".
    """
    if month:
        m = _MONTH_BY_SLUG.get(month.lower())
        return frozenset({m}) if m else None
    if season:
        return SEASON_MONTHS.get(season.lower())
    return None
