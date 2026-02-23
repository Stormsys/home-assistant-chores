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

# ── Weekday helpers ──────────────────────────────────────────────────

WEEKDAY_MAP: dict[str, int] = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6,
}

WEEKDAY_SHORT_NAMES: dict[int, str] = {
    0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu",
    4: "Fri", 5: "Sat", 6: "Sun",
}


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

    def _is_above_threshold(self, hass: HomeAssistant) -> bool | None:
        """Check if power/current is above threshold.

        Returns True/False when at least one sensor is readable.
        Returns None when all configured sensors are unavailable/unknown —
        callers must not treat this as a confirmed "below threshold".
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
        """Evaluate power state and update trigger."""
        above = self._is_above_threshold(hass)
        now = dt_util.utcnow()

        if above is True:
            # Machine is running
            self._machine_running = True
            self._power_dropped_at = None
            if self._state == SubState.IDLE:
                self.set_state(SubState.ACTIVE)
        elif above is False:
            if self._machine_running and self._power_dropped_at is None:
                # Power dropped below threshold — start cooldown
                self._power_dropped_at = now
        # above is None: all sensors unavailable — hold current state, do not
        # start the cooldown timer so a connectivity blip cannot trigger a cycle.

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
                old_state = event.data.get("old_state")
                # Ignore startup/reconnection events (old_state None or unavailable)
                # so that HA restoring state while the gate entity comes online does
                # not silently satisfy the gate without a genuine state transition.
                if old_state is None or old_state.state in ("unavailable", "unknown"):
                    return
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
# WeeklyTrigger
# ═══════════════════════════════════════════════════════════════════════


class WeeklyTrigger(BaseTrigger):
    """Trigger that fires at specific times on specific weekdays.

    Each schedule entry pairs a weekday with a time. The trigger fires at the
    configured time only on the matching weekday.

    Without gate: scheduled time reached on matching day -> done immediately.
    With gate: scheduled time reached -> active (pending), gate met -> done.
    """

    trigger_type = TriggerType.WEEKLY

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        # Parse schedule: list of (weekday_int, time) tuples
        self._schedule: list[tuple[int, time]] = []
        for entry in config["schedule"]:
            day_int = WEEKDAY_MAP[entry["day"]]
            time_val = entry["time"]
            if isinstance(time_val, str):
                parts = time_val.split(":")
                t = time(int(parts[0]), int(parts[1]))
            else:
                t = time_val
            self._schedule.append((day_int, t))

        gate = config.get("gate")
        self._gate_entity: str | None = gate.get("entity_id") if gate else None
        self._gate_state: str | None = gate.get("state") if gate else None
        self._has_gate: bool = self._gate_entity is not None
        self._time_fired_today: bool = False

    @property
    def schedule(self) -> list[tuple[int, time]]:
        """Return the configured schedule as (weekday, time) pairs."""
        return self._schedule

    @property
    def has_gate(self) -> bool:
        return self._has_gate

    @property
    def next_trigger_datetime(self) -> datetime:
        """Calculate the next trigger datetime across all schedule entries."""
        now = dt_util.now()
        best: datetime | None = None
        for weekday, t in self._schedule:
            candidate = now.replace(
                hour=t.hour, minute=t.minute, second=0, microsecond=0,
            )
            # Adjust to the correct weekday
            days_ahead = weekday - now.weekday()
            if days_ahead < 0:
                days_ahead += 7
            candidate += timedelta(days=days_ahead)
            # If same day but time already passed, move to next week
            if candidate <= now:
                candidate += timedelta(days=7)
            if best is None or candidate < best:
                best = candidate
        # Should never be None since schedule is non-empty, but guard anyway
        if best is None:
            return now + timedelta(days=1)
        return best

    def _todays_trigger_time(self, now: datetime) -> time | None:
        """Return the scheduled trigger time for today, or None."""
        current_day = now.weekday()
        for weekday, t in self._schedule:
            if weekday == current_day:
                return t
        return None

    def _reset_internal(self) -> None:
        self._time_fired_today = False

    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        # Group schedule entries by time so we register one listener per unique time
        times_to_days: dict[time, set[int]] = {}
        for weekday, t in self._schedule:
            times_to_days.setdefault(t, set()).add(weekday)

        for trigger_time, valid_days in times_to_days.items():

            @callback
            def _handle_time(now: datetime, _days: set[int] = valid_days) -> None:
                if self._state != SubState.IDLE:
                    return
                if now.weekday() not in _days:
                    return
                self._time_fired_today = True
                if self._has_gate:
                    if self._is_gate_met(hass):
                        self.set_state(SubState.DONE)
                    else:
                        self.set_state(SubState.ACTIVE)
                else:
                    self.set_state(SubState.DONE)
                on_state_change()

            unsub_time = async_track_time_change(
                hass, _handle_time,
                hour=trigger_time.hour, minute=trigger_time.minute, second=0,
            )
            self._listeners.append(unsub_time)

        # Gate entity listener (if configured)
        if self._gate_entity:

            @callback
            def _handle_gate(event: Event) -> None:
                if self._state != SubState.ACTIVE:
                    return
                new_state = event.data.get("new_state")
                old_state = event.data.get("old_state")
                if old_state is None or old_state.state in ("unavailable", "unknown"):
                    return
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
        """Check if we've passed a scheduled trigger time today (handles startup)."""
        if self._state == SubState.IDLE and not self._time_fired_today:
            now = dt_util.now()
            trigger_time = self._todays_trigger_time(now)
            if trigger_time is not None:
                today_trigger = now.replace(
                    hour=trigger_time.hour,
                    minute=trigger_time.minute,
                    second=0,
                    microsecond=0,
                )
                if now >= today_trigger:
                    self._time_fired_today = True
                    if self._has_gate:
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
            "schedule": [
                {
                    "day": WEEKDAY_SHORT_NAMES[weekday],
                    "time": t.isoformat(),
                }
                for weekday, t in self._schedule
            ],
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
# DurationTrigger
# ═══════════════════════════════════════════════════════════════════════


