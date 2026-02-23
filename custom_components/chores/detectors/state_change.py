"""State change detector for the Chores integration."""
from __future__ import annotations

from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from ..const import DetectorType, SubState
from .base import BaseDetector


class StateChangeDetector(BaseDetector):
    """Detects an entity state transition (from -> to).

    Active: entity is in ``from`` state.
    Done: entity transitions to ``to`` state.
    """

    detector_type = DetectorType.STATE_CHANGE

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._entity_id: str = config["entity_id"]
        self._from_state: str = config["from"]
        self._to_state: str = config["to"]

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

            new_val = new_state.state
            old_val = old_state.state if old_state else None

            if new_val == self._from_state and self._state == SubState.IDLE:
                self.set_state(SubState.ACTIVE)
                on_state_change()
            elif (
                old_val == self._from_state
                and new_val == self._to_state
                and self._state in (SubState.IDLE, SubState.ACTIVE)
            ):
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
            "expected_from": self._from_state,
            "expected_to": self._to_state,
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        pass
