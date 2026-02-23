"""Sensor state detector for the Chores integration."""
from __future__ import annotations

from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from ..const import DetectorType, SubState
from .base import BaseDetector


class SensorStateDetector(BaseDetector):
    """Detects when an entity enters a specific state."""

    detector_type = DetectorType.SENSOR_STATE

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._entity_id: str = config["entity_id"]
        self._target_state: str = config.get("state", "on")

    def _reset_internal(self) -> None:
        pass

    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        @callback
        def _handle_state_change(event: Event) -> None:
            new_state = event.data.get("new_state")
            if new_state and new_state.state == self._target_state:
                if self._state != SubState.DONE:
                    self.set_state(SubState.DONE)
                    on_state_change()

        unsub = async_track_state_change_event(
            hass, [self._entity_id], _handle_state_change
        )
        self._listeners.append(unsub)

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        state = hass.states.get(self._entity_id)
        return {
            "detector_type": self.detector_type.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            "watched_entity": self._entity_id,
            "watched_entity_state": state.state if state else None,
            "target_state": self._target_state,
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        pass
