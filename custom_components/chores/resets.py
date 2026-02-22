"""Reset types for the Chores integration.

Resets determine when a chore transitions from 'completed' back to 'inactive'.

Adding a new reset: subclass BaseReset, implement should_reset(),
and register it in RESET_FACTORY or use create_default_reset().
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import ResetType, TriggerType

_LOGGER = logging.getLogger(__name__)


class BaseReset(ABC):
    """Abstract base class for all reset types."""

    reset_type: ResetType

    @abstractmethod
    def should_reset(self, completed_at: datetime) -> bool:
        """Return True if the chore should reset to inactive now."""

    def next_reset_at(self, completed_at: datetime) -> datetime | None:
        """Return the datetime when the reset will trigger, or None if immediate/unknown."""
        return None

    def next_scheduled_reset(self) -> datetime | None:
        """Return the next upcoming reset time regardless of chore state.

        Useful for time-based resets (daily, implicit_daily) so the sensor
        always shows when the next reset window is.  Returns None for resets
        that depend on a completion event (delay, immediate).
        """
        return None

    def extra_attributes(self, completed_at: datetime | None) -> dict[str, Any]:
        """Return extra state attributes for the reset progress sensor.

        ``completed_at`` is the timestamp the chore entered the *completed*
        state.  It is ``None`` when the chore is *not* completed (the reset
        is idle).
        """
        attrs: dict[str, Any] = {
            "reset_type": self.reset_type.value,
        }
        if completed_at is not None:
            nra = self.next_reset_at(completed_at)
        else:
            nra = self.next_scheduled_reset()

        attrs["next_reset_at"] = nra.isoformat() if nra else None
        if nra is not None:
            remaining = (nra - dt_util.now()).total_seconds()
            attrs["seconds_remaining"] = max(0, int(remaining))
        else:
            attrs["seconds_remaining"] = None
        return attrs

    def snapshot_state(self) -> dict[str, Any]:
        """Return state for persistence."""
        return {"reset_type": self.reset_type.value}

    def restore_state(self, data: dict[str, Any]) -> None:
        """Restore state from persistence (no-op for most resets)."""


# ═══════════════════════════════════════════════════════════════════════
# DelayReset
# ═══════════════════════════════════════════════════════════════════════


class DelayReset(BaseReset):
    """Reset after a fixed delay from completion.

    minutes=0 means immediate reset.
    """

    reset_type = ResetType.DELAY

    def __init__(self, minutes: int = 0) -> None:
        self._minutes = minutes

    def should_reset(self, completed_at: datetime) -> bool:
        if self._minutes <= 0:
            return True
        elapsed = (dt_util.utcnow() - completed_at).total_seconds()
        return elapsed >= self._minutes * 60

    def next_reset_at(self, completed_at: datetime) -> datetime | None:
        if self._minutes <= 0:
            return None  # immediate
        return completed_at + timedelta(minutes=self._minutes)

    def extra_attributes(self, completed_at: datetime | None) -> dict[str, Any]:
        attrs = super().extra_attributes(completed_at)
        attrs["delay_minutes"] = self._minutes
        return attrs


# ═══════════════════════════════════════════════════════════════════════
# DailyReset
# ═══════════════════════════════════════════════════════════════════════


class DailyReset(BaseReset):
    """Reset at a specific time every day.

    Once the chore is completed, it stays 'completed' until the configured
    reset time arrives, then transitions back to 'inactive'.
    """

    reset_type = ResetType.DAILY_RESET

    def __init__(self, reset_time: time) -> None:
        self._reset_time = reset_time

    def _next_occurrence_after(self, after: datetime) -> datetime:
        """Return the next occurrence of reset_time after *after*."""
        local = dt_util.as_local(after)
        candidate = local.replace(
            hour=self._reset_time.hour,
            minute=self._reset_time.minute,
            second=0,
            microsecond=0,
        )
        if local >= candidate:
            candidate += timedelta(days=1)
        return candidate

    def should_reset(self, completed_at: datetime) -> bool:
        return dt_util.now() >= self._next_occurrence_after(completed_at)

    def next_reset_at(self, completed_at: datetime) -> datetime | None:
        return self._next_occurrence_after(completed_at)

    def next_scheduled_reset(self) -> datetime | None:
        return self._next_occurrence_after(dt_util.now())

    def extra_attributes(self, completed_at: datetime | None) -> dict[str, Any]:
        attrs = super().extra_attributes(completed_at)
        attrs["reset_time"] = self._reset_time.isoformat()
        return attrs


# ═══════════════════════════════════════════════════════════════════════
# ImplicitDailyReset
# ═══════════════════════════════════════════════════════════════════════


class ImplicitDailyReset(BaseReset):
    """Reset when the next daily trigger time arrives.

    Stays 'completed' until the next occurrence of trigger_time.
    """

    reset_type = ResetType.IMPLICIT_DAILY

    def __init__(self, trigger_time: time) -> None:
        self._trigger_time = trigger_time

    def _next_occurrence_after(self, after: datetime) -> datetime:
        """Return the next occurrence of trigger_time after *after*."""
        local = dt_util.as_local(after)
        candidate = local.replace(
            hour=self._trigger_time.hour,
            minute=self._trigger_time.minute,
            second=0,
            microsecond=0,
        )
        if local >= candidate:
            candidate += timedelta(days=1)
        return candidate

    def should_reset(self, completed_at: datetime) -> bool:
        return dt_util.now() >= self._next_occurrence_after(completed_at)

    def next_reset_at(self, completed_at: datetime) -> datetime | None:
        return self._next_occurrence_after(completed_at)

    def next_scheduled_reset(self) -> datetime | None:
        return self._next_occurrence_after(dt_util.now())

    def extra_attributes(self, completed_at: datetime | None) -> dict[str, Any]:
        attrs = super().extra_attributes(completed_at)
        attrs["trigger_time"] = self._trigger_time.isoformat()
        return attrs


# ═══════════════════════════════════════════════════════════════════════
# ImplicitWeeklyReset
# ═══════════════════════════════════════════════════════════════════════


class ImplicitWeeklyReset(BaseReset):
    """Reset when the next weekly trigger schedule entry arrives.

    Stays 'completed' until the next scheduled (day, time) from the weekly
    trigger's schedule list.
    """

    reset_type = ResetType.IMPLICIT_WEEKLY

    def __init__(self, schedule: list[tuple[int, time]]) -> None:
        self._schedule = schedule

    def _next_occurrence_after(self, after: datetime) -> datetime:
        """Return the next scheduled (day, time) after *after*."""
        local = dt_util.as_local(after)
        best: datetime | None = None
        for weekday, t in self._schedule:
            candidate = local.replace(
                hour=t.hour, minute=t.minute, second=0, microsecond=0,
            )
            # Adjust to the correct weekday
            days_ahead = weekday - local.weekday()
            if days_ahead < 0:
                days_ahead += 7
            candidate += timedelta(days=days_ahead)
            # If same day but time already passed, move to next week
            if candidate <= local:
                candidate += timedelta(days=7)
            if best is None or candidate < best:
                best = candidate
        # Should never be None since schedule is non-empty
        if best is None:
            return local + timedelta(days=1)
        return best

    def should_reset(self, completed_at: datetime) -> bool:
        return dt_util.now() >= self._next_occurrence_after(completed_at)

    def next_reset_at(self, completed_at: datetime) -> datetime | None:
        return self._next_occurrence_after(completed_at)

    def next_scheduled_reset(self) -> datetime | None:
        return self._next_occurrence_after(dt_util.now())

    def extra_attributes(self, completed_at: datetime | None) -> dict[str, Any]:
        attrs = super().extra_attributes(completed_at)
        attrs["schedule_entries"] = len(self._schedule)
        return attrs


# ═══════════════════════════════════════════════════════════════════════
# ImplicitEventReset
# ═══════════════════════════════════════════════════════════════════════


class ImplicitEventReset(BaseReset):
    """Immediate reset for event-based triggers (power_cycle, state_change).

    These triggers wait for external events, so the chore goes back to
    inactive immediately after completion.
    """

    reset_type = ResetType.IMPLICIT_EVENT

    def should_reset(self, completed_at: datetime) -> bool:
        return True


# ═══════════════════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════════════════


def create_reset(config: dict[str, Any] | None, trigger_type: TriggerType, trigger_config: dict[str, Any]) -> BaseReset:
    """Create a reset instance from configuration.

    If no explicit reset config, uses sensible defaults:
      - daily triggers: ImplicitDailyReset at the trigger time
      - event-based triggers: ImplicitEventReset (immediate)
    """
    if config is not None:
        reset_type = config.get("type", "delay")
        if reset_type == "delay":
            return DelayReset(minutes=config.get("minutes", 0))
        if reset_type == "daily_reset":
            time_val = config.get("time", "00:00")
            if isinstance(time_val, str):
                parts = time_val.split(":")
                t = time(int(parts[0]), int(parts[1]))
            else:
                t = time_val
            return DailyReset(reset_time=t)

    # Default resets based on trigger type
    if trigger_type == TriggerType.DAILY:
        time_val = trigger_config.get("time", "00:00")
        if isinstance(time_val, str):
            parts = time_val.split(":")
            t = time(int(parts[0]), int(parts[1]))
        else:
            t = time_val
        return ImplicitDailyReset(trigger_time=t)

    if trigger_type == TriggerType.WEEKLY:
        from .triggers import WEEKDAY_MAP

        schedule: list[tuple[int, time]] = []
        for entry in trigger_config.get("schedule", []):
            day_int = WEEKDAY_MAP[entry["day"]]
            time_val = entry["time"]
            if isinstance(time_val, str):
                parts = time_val.split(":")
                t = time(int(parts[0]), int(parts[1]))
            else:
                t = time_val
            schedule.append((day_int, t))
        return ImplicitWeeklyReset(schedule=schedule)

    # power_cycle, state_change -> immediate reset
    return ImplicitEventReset()

