"""Sensor threshold detector for the Chores integration."""
from __future__ import annotations

from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from ..const import DetectorType, SubState
from .base import BaseDetector


class SensorThresholdDetector(BaseDetector):
    """Detects when a sensor value crosses a numeric threshold.

    Single-step: idle -> done.
    Supports ``above``, ``below``, and ``equal`` operators.

    Overrides ``check_immediate`` to handle the case where the sensor
    value already satisfies the condition when the completion is enabled.
    """

    detector_type = DetectorType.SENSOR_THRESHOLD

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._entity_id: str = config["entity_id"]
        self._threshold: float = float(config["threshold"])
        self._operator: str = config.get("operator", "above")

    def _check_threshold(self, value: float) -> bool:
        """Return True when *value* satisfies the configured condition."""
        if self._operator == "above":
            return value > self._threshold
        if self._operator == "below":
            return value < self._threshold
        return value == self._threshold

    def _reset_internal(self) -> None:
        pass

    def check_immediate(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        """Check if threshold is already met right now."""
        state = hass.states.get(self._entity_id)
        if state and state.state not in ("unknown", "unavailable"):
            try:
                value = float(state.state)
            except (ValueError, TypeError):
                return
            if self._check_threshold(value) and self._state != SubState.DONE:
                self.set_state(SubState.DONE)
                on_state_change()

    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        @callback
        def _handle_state_change(event: Event) -> None:
            new_state = event.data.get("new_state")
            if not new_state or new_state.state in ("unknown", "unavailable"):
                return
            try:
                value = float(new_state.state)
            except (ValueError, TypeError):
                return
            if self._check_threshold(value) and self._state != SubState.DONE:
                self.set_state(SubState.DONE)
                on_state_change()

        unsub = async_track_state_change_event(
            hass, [self._entity_id], _handle_state_change
        )
        self._listeners.append(unsub)

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        state = hass.states.get(self._entity_id)
        current_value: float | str | None = None
        if state and state.state not in ("unknown", "unavailable"):
            try:
                current_value = float(state.state)
            except (ValueError, TypeError):
                current_value = state.state
        return {
            "detector_type": self.detector_type.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            "watched_entity": self._entity_id,
            "current_value": current_value,
            "threshold": self._threshold,
            "operator": self._operator,
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        pass
