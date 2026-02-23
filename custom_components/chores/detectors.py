"""Generic detector types for the Chores integration.

Detectors are the unified building blocks for both trigger and completion
stages.  Each detector monitors external conditions (entity state, time,
power draw, etc.) and transitions through the standard sub-state machine:

    idle -> active -> done

Unlike the legacy trigger/completion classes, detectors carry no stage-
specific semantics (no gate logic, no ``_enabled`` flag).  Those concerns
are handled by the stage wrappers that compose a detector.

Adding a new detector: subclass BaseDetector, implement the abstract
methods, register it in DETECTOR_REGISTRY, and add the type to
``DetectorType`` in ``const.py``.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.util import dt as dt_util

from .const import DetectorType, SubState

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


# ═══════════════════════════════════════════════════════════════════════
# BaseDetector
# ═══════════════════════════════════════════════════════════════════════


class BaseDetector(ABC):
    """Abstract base class for all detector types.

    A detector watches a single external condition and transitions through
    ``idle -> active -> done``.  It is stage-agnostic: the same detector
    class can be used as a trigger *or* a completion depending on how the
    stage wrapper composes it.
    """

    detector_type: DetectorType
    steps_total: int = 1

    def __init__(self, config: dict[str, Any]) -> None:
        self._state: SubState = SubState.IDLE
        self._state_entered_at: datetime = dt_util.utcnow()
        self._sensor_config: dict[str, Any] | None = config.get("sensor")
        self._listeners: list[CALLBACK_TYPE] = []
        # Optional guard: when set, set_state() checks guard() before changing.
        # Used by CompletionStage to prevent state changes when disabled.
        self._guard: Any = None  # Callable[[], bool] | None

    # ── Stage compatibility ─────────────────────────────────────────

    @classmethod
    def supported_stages(cls) -> frozenset[str]:
        """Return the set of stages this detector may be used in.

        Override in subclasses that are restricted to a single stage
        (e.g. ``ManualDetector`` is completion-only, ``DailyDetector``
        is trigger-only).
        """
        return frozenset({"trigger", "completion"})

    # ── Public properties ───────────────────────────────────────────

    @property
    def state(self) -> SubState:
        """Return the current sub-state."""
        return self._state

    @property
    def state_entered_at(self) -> datetime:
        """Return the timestamp when the current sub-state was entered."""
        return self._state_entered_at

    @property
    def sensor_config(self) -> dict[str, Any] | None:
        """Return the optional sensor display configuration."""
        return self._sensor_config

    @property
    def has_sensor(self) -> bool:
        """Return True if a sensor display configuration is present."""
        return self._sensor_config is not None

    # ── State management ────────────────────────────────────────────

    def set_state(self, new_state: SubState) -> bool:
        """Set the detector sub-state.  Returns True if changed (idempotent).

        If a ``_guard`` callable is set and returns ``False``, the state
        change is suppressed and this method returns ``False``.
        """
        if new_state == self._state:
            return False
        if self._guard is not None and not self._guard():
            return False
        old = self._state
        self._state = new_state
        self._state_entered_at = dt_util.utcnow()
        _LOGGER.debug("Detector %s: %s -> %s", self.detector_type, old, new_state)
        return True

    def reset(self) -> None:
        """Reset detector to idle."""
        self.set_state(SubState.IDLE)
        self._reset_internal()

    @abstractmethod
    def _reset_internal(self) -> None:
        """Reset internal tracking state (called after state set to IDLE)."""

    # ── Listener management ─────────────────────────────────────────

    @abstractmethod
    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        """Set up HA event listeners for this detector."""

    def async_remove_listeners(self) -> None:
        """Remove all registered listeners."""
        for unsub in self._listeners:
            unsub()
        self._listeners.clear()

    # ── Polling (called every coordinator update) ───────────────────

    def evaluate(self, hass: HomeAssistant) -> SubState:
        """Evaluate current state (called on every coordinator poll).

        Default implementation returns current state.  Override for
        detectors that need time-based evaluation (cooldown timers,
        duration checks, startup recovery, etc.).
        """
        return self._state

    # ── Enable-time immediate check ─────────────────────────────────

    def check_immediate(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        """Perform an immediate state check when the detector is enabled.

        Default is a no-op.  Override in detectors that need to inspect
        the current entity value at the moment the stage wrapper enables
        them (e.g. ``SensorThresholdDetector`` checks whether the
        threshold is already met).
        """

    # ── Attributes for progress sensor ──────────────────────────────

    @abstractmethod
    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        """Return extra state attributes for the progress sensor."""

    # ── Persistence ─────────────────────────────────────────────────

    def snapshot_state(self) -> dict[str, Any]:
        """Return full state dict for persistence."""
        return {
            "state": self._state.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            **self._snapshot_internal(),
        }

    @abstractmethod
    def _snapshot_internal(self) -> dict[str, Any]:
        """Return detector-specific state for persistence."""

    def restore_state(self, data: dict[str, Any]) -> None:
        """Restore state from a persisted dict."""
        if "state" in data:
            self._state = SubState(data["state"])
        if "state_entered_at" in data:
            self._state_entered_at = (
                dt_util.parse_datetime(data["state_entered_at"]) or dt_util.utcnow()
            )
        self._restore_internal(data)

    @abstractmethod
    def _restore_internal(self, data: dict[str, Any]) -> None:
        """Restore detector-specific state from persistence."""


# ═══════════════════════════════════════════════════════════════════════
# PowerCycleDetector
# ═══════════════════════════════════════════════════════════════════════


class PowerCycleDetector(BaseDetector):
    """Detector that senses power/current cycles.

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
        Returns None when all configured sensors are unavailable/unknown --
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
        """Evaluate power state and update detector."""
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
                # Power dropped below threshold -- start cooldown
                self._power_dropped_at = now
        # above is None: all sensors unavailable -- hold current state, do not
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
            "power_dropped_at": (
                self._power_dropped_at.isoformat() if self._power_dropped_at else None
            ),
        }

    def _restore_internal(self, data: dict[str, Any]) -> None:
        self._machine_running = data.get("machine_running", False)
        pda = data.get("power_dropped_at")
        self._power_dropped_at = dt_util.parse_datetime(pda) if pda else None


