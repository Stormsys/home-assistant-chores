"""Duration detector for the Chores integration."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from ..const import DetectorType, SubState
from .base import BaseDetector


class DurationDetector(BaseDetector):
    """Detects an entity staying in a target state for a duration.

    Active: entity is in the target state but duration has not elapsed.
    Done: entity has remained in the target state for >= duration_hours.

    The persisted ``_state_since`` timestamp survives HA restarts.
    Transitions through ``unavailable`` / ``unknown`` are ignored to
    preserve the timer.
    """

    detector_type = DetectorType.DURATION

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._entity_id: str = config["entity_id"]
        self._target_state: str = config.get("state", "on")
        self._duration_hours: float = config["duration_hours"]
        self._state_since: datetime | None = None

    def _reset_internal(self) -> None:
        self._state_since = None

    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        @callback
        def _handle_state_change(event: Event) -> None:
            new_state = event.data.get("new_state")
            old_state = event.data.get("old_state")
            if not new_state:
                return

            new_val = new_state.state
            old_val = old_state.state if old_state else None

            if old_val is None or old_val in ("unavailable", "unknown"):
                return
            if new_val in ("unavailable", "unknown"):
                return
            if old_val == new_val:
                return

            if new_val == self._target_state and self._state == SubState.IDLE:
                self._state_since = dt_util.utcnow()
                self.set_state(SubState.ACTIVE)
                on_state_change()
            elif new_val != self._target_state and self._state == SubState.ACTIVE:
                self._state_since = None
                self.set_state(SubState.IDLE)
                on_state_change()

        unsub = async_track_state_change_event(
            hass, [self._entity_id], _handle_state_change
        )
        self._listeners.append(unsub)

    def evaluate(self, hass: HomeAssistant) -> SubState:
        """Check duration timer on every poll and handle startup recovery."""
        now = dt_util.utcnow()

        if self._state == SubState.IDLE:
            state = hass.states.get(self._entity_id)
            if (
                state
                and state.state not in ("unknown", "unavailable")
                and state.state == self._target_state
            ):
                self._state_since = self._state_since or now
                self.set_state(SubState.ACTIVE)

        if self._state == SubState.ACTIVE and self._state_since is not None:
            state = hass.states.get(self._entity_id)
            if (
                state
                and state.state not in ("unknown", "unavailable")
                and state.state != self._target_state
            ):
                self._state_since = None
                self.set_state(SubState.IDLE)
            else:
                elapsed = (now - self._state_since).total_seconds()
                if elapsed >= self._duration_hours * 3600:
                    self.set_state(SubState.DONE)

        return self._state

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        state = hass.states.get(self._entity_id)
        attrs: dict[str, Any] = {
            "detector_type": self.detector_type.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            "watched_entity": self._entity_id,
            "watched_entity_state": state.state if state else None,
            "target_state": self._target_state,
            "duration_hours": self._duration_hours,
            "state_since": self._state_since.isoformat() if self._state_since else None,
        }
        if self._state_since is not None:
            elapsed = (dt_util.utcnow() - self._state_since).total_seconds()
            total = self._duration_hours * 3600
            remaining = max(0, total - elapsed)
            attrs["time_remaining_seconds"] = int(remaining)
        else:
            attrs["time_remaining_seconds"] = None
        return attrs

    def _snapshot_internal(self) -> dict[str, Any]:
        return {
            "state_since": self._state_since.isoformat() if self._state_since else None,
        }

    def _restore_internal(self, data: dict[str, Any]) -> None:
        ss = data.get("state_since")
        self._state_since = dt_util.parse_datetime(ss) if ss else None
