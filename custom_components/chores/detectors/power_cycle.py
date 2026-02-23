"""Power cycle detector for the Chores integration."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from ..const import DetectorType, SubState
from .base import BaseDetector


class PowerCycleDetector(BaseDetector):
    """Detects power/current cycles (e.g. washing machine, dishwasher).

    Active: power or current above threshold (machine running).
    Done: power AND current drop below threshold for cooldown_minutes.
    """

    detector_type = DetectorType.POWER_CYCLE

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._power_sensor: str | None = config.get("power_sensor")
        self._current_sensor: str | None = config.get("current_sensor")
        self._power_threshold: float = config.get("power_threshold", 10.0)
        self._current_threshold: float = config.get("current_threshold", 0.04)
        self._cooldown_minutes: int = config.get("cooldown_minutes", 5)
        self._power_dropped_at: datetime | None = None
        self._machine_running: bool = False

    def _reset_internal(self) -> None:
        self._power_dropped_at = None
        self._machine_running = False

    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        entities = [e for e in [self._power_sensor, self._current_sensor] if e]
        if not entities:
            return

        @callback
        def _handle_state_change(event: Event) -> None:
            self._evaluate_power(hass)
            on_state_change()

        unsub = async_track_state_change_event(hass, entities, _handle_state_change)
        self._listeners.append(unsub)

    def _is_above_threshold(self, hass: HomeAssistant) -> bool | None:
        """Check if power/current is above threshold.

        Returns True/False when at least one sensor is readable.
        Returns None when all configured sensors are unavailable/unknown.
        """
        any_readable = False
        above = False

        if self._power_sensor:
            state = hass.states.get(self._power_sensor)
            if state and state.state not in ("unknown", "unavailable"):
                any_readable = True
                try:
                    if float(state.state) > self._power_threshold:
                        above = True
                except (ValueError, TypeError):
                    pass

        if self._current_sensor:
            state = hass.states.get(self._current_sensor)
            if state and state.state not in ("unknown", "unavailable"):
                any_readable = True
                try:
                    if float(state.state) > self._current_threshold:
                        above = True
                except (ValueError, TypeError):
                    pass

        return above if any_readable else None

    def _evaluate_power(self, hass: HomeAssistant) -> None:
        """Evaluate power state and update detector."""
        above = self._is_above_threshold(hass)

        if above is True:
            self._machine_running = True
            self._power_dropped_at = None
            if self._state == SubState.IDLE:
                self.set_state(SubState.ACTIVE)
        elif above is False:
            if self._machine_running and self._power_dropped_at is None:
                self._power_dropped_at = dt_util.utcnow()

    def evaluate(self, hass: HomeAssistant) -> SubState:
        """Check cooldown timer on every poll."""
        if (
            self._state == SubState.ACTIVE
            and self._power_dropped_at is not None
        ):
            elapsed = (dt_util.utcnow() - self._power_dropped_at).total_seconds()
            if elapsed >= self._cooldown_minutes * 60:
                self.set_state(SubState.DONE)
                self._machine_running = False
        return self._state

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "detector_type": self.detector_type.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            "watched_entity": self._power_sensor or self._current_sensor or "N/A",
            "machine_running": self._machine_running,
        }
        if self._power_sensor:
            state = hass.states.get(self._power_sensor)
            attrs["power_value"] = state.state if state else None
        if self._current_sensor:
            state = hass.states.get(self._current_sensor)
            attrs["current_value"] = state.state if state else None
        if self._power_dropped_at:
            remaining = max(
                0,
                self._cooldown_minutes * 60
                - (dt_util.utcnow() - self._power_dropped_at).total_seconds(),
            )
            attrs["cooldown_remaining"] = int(remaining)
        else:
            attrs["cooldown_remaining"] = None
        return attrs

    def _snapshot_internal(self) -> dict[str, Any]:
        return {
            "machine_running": self._machine_running,
            "power_dropped_at": self._power_dropped_at.isoformat() if self._power_dropped_at else None,
        }

    def _restore_internal(self, data: dict[str, Any]) -> None:
        self._machine_running = data.get("machine_running", False)
        pda = data.get("power_dropped_at")
        self._power_dropped_at = dt_util.parse_datetime(pda) if pda else None
