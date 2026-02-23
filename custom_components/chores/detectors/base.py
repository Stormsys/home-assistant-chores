"""Base detector class for the Chores integration.

A detector encapsulates pure detection logic: it watches HA entities
(or the clock) and transitions through idle -> active -> done.

Detectors do NOT handle:
- Enable/disable gating (that's CompletionStage's job)
- Gate conditions (that's Gate + the stage wrapper's job)
- Steps tracking (that's CompletionStage's job)
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from ..const import DetectorType, SubState

_LOGGER = logging.getLogger(__name__)


class BaseDetector(ABC):
    """Abstract base class for all detector types."""

    detector_type: DetectorType
    steps_total: int = 1  # 1 for single-step, 2 for multi-step (e.g. contact_cycle)

    def __init__(self, config: dict[str, Any]) -> None:
        self._state: SubState = SubState.IDLE
        self._state_entered_at: datetime = dt_util.utcnow()
        self._sensor_config: dict[str, Any] | None = config.get("sensor")
        self._listeners: list[CALLBACK_TYPE] = []

    @classmethod
    def supported_stages(cls) -> frozenset[str]:
        """Return which stages this detector supports: 'trigger', 'completion'."""
        return frozenset({"trigger", "completion"})

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
        """Set the detector state. Returns True if changed."""
        if new_state == self._state:
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
        """Reset internal tracking state."""

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

        Default implementation returns current state. Override for detectors
        that need time-based evaluation (e.g. cooldown timers).
        """
        return self._state

    # ── Enable-time check ───────────────────────────────────────────

    def check_immediate(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        """Check if detection condition is already met.

        Called by CompletionStage.enable() to handle the case where the
        sensor value already satisfies the condition when the chore becomes
        due.  Default: no-op.  Override in detectors like SensorThreshold.
        """

    # ── Attributes for progress sensor ──────────────────────────────

    @abstractmethod
    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        """Return extra state attributes for the progress sensor."""

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
        """Return detector-specific state for persistence."""

    def restore_state(self, data: dict[str, Any]) -> None:
        """Restore state from persistence."""
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
