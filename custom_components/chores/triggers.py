"""Trigger types for the Chores integration.

Each trigger monitors external conditions and transitions through:
    idle -> active -> done

Adding a new trigger: subclass BaseTrigger, implement the abstract methods,
and register it in TRIGGER_FACTORY.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.util import dt as dt_util

from .const import SubState, TriggerType

_LOGGER = logging.getLogger(__name__)


class BaseTrigger(ABC):
    """Abstract base class for all trigger types."""

    trigger_type: TriggerType

    def __init__(self, config: dict[str, Any]) -> None:
        self._state: SubState = SubState.IDLE
        self._state_entered_at: datetime = dt_util.utcnow()
        self._sensor_config: dict[str, Any] | None = config.get("sensor")
        self._listeners: list[CALLBACK_TYPE] = []

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

    def set_state(self, new_state: SubState) -> bool:
        """Set the trigger state. Returns True if changed."""
        if new_state == self._state:
            return False
        old = self._state
        self._state = new_state
        self._state_entered_at = dt_util.utcnow()
        _LOGGER.debug("Trigger %s: %s -> %s", self.trigger_type, old, new_state)
        return True

    def reset(self) -> None:
        """Reset trigger to idle."""
        self.set_state(SubState.IDLE)
        self._reset_internal()

    @abstractmethod
    def _reset_internal(self) -> None:
        """Reset internal tracking state."""

    # ── Listener management ─────────────────────────────────────────

    @abstractmethod
    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        """Set up HA event listeners for this trigger."""

    def async_remove_listeners(self) -> None:
        """Remove all registered listeners."""
        for unsub in self._listeners:
            unsub()
        self._listeners.clear()

    # ── Polling (called every coordinator update) ───────────────────

    def evaluate(self, hass: HomeAssistant) -> SubState:
        """Evaluate current state (called on every coordinator poll).

        Default implementation returns current state. Override for triggers
        that need time-based evaluation (e.g. cooldown timers).
        """
        return self._state

    # ── Attributes for the trigger progress sensor ──────────────────

    @abstractmethod
    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        """Return extra state attributes for the trigger progress sensor."""

    # ── Persistence ─────────────────────────────────────────────────

    def snapshot_state(self) -> dict[str, Any]:
        """Return state for persistence."""
        return {
            "state": self._state.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            **self._snapshot_internal(),
        }

    @abstractmethod
    def _snapshot_internal(self) -> dict[str, Any]:
        """Return trigger-specific state for persistence."""

    def restore_state(self, data: dict[str, Any]) -> None:
        """Restore state from persistence."""
        if "state" in data:
            self._state = SubState(data["state"])
        if "state_entered_at" in data:
            self._state_entered_at = dt_util.parse_datetime(data["state_entered_at"]) or dt_util.utcnow()
        self._restore_internal(data)

    @abstractmethod
    def _restore_internal(self, data: dict[str, Any]) -> None:
        """Restore trigger-specific state from persistence."""


# ═══════════════════════════════════════════════════════════════════════
# PowerCycleTrigger
# ═══════════════════════════════════════════════════════════════════════


class PowerCycleTrigger(BaseTrigger):
    """Trigger that detects power/current cycles.

    Active: power or current above threshold (machine running).
    Done: power AND current drop below threshold for cooldown_minutes.
    """

    trigger_type = TriggerType.POWER_CYCLE

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

    def _is_above_threshold(self, hass: HomeAssistant) -> bool:
        """Check if power/current is above threshold."""
        power_above = False
        current_above = False

        if self._power_sensor:
            state = hass.states.get(self._power_sensor)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    power_above = float(state.state) > self._power_threshold
                except (ValueError, TypeError):
                    pass

        if self._current_sensor:
            state = hass.states.get(self._current_sensor)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    current_above = float(state.state) > self._current_threshold
                except (ValueError, TypeError):
                    pass

        return power_above or current_above

    def _evaluate_power(self, hass: HomeAssistant) -> None:
        """Evaluate power state and update trigger."""
        above = self._is_above_threshold(hass)
        now = dt_util.utcnow()

        if above:
            # Machine is running
            self._machine_running = True
            self._power_dropped_at = None
            if self._state == SubState.IDLE:
                self.set_state(SubState.ACTIVE)
        else:
            if self._machine_running and self._power_dropped_at is None:
                # Power just dropped -- start cooldown
                self._power_dropped_at = now

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
            "trigger_type": self.trigger_type.value,
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


# ═══════════════════════════════════════════════════════════════════════
# StateChangeTrigger
# ═══════════════════════════════════════════════════════════════════════


class StateChangeTrigger(BaseTrigger):
    """Trigger that fires on an entity state transition.

    Active: entity is in `from` state.
    Done: entity transitions to `to` state.
    """

    trigger_type = TriggerType.STATE_CHANGE

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
            "trigger_type": self.trigger_type.value,
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


# ═══════════════════════════════════════════════════════════════════════
# DailyTrigger
# ═══════════════════════════════════════════════════════════════════════


class DailyTrigger(BaseTrigger):
    """Trigger that fires at a specific time each day.

    Without gate: time reached -> done immediately.
    With gate: time reached -> active (pending), gate entity enters state -> done.
    """

    trigger_type = TriggerType.DAILY

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        time_val = config["time"]
        if isinstance(time_val, str):
            parts = time_val.split(":")
            self._time: time = time(int(parts[0]), int(parts[1]))
        else:
            self._time = time_val

        gate = config.get("gate")
        self._gate_entity: str | None = gate.get("entity_id") if gate else None
        self._gate_state: str | None = gate.get("state") if gate else None
        self._has_gate: bool = self._gate_entity is not None
        self._time_fired_today: bool = False

    @property
    def trigger_time(self) -> time:
        return self._time

    @property
    def has_gate(self) -> bool:
        return self._has_gate

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
        # Time listener for the daily trigger
        @callback
        def _handle_time(now: datetime) -> None:
            if self._state != SubState.IDLE:
                return
            self._time_fired_today = True
            if self._has_gate:
                # Check if gate is already met
                if self._is_gate_met(hass):
                    self.set_state(SubState.DONE)
                else:
                    self.set_state(SubState.ACTIVE)
            else:
                self.set_state(SubState.DONE)
            on_state_change()

        unsub_time = async_track_time_change(
            hass, _handle_time, hour=self._time.hour, minute=self._time.minute, second=0
        )
        self._listeners.append(unsub_time)

        # Gate entity listener (if configured)
        if self._gate_entity:

            @callback
            def _handle_gate(event: Event) -> None:
                if self._state != SubState.ACTIVE:
                    return
                new_state = event.data.get("new_state")
                if new_state and new_state.state == self._gate_state:
                    self.set_state(SubState.DONE)
                    on_state_change()

            unsub_gate = async_track_state_change_event(
                hass, [self._gate_entity], _handle_gate
            )
            self._listeners.append(unsub_gate)

    def _is_gate_met(self, hass: HomeAssistant) -> bool:
        """Check if the gate condition is currently met."""
        if not self._gate_entity:
            return True
        state = hass.states.get(self._gate_entity)
        return state is not None and state.state == self._gate_state

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
            # If we're past the trigger time today and haven't fired
            if now >= today_trigger:
                # Check gate and set state appropriately
                self._time_fired_today = True
                if self._has_gate:
                    # Check if gate is already met
                    if self._is_gate_met(hass):
                        self.set_state(SubState.DONE)
                    else:
                        self.set_state(SubState.ACTIVE)
                else:
                    self.set_state(SubState.DONE)
        return self._state

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "trigger_type": self.trigger_type.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            "trigger_time": self._time.isoformat(),
            "next_trigger": self.next_trigger_datetime.isoformat(),
            "time_fired_today": self._time_fired_today,
        }
        if self._gate_entity:
            state = hass.states.get(self._gate_entity)
            attrs["gate_entity"] = self._gate_entity
            attrs["gate_expected_state"] = self._gate_state
            attrs["gate_current_state"] = state.state if state else None
            attrs["gate_met"] = self._is_gate_met(hass)
        return attrs

    def _snapshot_internal(self) -> dict[str, Any]:
        return {
            "time_fired_today": self._time_fired_today,
        }

    def _restore_internal(self, data: dict[str, Any]) -> None:
        self._time_fired_today = data.get("time_fired_today", False)


# ═══════════════════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════════════════

TRIGGER_FACTORY: dict[str, type[BaseTrigger]] = {
    TriggerType.POWER_CYCLE: PowerCycleTrigger,
    TriggerType.STATE_CHANGE: StateChangeTrigger,
    TriggerType.DAILY: DailyTrigger,
}


def create_trigger(config: dict[str, Any]) -> BaseTrigger:
    """Create a trigger instance from configuration."""
    trigger_type = config["type"]
    cls = TRIGGER_FACTORY.get(trigger_type)
    if cls is None:
        raise ValueError(f"Unknown trigger type: {trigger_type}")
    return cls(config)

