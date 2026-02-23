"""Presence cycle detector (two step: leave -> return) for the Chores integration."""
from __future__ import annotations

from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from ..const import DetectorType, SubState
from .base import BaseDetector


class PresenceCycleDetector(BaseDetector):
    """Detects a presence leave-then-return cycle (two-step).

    Auto-detects entity domain:
      - person.* / device_tracker.*: not_home / home
      - binary_sensor.* / others: off / on
    """

    detector_type = DetectorType.PRESENCE_CYCLE
    steps_total = 2

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._entity_id: str = config["entity_id"]

        if self._entity_id.startswith(("person.", "device_tracker.")):
            self._away_state = "not_home"
            self._home_state = "home"
        else:
            self._away_state = "off"
            self._home_state = "on"

    def _reset_internal(self) -> None:
        pass

    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        @callback
        def _handle_state_change(event: Event) -> None:
            new_state = event.data.get("new_state")
            old_state = event.data.get("old_state")
            if not new_state:
                return

            if old_state is None or old_state.state in ("unavailable", "unknown"):
                return

            if new_state.state == self._away_state and self._state == SubState.IDLE:
                self.set_state(SubState.ACTIVE)
                on_state_change()
            elif new_state.state == self._home_state and self._state == SubState.ACTIVE:
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
            "away_state": self._away_state,
            "home_state": self._home_state,
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        pass
