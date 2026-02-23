"""Reusable gate logic for the Chores integration.

A gate is a conditional wrapper that can be applied to any stage (trigger
or completion).  When the underlying detector reaches DONE, the gate checks
whether a secondary entity is in the expected state.  If met, the DONE
transition passes through.  If not, the stage holds at ACTIVE (pending)
until the gate entity enters the expected state.

Gate logic was previously duplicated in DailyTrigger, WeeklyTrigger, and
DurationTrigger.  This module extracts it into a single reusable class.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

_LOGGER = logging.getLogger(__name__)


class Gate:
    """Conditional gate that checks whether an entity is in an expected state.

    Used by TriggerStage and CompletionStage to hold a detector at ACTIVE
    until the gate condition is satisfied.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._entity_id: str = config["entity_id"]
        self._expected_state: str = config["state"]
        self._listeners: list[CALLBACK_TYPE] = []

    @property
    def entity_id(self) -> str:
        return self._entity_id

    @property
    def expected_state(self) -> str:
        return self._expected_state

    def is_met(self, hass: HomeAssistant) -> bool:
        """Check if the gate condition is currently met."""
        state = hass.states.get(self._entity_id)
        return state is not None and state.state == self._expected_state

    def async_setup_listener(
        self,
        hass: HomeAssistant,
        on_gate_change: callback,
    ) -> None:
        """Listen for gate entity state changes.

        ``on_gate_change`` is called whenever the gate entity transitions
        to the expected state (ignoring startup / unavailable transitions).
        The caller (TriggerStage / CompletionStage) is responsible for
        checking ``is_met()`` and deciding what to do.
        """

        @callback
        def _handle_gate(event: Event) -> None:
            new_state = event.data.get("new_state")
            old_state = event.data.get("old_state")
            # Ignore startup/reconnection events so that HA restoring state
            # while the gate entity comes online does not silently satisfy
            # the gate without a genuine state transition.
            if old_state is None or old_state.state in ("unavailable", "unknown"):
                return
            if new_state and new_state.state == self._expected_state:
                on_gate_change()

        unsub = async_track_state_change_event(
            hass, [self._entity_id], _handle_gate
        )
        self._listeners.append(unsub)

    def async_remove_listeners(self) -> None:
        """Remove all registered listeners."""
        for unsub in self._listeners:
            unsub()
        self._listeners.clear()

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        """Return gate-specific attributes for progress sensor display."""
        state = hass.states.get(self._entity_id)
        return {
            "gate_entity": self._entity_id,
            "gate_expected_state": self._expected_state,
            "gate_current_state": state.state if state else None,
            "gate_met": self.is_met(hass),
        }