# ═══════════════════════════════════════════════════════════════════════
# StateChangeDetector
# ═══════════════════════════════════════════════════════════════════════


class StateChangeDetector(BaseDetector):
    """Detector that fires on an entity state transition.

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


# ═══════════════════════════════════════════════════════════════════════
# DailyDetector
# ═══════════════════════════════════════════════════════════════════════


class DailyDetector(BaseDetector):
    """Detector that fires at a specific time each day.

    Time reached -> done immediately (no gate logic; gate handling is
    the responsibility of the stage wrapper).
    """

    detector_type = DetectorType.DAILY

    @classmethod
    def supported_stages(cls) -> frozenset[str]:
        """Daily detection is trigger-only."""
        return frozenset({"trigger"})

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        time_val = config["time"]
        if isinstance(time_val, str):
            parts = time_val.split(":")
            self._time: time = time(int(parts[0]), int(parts[1]))
        else:
            self._time = time_val

        self._time_fired_today: bool = False

    @property
    def trigger_time(self) -> time:
        """Return the configured daily trigger time."""
        return self._time

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
        @callback
        def _handle_time(now: datetime) -> None:
            if self._state != SubState.IDLE:
                return
            self._time_fired_today = True
            self.set_state(SubState.DONE)
            on_state_change()

        unsub_time = async_track_time_change(
            hass, _handle_time,
            hour=self._time.hour, minute=self._time.minute, second=0,
        )
        self._listeners.append(unsub_time)

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
                self._time_fired_today = True
                self.set_state(SubState.DONE)
        return self._state

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        return {
            "detector_type": self.detector_type.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            "trigger_time": self._time.isoformat(),
            "next_trigger": self.next_trigger_datetime.isoformat(),
            "time_fired_today": self._time_fired_today,
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {
            "time_fired_today": self._time_fired_today,
        }

    def _restore_internal(self, data: dict[str, Any]) -> None:
        self._time_fired_today = data.get("time_fired_today", False)


# ═══════════════════════════════════════════════════════════════════════
# WeeklyDetector
# ═══════════════════════════════════════════════════════════════════════


class WeeklyDetector(BaseDetector):
    """Detector that fires at specific times on specific weekdays.

    Each schedule entry pairs a weekday with a time.  The detector fires
    at the configured time only on the matching weekday.  No gate logic;
    gate handling is the responsibility of the stage wrapper.
    """

    detector_type = DetectorType.WEEKLY

    @classmethod
    def supported_stages(cls) -> frozenset[str]:
        """Weekly detection is trigger-only."""
        return frozenset({"trigger"})

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

        self._time_fired_today: bool = False

    @property
    def schedule(self) -> list[tuple[int, time]]:
        """Return the configured schedule as (weekday, time) pairs."""
        return self._schedule

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
                self.set_state(SubState.DONE)
                on_state_change()

            unsub_time = async_track_time_change(
                hass, _handle_time,
                hour=trigger_time.hour, minute=trigger_time.minute, second=0,
            )
            self._listeners.append(unsub_time)

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
                    self.set_state(SubState.DONE)
        return self._state

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        return {
            "detector_type": self.detector_type.value,
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

    def _snapshot_internal(self) -> dict[str, Any]:
        return {
            "time_fired_today": self._time_fired_today,
        }

    def _restore_internal(self, data: dict[str, Any]) -> None:
        self._time_fired_today = data.get("time_fired_today", False)


# ═══════════════════════════════════════════════════════════════════════
# DurationDetector
# ═══════════════════════════════════════════════════════════════════════


class DurationDetector(BaseDetector):
    """Detector that fires after an entity has been in a target state for a duration.

    Active: entity is in the target state but required duration has not yet elapsed.
    Done: entity has remained in the target state for >= duration_hours.

    If the entity leaves the target state before the duration elapses, the
    detector resets to idle and the timer restarts next time it enters the state.

    The ``_state_since`` timestamp is persisted so that the timer survives
    HA restarts.  Transitions through ``unavailable`` / ``unknown`` (common
    during reboots) are ignored so the timer is not accidentally cleared.

    No gate logic -- gate handling is the responsibility of the stage wrapper.
    """

    detector_type = DetectorType.DURATION

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._entity_id: str = config["entity_id"]
        self._target_state: str = config.get("state", "on")
        self._duration_hours: float = config["duration_hours"]
        self._state_since: datetime | None = None

    def _reset_internal(self) -> None:
        self._state_since = None

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
            # or transitional, so a reboot's unavailable->on sequence does
            # not re-record _state_since and lose the persisted timestamp.
            if old_val is None or old_val in ("unavailable", "unknown"):
                return
            # Ignore transient unavailability -- do not clear the timer.
            if new_val in ("unavailable", "unknown"):
                return
            # Ignore attribute-only changes (state value unchanged).
            if old_val == new_val:
                return

            if new_val == self._target_state and self._state == SubState.IDLE:
                self._state_since = dt_util.utcnow()
                self.set_state(SubState.ACTIVE)
                on_state_change()
            elif new_val != self._target_state and self._state == SubState.ACTIVE:
                # Entity left target state while duration hasn't elapsed yet
                self._state_since = None
                self.set_state(SubState.IDLE)
                on_state_change()

        unsub = async_track_state_change_event(
            hass, [self._entity_id], _handle_state_change
        )
        self._listeners.append(unsub)

    def evaluate(self, hass: HomeAssistant) -> SubState:
        """Check duration timer on every poll.

        Also handles startup recovery: if HA starts while the entity is
        already in the target state, the detector transitions to ACTIVE
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
            # Safety check -- if the entity somehow left the target state
            # between polls (and the listener missed it), reset.  Treat
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
                    self.set_state(SubState.DONE)

        return self._state

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        state = hass.states.get(self._entity_id)
        attrs: dict[str, Any] = {
            "detector_type": self.detector_type.value,
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
        return attrs

    def _snapshot_internal(self) -> dict[str, Any]:
        return {
            "state_since": self._state_since.isoformat() if self._state_since else None,
        }

    def _restore_internal(self, data: dict[str, Any]) -> None:
        ss = data.get("state_since")
        self._state_since = dt_util.parse_datetime(ss) if ss else None


# ═══════════════════════════════════════════════════════════════════════
# ManualDetector
# ═══════════════════════════════════════════════════════════════════════


class ManualDetector(BaseDetector):
    """Detector that is only completed via external action (service/button).

    Has no listeners and never transitions on its own.  The stage wrapper
    calls ``set_state(SubState.DONE)`` in response to a ``force_complete``
    service call.
    """

    detector_type = DetectorType.MANUAL

    @classmethod
    def supported_stages(cls) -> frozenset[str]:
        """Manual detection is completion-only."""
        return frozenset({"completion"})

    def _reset_internal(self) -> None:
        pass

    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        # No listeners needed -- manual completion is triggered via service/button
        pass

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        return {
            "detector_type": self.detector_type.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            "steps_total": self.steps_total,
            "steps_done": 0 if self._state == SubState.IDLE else self.steps_total,
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════
# SensorStateDetector
# ═══════════════════════════════════════════════════════════════════════


class SensorStateDetector(BaseDetector):
    """Detector that fires when an entity enters a specific state."""

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
            "steps_total": self.steps_total,
            "steps_done": 0 if self._state == SubState.IDLE else self.steps_total,
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════
# ContactDetector (single step)
# ═══════════════════════════════════════════════════════════════════════


class ContactDetector(BaseDetector):
    """Detector that fires when a contact sensor opens (single step)."""

    detector_type = DetectorType.CONTACT

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
            "detector_type": self.detector_type.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            "watched_entity": self._entity_id,
            "watched_entity_state": state.state if state else None,
            "steps_total": self.steps_total,
            "steps_done": 0 if self._state == SubState.IDLE else self.steps_total,
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════
# ContactCycleDetector (two step: open -> close)
# ═══════════════════════════════════════════════════════════════════════


class ContactCycleDetector(BaseDetector):
    """Detector for contact open then close (two-step).

    Step 1 (ACTIVE): contact sensor opens (debounced to filter bounces).
    Step 2 (DONE): contact sensor closes after being open.
    """

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

            # Ignore transitions from None/unavailable/unknown (startup or reconnection
            # events) to avoid spurious two-step completions with no real contact cycle.
            if old_state is None or old_state.state in ("unavailable", "unknown"):
                return

            if new_state.state == "on" and self._state == SubState.IDLE:
                # Contact opened -- start debounce timer for step 1.
                # If the sensor bounces back to "off" before the timer fires,
                # the pending callback is cancelled and we stay in IDLE.
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
                # Bounced back before debounce expired -- cancel step 1
                self._pending_active_cancel()
                self._pending_active_cancel = None

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
        steps_done = 0
        if self._state == SubState.ACTIVE:
            steps_done = 1
        elif self._state == SubState.DONE:
            steps_done = 2
        return {
            "detector_type": self.detector_type.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            "watched_entity": self._entity_id,
            "watched_entity_state": state.state if state else None,
            "steps_total": self.steps_total,
            "steps_done": steps_done,
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════
# PresenceCycleDetector (two step: leave -> return)
# ═══════════════════════════════════════════════════════════════════════


class PresenceCycleDetector(BaseDetector):
    """Detector for presence: leave home then return (two-step).

    Auto-detects entity domain:
      - person.* / device_tracker.*: not_home = away, home = returned
      - binary_sensor.* / others: off = away, on = returned
    """

    detector_type = DetectorType.PRESENCE_CYCLE
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
            new_state = event.data.get("new_state")
            old_state = event.data.get("old_state")
            if not new_state:
                return

            # Ignore transitions from None/unavailable/unknown (startup or reconnection
            # events) to avoid a device reconnect counting as a genuine leave+return.
            if old_state is None or old_state.state in ("unavailable", "unknown"):
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
        steps_done = 0
        if self._state == SubState.ACTIVE:
            steps_done = 1
        elif self._state == SubState.DONE:
            steps_done = 2
        return {
            "detector_type": self.detector_type.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            "watched_entity": self._entity_id,
            "watched_entity_state": state.state if state else None,
            "away_state": self._away_state,
            "home_state": self._home_state,
            "steps_total": self.steps_total,
            "steps_done": steps_done,
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════
# SensorThresholdDetector
# ═══════════════════════════════════════════════════════════════════════


class SensorThresholdDetector(BaseDetector):
    """Detector that fires when a sensor value crosses a numeric threshold.

    Single-step: idle -> done.
    Supports ``above``, ``below``, and ``equal`` operators.

    Reacts to state-change events.  The enable-time check for a pre-existing
    sensor value is handled via ``check_immediate()``, which the stage
    wrapper calls when it enables the detector.
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
        # equal
        return value == self._threshold

    def _reset_internal(self) -> None:
        pass

    def check_immediate(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        """Check if the threshold is already met at enable time."""
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
            "steps_total": self.steps_total,
            "steps_done": 0 if self._state == SubState.IDLE else self.steps_total,
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════════
# Registry & Factory
# ═══════════════════════════════════════════════════════════════════════

DETECTOR_REGISTRY: dict[DetectorType, type[BaseDetector]] = {
    DetectorType.POWER_CYCLE: PowerCycleDetector,
    DetectorType.STATE_CHANGE: StateChangeDetector,
    DetectorType.DAILY: DailyDetector,
    DetectorType.WEEKLY: WeeklyDetector,
    DetectorType.DURATION: DurationDetector,
    DetectorType.MANUAL: ManualDetector,
    DetectorType.SENSOR_STATE: SensorStateDetector,
    DetectorType.CONTACT: ContactDetector,
    DetectorType.CONTACT_CYCLE: ContactCycleDetector,
    DetectorType.PRESENCE_CYCLE: PresenceCycleDetector,
    DetectorType.SENSOR_THRESHOLD: SensorThresholdDetector,
}


def create_detector(config: dict[str, Any]) -> BaseDetector:
    """Create a detector instance from configuration.

    The configuration dict must contain a ``type`` key whose value matches
    a ``DetectorType`` enum member.
    """
    detector_type_str = config["type"]
    try:
        detector_type = DetectorType(detector_type_str)
    except ValueError as exc:
        raise ValueError(f"Unknown detector type: {detector_type_str}") from exc
    cls = DETECTOR_REGISTRY.get(detector_type)
    if cls is None:
        raise ValueError(f"No detector registered for type: {detector_type}")
    return cls(config)
