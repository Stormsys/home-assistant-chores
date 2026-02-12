"""Completion types for the Chores integration.

Each completion monitors how a chore gets marked as done and transitions through:
    idle -> active (optional, 2-step only) -> done

Adding a new completion: subclass BaseCompletion, implement the abstract methods,
and register it in COMPLETION_FACTORY.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import CompletionType, SubState

_LOGGER = logging.getLogger(__name__)


class BaseCompletion(ABC):
    """Abstract base class for all completion types."""

    completion_type: CompletionType
    steps_total: int = 1

    def __init__(self, config: dict[str, Any]) -> None:
        self._state: SubState = SubState.IDLE
        self._state_entered_at: datetime = dt_util.utcnow()
        self._sensor_config: dict[str, Any] | None = config.get("sensor")
        self._listeners: list[CALLBACK_TYPE] = []
        self._steps_done: int = 0
        self._enabled: bool = False  # Only listen when chore is due/started

    # ── Public API ──────────────────────────────────────────────────

    @property
    def state(self) -> SubState:
        return self._state

    @property
    def state_entered_at(self) -> datetime:
        return self._state_entered_at

    @property
    def sensor_config(self) -> dict[str, Any] | None:
        return self._sensor_config

    @property
    def has_sensor(self) -> bool:
        return self._sensor_config is not None

    @property
    def steps_done(self) -> int:
        return self._steps_done

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        """Enable listening for completion events (called when chore becomes due)."""
        self._enabled = True

    def disable(self) -> None:
        """Disable listening (called when chore resets)."""
        self._enabled = False

    def set_state(self, new_state: SubState) -> bool:
        """Set the completion state. Returns True if changed."""
        if new_state == self._state:
            return False
        old = self._state
        self._state = new_state
        self._state_entered_at = dt_util.utcnow()
        if new_state == SubState.ACTIVE:
            self._steps_done = 1
        elif new_state == SubState.DONE:
            self._steps_done = self.steps_total
        _LOGGER.debug(
            "Completion %s: %s -> %s", self.completion_type, old, new_state
        )
        return True

    def reset(self) -> None:
        """Reset completion to idle."""
        self._state = SubState.IDLE
        self._state_entered_at = dt_util.utcnow()
        self._steps_done = 0
        self._enabled = False
        self._reset_internal()

    @abstractmethod
    def _reset_internal(self) -> None:
        """Reset internal tracking state."""

    # ── Listener management ─────────────────────────────────────────

    @abstractmethod
    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        """Set up HA event listeners for this completion."""

    def async_remove_listeners(self) -> None:
        """Remove all registered listeners."""
        for unsub in self._listeners:
            unsub()
        self._listeners.clear()

    # ── Attributes for the completion progress sensor ───────────────

    @abstractmethod
    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        """Return extra state attributes for the completion progress sensor."""

    # ── Persistence ─────────────────────────────────────────────────

    def snapshot_state(self) -> dict[str, Any]:
        """Return state for persistence."""
        return {
            "state": self._state.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            "steps_done": self._steps_done,
            "enabled": self._enabled,
            **self._snapshot_internal(),
        }

    @abstractmethod
    def _snapshot_internal(self) -> dict[str, Any]:
        """Return completion-specific state for persistence."""

    def restore_state(self, data: dict[str, Any]) -> None:
        """Restore state from persistence."""
        if "state" in data:
            self._state = SubState(data["state"])
        if "state_entered_at" in data:
            self._state_entered_at = (
                dt_util.parse_datetime(data["state_entered_at"]) or dt_util.utcnow()
            )
        self._steps_done = data.get("steps_done", 0)
        self._enabled = data.get("enabled", False)
        self._restore_internal(data)

    @abstractmethod
    def _restore_internal(self, data: dict[str, Any]) -> None:
        """Restore completion-specific state from persistence."""


# ═══════════════════════════════════════════════════════════════════════
# ManualCompletion
# ═══════════════════════════════════════════════════════════════════════


class ManualCompletion(BaseCompletion):
    """Completion via the force-complete button/service only."""

    completion_type = CompletionType.MANUAL
    steps_total = 1

    def _reset_internal(self) -> None:
        pass

    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        # No listeners needed -- manual completion is triggered via service/button
        pass

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        return {
            "completion_type": self.completion_type.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            "steps_total": self.steps_total,
            "steps_done": self._steps_done,
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════
# SensorStateCompletion
# ═══════════════════════════════════════════════════════════════════════


class SensorStateCompletion(BaseCompletion):
    """Completion when an entity enters a specific state."""

    completion_type = CompletionType.SENSOR_STATE
    steps_total = 1

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
            if not self._enabled:
                return
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
            "completion_type": self.completion_type.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            "watched_entity": self._entity_id,
            "watched_entity_state": state.state if state else None,
            "target_state": self._target_state,
            "steps_total": self.steps_total,
            "steps_done": self._steps_done,
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════
# ContactCompletion (single step)
# ═══════════════════════════════════════════════════════════════════════


class ContactCompletion(BaseCompletion):
    """Completion when a contact sensor opens (single step)."""

    completion_type = CompletionType.CONTACT
    steps_total = 1

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._entity_id: str = config["entity_id"]

    def _reset_internal(self) -> None:
        pass

    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        @callback
        def _handle_state_change(event: Event) -> None:
            if not self._enabled:
                return
            new_state = event.data.get("new_state")
            if new_state and new_state.state == "on":
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
            "completion_type": self.completion_type.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            "watched_entity": self._entity_id,
            "watched_entity_state": state.state if state else None,
            "steps_total": self.steps_total,
            "steps_done": self._steps_done,
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════
# ContactCycleCompletion (two step: open -> close)
# ═══════════════════════════════════════════════════════════════════════


class ContactCycleCompletion(BaseCompletion):
    """Completion via contact open then close (two-step)."""

    completion_type = CompletionType.CONTACT_CYCLE
    steps_total = 2

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._entity_id: str = config["entity_id"]

    def _reset_internal(self) -> None:
        pass

    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        @callback
        def _handle_state_change(event: Event) -> None:
            if not self._enabled:
                return
            new_state = event.data.get("new_state")
            if not new_state:
                return

            if new_state.state == "on" and self._state == SubState.IDLE:
                # Contact opened -- step 1
                self.set_state(SubState.ACTIVE)
                on_state_change()
            elif new_state.state == "off" and self._state == SubState.ACTIVE:
                # Contact closed -- step 2
                self.set_state(SubState.DONE)
                on_state_change()

        unsub = async_track_state_change_event(
            hass, [self._entity_id], _handle_state_change
        )
        self._listeners.append(unsub)

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        state = hass.states.get(self._entity_id)
        return {
            "completion_type": self.completion_type.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            "watched_entity": self._entity_id,
            "watched_entity_state": state.state if state else None,
            "steps_total": self.steps_total,
            "steps_done": self._steps_done,
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════
# PresenceCycleCompletion (two step: leave -> return)
# ═══════════════════════════════════════════════════════════════════════


class PresenceCycleCompletion(BaseCompletion):
    """Completion via presence: leave home then return (two-step).

    Auto-detects entity domain:
      - person.*: not_home = away, home = returned
      - binary_sensor.* / others: off = away, on = returned
    """

    completion_type = CompletionType.PRESENCE_CYCLE
    steps_total = 2

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._entity_id: str = config["entity_id"]

        # Determine away/home states based on entity domain
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
            if not self._enabled:
                return
            new_state = event.data.get("new_state")
            if not new_state:
                return

            if new_state.state == self._away_state and self._state == SubState.IDLE:
                # Person left -- step 1
                self.set_state(SubState.ACTIVE)
                on_state_change()
            elif new_state.state == self._home_state and self._state == SubState.ACTIVE:
                # Person returned -- step 2
                self.set_state(SubState.DONE)
                on_state_change()

        unsub = async_track_state_change_event(
            hass, [self._entity_id], _handle_state_change
        )
        self._listeners.append(unsub)

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        state = hass.states.get(self._entity_id)
        return {
            "completion_type": self.completion_type.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            "watched_entity": self._entity_id,
            "watched_entity_state": state.state if state else None,
            "away_state": self._away_state,
            "home_state": self._home_state,
            "steps_total": self.steps_total,
            "steps_done": self._steps_done,
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════════════════

COMPLETION_FACTORY: dict[str, type[BaseCompletion]] = {
    CompletionType.MANUAL: ManualCompletion,
    CompletionType.SENSOR_STATE: SensorStateCompletion,
    CompletionType.CONTACT: ContactCompletion,
    CompletionType.CONTACT_CYCLE: ContactCycleCompletion,
    CompletionType.PRESENCE_CYCLE: PresenceCycleCompletion,
}


def create_completion(config: dict[str, Any]) -> BaseCompletion:
    """Create a completion instance from configuration."""
    completion_type = config.get("type", "manual")
    cls = COMPLETION_FACTORY.get(completion_type)
    if cls is None:
        raise ValueError(f"Unknown completion type: {completion_type}")
    return cls(config)

