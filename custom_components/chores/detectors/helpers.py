"""Shared helpers for detector modules."""
from __future__ import annotations

WEEKDAY_MAP: dict[str, int] = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6,
}

WEEKDAY_SHORT_NAMES: dict[int, str] = {
    0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu",
    4: "Fri", 5: "Sat", 6: "Sun",
}
