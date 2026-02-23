"""Contact cycle detector (two step: open -> close) for the Chores integration."""
from __future__ import annotations

from typing import Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from ..const import DetectorType, SubState
from .base import BaseDetector


class ContactCycleDetector(BaseDetector):
    """Detects a contact open-then-close cycle (two-step)."""

    detector_type = DetectorType.CONTACT_CYCLE
    steps_total = 2

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._entity_id: str = config["entity_id"]
        self._debounce_seconds: int = config.get("debounce_seconds", 2)
        self._pending_active_cancel: CALLBACK_TYPE | None = None

    def _reset_internal(self) -> None:
        if self._pending_active_cancel:
            self._pending_active_cancel()
            self._pending_active_cancel = None

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

            if new_state.state == "on" and self._state == SubState.IDLE:
                if self._pending_active_cancel:
                    self._pending_active_cancel()

                @callback
                def _confirm_active(_now: Any) -> None:
                    self._pending_active_cancel = None
                    if self._state == SubState.IDLE:
                        self.set_state(SubState.ACTIVE)
                        on_state_change()

                self._pending_active_cancel = async_call_later(
                    hass, self._debounce_seconds, _confirm_active
                )

            elif new_state.state == "off" and self._state == SubState.IDLE and self._pending_active_cancel:
                self._pending_active_cancel()
                self._pending_active_cancel = None

            elif new_state.state == "off" and self._state == SubState.ACTIVE:
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
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        pass
