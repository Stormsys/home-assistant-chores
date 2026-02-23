"""Daily time detector for the Chores integration."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from ..const import DetectorType, SubState
from .base import BaseDetector


class DailyDetector(BaseDetector):
    """Detects a daily time event.

    Done when the configured time is reached each day.
    Gate logic (if any) is handled by the stage wrapper, not this detector.
    """

    detector_type = DetectorType.DAILY

    @classmethod
    def supported_stages(cls) -> frozenset[str]:
        return frozenset({"trigger"})

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        time_val = config["time"]
        if isinstance(time_val, str):
            parts = time_val.split(":")
            self._time: time = time(int(parts[0]), int(parts[1]))
        else:
            self._time = time_val
        self._time_fired_today: bool = False

    @property
    def trigger_time(self) -> time:
        return self._time

    @property
    def next_trigger_datetime(self) -> datetime:
        """Calculate the next trigger datetime."""
        now = dt_util.now()
        today_trigger = now.replace(
            hour=self._time.hour,
            minute=self._time.minute,
            second=0,
            microsecond=0,
        )
        if now >= today_trigger:
            return today_trigger + timedelta(days=1)
        return today_trigger

    def _reset_internal(self) -> None:
        self._time_fired_today = False

    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        @callback
        def _handle_time(now: datetime) -> None:
            if self._state != SubState.IDLE:
                return
            self._time_fired_today = True
            self.set_state(SubState.DONE)
            on_state_change()

        unsub_time = async_track_time_change(
            hass, _handle_time, hour=self._time.hour, minute=self._time.minute, second=0
        )
        self._listeners.append(unsub_time)

    def evaluate(self, hass: HomeAssistant) -> SubState:
        """Check if we've passed the trigger time (handles startup after time)."""
        if self._state == SubState.IDLE and not self._time_fired_today:
            now = dt_util.now()
            today_trigger = now.replace(
                hour=self._time.hour,
                minute=self._time.minute,
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
            "trigger_time": self._time.isoformat(),
            "next_trigger": self.next_trigger_datetime.isoformat(),
            "time_fired_today": self._time_fired_today,
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {"time_fired_today": self._time_fired_today}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        self._time_fired_today = data.get("time_fired_today", False)