class DurationTrigger(BaseTrigger):
    """Trigger that fires after an entity has been in a target state for a duration.

    Active: entity is in the target state but required duration has not yet elapsed.
    Done: entity has remained in the target state for >= duration_hours.

    If the entity leaves the target state before the duration elapses, the
    trigger resets to idle and the timer restarts next time it enters the state.

    The ``_state_since`` timestamp is persisted so that the timer survives
    HA restarts.  Transitions through ``unavailable`` / ``unknown`` (common
    during reboots) are ignored so the timer is not accidentally cleared.
    """

    trigger_type = TriggerType.DURATION

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._entity_id: str = config["entity_id"]
        self._target_state: str = config.get("state", "on")
        self._duration_hours: float = config["duration_hours"]
        self._state_since: datetime | None = None

        gate = config.get("gate")
        self._gate_entity: str | None = gate.get("entity_id") if gate else None
        self._gate_state: str | None = gate.get("state") if gate else None
        self._has_gate: bool = self._gate_entity is not None
        self._duration_elapsed: bool = False

    def _reset_internal(self) -> None:
        self._state_since = None
        self._duration_elapsed = False

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

            # Ignore startup/reconnection events where old state is absent
            # or transitional, so a reboot's unavailable→on sequence does
            # not re-record _state_since and lose the persisted timestamp.
            if old_val is None or old_val in ("unavailable", "unknown"):
                return
            # Ignore transient unavailability — do not clear the timer.
            if new_val in ("unavailable", "unknown"):
                return
            # Ignore attribute-only changes (state value unchanged).
            if old_val == new_val:
                return

            if new_val == self._target_state and self._state == SubState.IDLE:
                self._state_since = dt_util.utcnow()
                self.set_state(SubState.ACTIVE)
                on_state_change()
            elif new_val != self._target_state and self._state == SubState.ACTIVE and not self._duration_elapsed:
                self._state_since = None
                self.set_state(SubState.IDLE)
                on_state_change()

        unsub = async_track_state_change_event(
            hass, [self._entity_id], _handle_state_change
        )
        self._listeners.append(unsub)

        # Gate entity listener (if configured)
        if self._gate_entity:

            @callback
            def _handle_gate(event: Event) -> None:
                if self._state != SubState.ACTIVE or not self._duration_elapsed:
                    return
                new_state = event.data.get("new_state")
                old_state = event.data.get("old_state")
                if old_state is None or old_state.state in ("unavailable", "unknown"):
                    return
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
        """Check duration timer on every poll.

        Also handles startup recovery: if HA starts while the entity is
        already in the target state, the trigger transitions to ACTIVE
        and honours a persisted ``_state_since`` if available.
        """
        now = dt_util.utcnow()

        if self._state == SubState.IDLE:
            state = hass.states.get(self._entity_id)
            if (
                state
                and state.state not in ("unknown", "unavailable")
                and state.state == self._target_state
            ):
                # Use persisted timestamp when available (restored after restart);
                # fall back to now for a fresh start.
                self._state_since = self._state_since or now
                self.set_state(SubState.ACTIVE)

        if self._state == SubState.ACTIVE and self._state_since is not None:
            if not self._duration_elapsed:
                # Safety check — if the entity somehow left the target state
                # between polls (and the listener missed it), reset. Treat
                # unavailable/unknown as "still in target state" so transient
                # connectivity blips don't clear the timer.
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
                        self._duration_elapsed = True
                        if self._has_gate:
                            if self._is_gate_met(hass):
                                self.set_state(SubState.DONE)
                            # else stay ACTIVE (pending) until gate is met
                        else:
                            self.set_state(SubState.DONE)
            elif self._has_gate:
                # Duration already elapsed, waiting for gate
                if self._is_gate_met(hass):
                    self.set_state(SubState.DONE)

        return self._state

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        state = hass.states.get(self._entity_id)
        attrs: dict[str, Any] = {
            "trigger_type": self.trigger_type.value,
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
        if self._gate_entity:
            gate_state = hass.states.get(self._gate_entity)
            attrs["gate_entity"] = self._gate_entity
            attrs["gate_expected_state"] = self._gate_state
            attrs["gate_current_state"] = gate_state.state if gate_state else None
            attrs["gate_met"] = self._is_gate_met(hass)
        return attrs

    def _snapshot_internal(self) -> dict[str, Any]:
        return {
            "state_since": self._state_since.isoformat() if self._state_since else None,
            "duration_elapsed": self._duration_elapsed,
        }

    def _restore_internal(self, data: dict[str, Any]) -> None:
        ss = data.get("state_since")
        self._state_since = dt_util.parse_datetime(ss) if ss else None
        self._duration_elapsed = data.get("duration_elapsed", False)


# ═══════════════════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════════════════

TRIGGER_FACTORY: dict[str, type[BaseTrigger]] = {
    TriggerType.POWER_CYCLE: PowerCycleTrigger,
    TriggerType.STATE_CHANGE: StateChangeTrigger,
    TriggerType.DAILY: DailyTrigger,
    TriggerType.WEEKLY: WeeklyTrigger,
    TriggerType.DURATION: DurationTrigger,
}


def create_trigger(config: dict[str, Any]) -> BaseTrigger:
    """Create a trigger instance from configuration."""
    trigger_type = config["type"]
    cls = TRIGGER_FACTORY.get(trigger_type)
    if cls is None:
        raise ValueError(f"Unknown trigger type: {trigger_type}")
    return cls(config)

