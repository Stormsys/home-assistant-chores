"""Weekly schedule detector for the Chores integration."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from ..const import DetectorType, SubState
from .base import BaseDetector
from .helpers import WEEKDAY_MAP, WEEKDAY_SHORT_NAMES


class WeeklyDetector(BaseDetector):
    """Detects weekly scheduled time events.

    Done when a configured time is reached on a matching weekday.
    Gate logic (if any) is handled by the stage wrapper, not this detector.
    """

    detector_type = DetectorType.WEEKLY

    @classmethod
    def supported_stages(cls) -> frozenset[str]:
        return frozenset({"trigger"})

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._schedule: list[tuple[int, time]] = []
        for entry in config["schedule"]:
            day_int = WEEKDAY_MAP[entry["day"]]
            time_val = entry["time"]
            if isinstance(time_val, str):
                parts = time_val.split(":")
                t = time(int(parts[0]), int(parts[1]))
            else:
                t = time_val
            self._schedule.append((day_int, t))
        self._time_fired_today: bool = False

    @property
    def schedule(self) -> list[tuple[int, time]]:
        return self._schedule

    @property
    def next_trigger_datetime(self) -> datetime:
        """Calculate the next trigger datetime across all schedule entries."""
        now = dt_util.now()
        best: datetime | None = None
        for weekday, t in self._schedule:
            candidate = now.replace(
                hour=t.hour, minute=t.minute, second=0, microsecond=0,
            )
            days_ahead = weekday - now.weekday()
            if days_ahead < 0:
                days_ahead += 7
            candidate += timedelta(days=days_ahead)
            if candidate <= now:
                candidate += timedelta(days=7)
            if best is None or candidate < best:
                best = candidate
        if best is None:
            return now + timedelta(days=1)
        return best

    def _todays_trigger_time(self, now: datetime) -> time | None:
        """Return the scheduled trigger time for today, or None."""
        current_day = now.weekday()
        for weekday, t in self._schedule:
            if weekday == current_day:
                return t
        return None

    def _reset_internal(self) -> None:
        self._time_fired_today = False

    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        times_to_days: dict[time, set[int]] = {}
        for weekday, t in self._schedule:
            times_to_days.setdefault(t, set()).add(weekday)

        for trigger_time, valid_days in times_to_days.items():

            @callback
            def _handle_time(now: datetime, _days: set[int] = valid_days) -> None:
                if self._state != SubState.IDLE:
                    return
                if now.weekday() not in _days:
                    return
                self._time_fired_today = True
                self.set_state(SubState.DONE)
                on_state_change()

            unsub_time = async_track_time_change(
                hass, _handle_time,
                hour=trigger_time.hour, minute=trigger_time.minute, second=0,
            )
            self._listeners.append(unsub_time)

    def evaluate(self, hass: HomeAssistant) -> SubState:
        """Check if we've passed a scheduled trigger time today (handles startup)."""
        if self._state == SubState.IDLE and not self._time_fired_today:
            now = dt_util.now()
            trigger_time = self._todays_trigger_time(now)
            if trigger_time is not None:
                today_trigger = now.replace(
                    hour=trigger_time.hour,
                    minute=trigger_time.minute,
                    second=0,
                    microsecond=0,
                )
                if now >= today_trigger:
                    self._time_fired_today = True
                    self.set_state(SubState.DONE)
        return self._state

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        return {
            "detector_type": self.detector_type.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            "schedule": [
                {"day": WEEKDAY_SHORT_NAMES[weekday], "time": t.isoformat()}
                for weekday, t in self._schedule
            ],
            "next_trigger": self.next_trigger_datetime.isoformat(),
            "time_fired_today": self._time_fired_today,
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {"time_fired_today": self._time_fired_today}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        self._time_fired_today = data.get("time_fired_today", False)
