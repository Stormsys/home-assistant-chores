"""Trigger stage wrapper for the Chores integration.

TriggerStage composes a generic detector (from detectors/) with an
optional Gate (from gate.py) to form the trigger component of a Chore.

Stage-specific behavior:
- Gate holding: when the detector fires DONE but the gate condition is not
  met, the stage reports ACTIVE (pending) until the gate is satisfied.
- next_trigger_datetime: delegated to the detector for time-based types.

The old BaseTrigger/DailyTrigger/WeeklyTrigger classes are replaced by
this single wrapper.  Callers that need detector-specific properties
(e.g. trigger_time, schedule) access them via ``trigger.detector``.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant, callback

from .const import DetectorType, SubState, TriggerType
from .detectors import (
    BaseDetector,
    WEEKDAY_MAP,
    WEEKDAY_SHORT_NAMES,
    create_detector,
)
from .gate import Gate

_LOGGER = logging.getLogger(__name__)

# Re-export for backwards compat (resets.py imports WEEKDAY_MAP from triggers)
__all__ = [
    "TriggerStage",
    "BaseTrigger",
    "create_trigger",
    "WEEKDAY_MAP",
    "WEEKDAY_SHORT_NAMES",
]


class TriggerStage:
    """Stage wrapper for trigger detection.

    Composes a detector instance with an optional Gate.  Presents the
    same public API that chore_core.py, sensor.py and other modules
    expect from trigger objects.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._detector: BaseDetector = create_detector(config)
        self._gate: Gate | None = None
        if config.get("gate"):
            self._gate = Gate(config["gate"])
        self._gate_holding: bool = False

    # ── Properties ──────────────────────────────────────────────────

    @property
    def detector(self) -> BaseDetector:
        """Access the underlying detector (for type-specific properties)."""
        return self._detector

    @property
    def trigger_type(self) -> TriggerType:
        """Backwards-compat trigger type enum."""
        return TriggerType(self._detector.detector_type.value)

    @property
    def detector_type(self) -> DetectorType:
        return self._detector.detector_type

    @property
    def state(self) -> SubState:
        """Return effective state, accounting for gate holding."""
        if self._gate_holding:
            return SubState.ACTIVE
        return self._detector.state

    @property
    def state_entered_at(self) -> datetime:
        return self._detector.state_entered_at

    @property
    def sensor_config(self) -> dict[str, Any] | None:
        return self._detector.sensor_config

    @property
    def has_sensor(self) -> bool:
        return self._detector.has_sensor

    @property
    def next_trigger_datetime(self) -> datetime | None:
        """Delegate to detector if it supports this (Daily/Weekly)."""
        return getattr(self._detector, "next_trigger_datetime", None)

    @property
    def has_gate(self) -> bool:
        return self._gate is not None

    # ── State management ────────────────────────────────────────────

    def set_state(self, new_state: SubState) -> bool:
        """Set detector state directly (used by force actions)."""
        if new_state == SubState.DONE:
            # Force actions bypass gate
            self._gate_holding = False
        return self._detector.set_state(new_state)

    def reset(self) -> None:
        """Reset trigger to idle."""
        self._gate_holding = False
        self._detector.reset()

    # ── Listener management ─────────────────────────────────────────

    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        """Set up listeners for the detector and optional gate."""

        @callback
        def _on_detector_change() -> None:
            """Intercept detector state changes to apply gate logic."""
            if self._detector.state == SubState.DONE and self._gate is not None:
                if self._gate.is_met(hass):
                    self._gate_holding = False
                else:
                    self._gate_holding = True
            else:
                self._gate_holding = False
            on_state_change()

        self._detector.async_setup_listeners(hass, _on_detector_change)

        if self._gate is not None:

            @callback
            def _on_gate_met() -> None:
                """Gate entity entered expected state."""
                if self._gate_holding and self._gate.is_met(hass):
                    self._gate_holding = False
                    on_state_change()

            self._gate.async_setup_listener(hass, _on_gate_met)

    def async_remove_listeners(self) -> None:
        """Remove all registered listeners."""
        self._detector.async_remove_listeners()
        if self._gate:
            self._gate.async_remove_listeners()

    # ── Polling ──────────────────────────────────────────────────────

    def evaluate(self, hass: HomeAssistant) -> SubState:
        """Evaluate on every coordinator poll."""
        old_state = self._detector.state
        self._detector.evaluate(hass)

        # If detector just transitioned to DONE, apply gate logic
        if self._detector.state == SubState.DONE and old_state != SubState.DONE:
            if self._gate is not None and not self._gate.is_met(hass):
                self._gate_holding = True

        # If holding for gate, check if gate is now met
        if self._gate_holding and self._gate is not None and self._gate.is_met(hass):
            self._gate_holding = False

        return self.state

    # ── Attributes ───────────────────────────────────────────────────

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        """Return attributes for the progress sensor."""
        attrs = self._detector.extra_attributes(hass)
        # Remap detector_type -> trigger_type for backwards compat
        if "detector_type" in attrs:
            attrs["trigger_type"] = attrs.pop("detector_type")
        if self._gate:
            attrs.update(self._gate.extra_attributes(hass))
        return attrs

    # ── Persistence ──────────────────────────────────────────────────

    def snapshot_state(self) -> dict[str, Any]:
        """Return state for persistence."""
        data = self._detector.snapshot_state()
        data["gate_holding"] = self._gate_holding
        return data

    def restore_state(self, data: dict[str, Any]) -> None:
        """Restore state from persistence."""
        self._detector.restore_state(data)
        self._gate_holding = data.get("gate_holding", False)


# Backwards-compat alias for type hints in other modules
BaseTrigger = TriggerStage


def create_trigger(config: dict[str, Any]) -> TriggerStage:
    """Create a trigger stage from configuration."""
    return TriggerStage(config)
