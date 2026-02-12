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

    def should_reset(self, completed_at: datetime) -> bool:
        now = dt_util.now()
        # Calculate the next trigger time after completion
        completed_local = dt_util.as_local(completed_at)
        next_trigger = completed_local.replace(
            hour=self._trigger_time.hour,
            minute=self._trigger_time.minute,
            second=0,
            microsecond=0,
        )
        # If completed before today's trigger, next trigger is today
        # If completed after today's trigger, next trigger is tomorrow
        if completed_local >= next_trigger:
            next_trigger += timedelta(days=1)
        return now >= next_trigger


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

    # Default resets based on trigger type
    if trigger_type == TriggerType.DAILY:
        time_val = trigger_config.get("time", "00:00")
        if isinstance(time_val, str):
            parts = time_val.split(":")
            t = time(int(parts[0]), int(parts[1]))
        else:
            t = time_val
        return ImplicitDailyReset(trigger_time=t)

    # power_cycle, state_change -> immediate reset
    return ImplicitEventReset()

