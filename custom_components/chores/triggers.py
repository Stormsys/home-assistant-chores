"""Trigger stage wrapper for the Chores integration.

The TriggerStage wraps a generic detector and optionally applies gate logic.
Trigger detectors are always-on: they listen for conditions from startup
and reset after the chore completes a cycle.

Gate handling: when a gate is configured, the stage intercepts the detector's
DONE transition.  If the gate condition is not met, the stage reports ACTIVE
(chore goes PENDING) while the detector internally stays at DONE.  When the
gate entity enters the expected state, the stage releases the hold and
reports DONE (chore transitions to DUE).
"""
from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import DetectorType, SubState, TriggerType
from .detectors import (
    BaseDetector,
    DailyDetector,
    WeeklyDetector,
    create_detector,
    WEEKDAY_MAP,
    WEEKDAY_SHORT_NAMES,
)
from .gate import Gate

_LOGGER = logging.getLogger(__name__)

# Mapping from DetectorType to TriggerType for backwards compatibility
_DETECTOR_TO_TRIGGER_TYPE: dict[DetectorType, TriggerType] = {
    DetectorType.POWER_CYCLE: TriggerType.POWER_CYCLE,
    DetectorType.STATE_CHANGE: TriggerType.STATE_CHANGE,
    DetectorType.DAILY: TriggerType.DAILY,
    DetectorType.WEEKLY: TriggerType.WEEKLY,
    DetectorType.DURATION: TriggerType.DURATION,
}


class TriggerStage:
    """Wraps a detector for the trigger role.

    Always-on, optional gate.  Preserves the same public interface as the
    legacy ``BaseTrigger`` for backwards compatibility with ``chore_core.py``,
    ``sensor.py``, and ``logbook.py``.
    """

    def __init__(self, detector: BaseDetector, gate: Gate | None = None) -> None:
        self._detector = detector
        self._gate = gate
        self._gate_holding: bool = False

    # ── Delegated properties ──────────────────────────────────────

    @property
    def detector(self) -> BaseDetector:
        """Access the underlying detector (for advanced introspection)."""
        return self._detector

    @property
    def state(self) -> SubState:
        """Return the effective state, accounting for gate holds."""
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
    def detector_type(self) -> DetectorType:
        return self._detector.detector_type

    @property
    def trigger_type(self) -> TriggerType:
        """Backwards-compatible trigger type enum value."""
        return _DETECTOR_TO_TRIGGER_TYPE.get(
            self._detector.detector_type,
            TriggerType(self._detector.detector_type.value),
        )

    @property
    def has_gate(self) -> bool:
        return self._gate is not None

    @property
    def next_trigger_datetime(self) -> datetime | None:
        """For Daily/Weekly detectors, return the next scheduled trigger time."""
        if hasattr(self._detector, "next_trigger_datetime"):
            return self._detector.next_trigger_datetime
        return None

    @property
    def trigger_time(self) -> time | None:
        """For DailyDetector, return the configured trigger time."""
        if hasattr(self._detector, "trigger_time"):
            return self._detector.trigger_time
        return None

    @property
    def schedule(self) -> list[tuple[int, time]] | None:
        """For WeeklyDetector, return the configured schedule."""
        if hasattr(self._detector, "schedule"):
            return self._detector.schedule
        return None

    # ── State management ──────────────────────────────────────────

    def set_state(self, new_state: SubState) -> bool:
        """Set the stage state.  Always clears gate hold on explicit state changes."""
        self._gate_holding = False
        return self._detector.set_state(new_state)

    def reset(self) -> None:
        """Reset trigger to idle."""
        self._gate_holding = False
        self._detector.reset()

    def evaluate(self, hass: HomeAssistant) -> SubState:
        """Evaluate current state via detector + gate check.

        Called on every coordinator poll.  If the detector reaches DONE
        and a gate is configured, the gate is checked.  If the gate is
        not met, the stage holds at ACTIVE (chore goes PENDING).

        Gate holding is only engaged on *transitions* to DONE (not when
        the detector was already DONE — e.g. from an explicit set_state).
        However, once engaged, gate holding is released when the gate
        becomes met on subsequent polls.
        """
        old_detector_state = self._detector.state
        self._detector.evaluate(hass)

        if self._detector.state == SubState.DONE and self._gate is not None:
            if old_detector_state != SubState.DONE:
                # Detector just transitioned to DONE — check gate
                if not self._gate.is_met(hass):
                    self._gate_holding = True
                else:
                    self._gate_holding = False
            elif self._gate_holding and self._gate.is_met(hass):
                # Already DONE with gate holding — release if gate now met
                self._gate_holding = False

        return self.state

    # ── Listener management ───────────────────────────────────────

    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        """Set up listeners, interposing gate logic when configured."""
        if self._gate:

            @callback
            def _gated_callback() -> None:
                if self._detector.state == SubState.DONE and not self._gate.is_met(hass):
                    self._gate_holding = True
                else:
                    self._gate_holding = False
                on_state_change()

            self._detector.async_setup_listeners(hass, _gated_callback)

            @callback
            def _on_gate_change() -> None:
                if (
                    self._detector.state == SubState.DONE
                    and self._gate.is_met(hass)
                ):
                    self._gate_holding = False
                    on_state_change()

            self._gate.async_setup_listener(hass, _on_gate_change)
        else:
            self._detector.async_setup_listeners(hass, on_state_change)

    def async_remove_listeners(self) -> None:
        """Remove all registered listeners."""
        self._detector.async_remove_listeners()
        if self._gate:
            self._gate.async_remove_listeners()

    # ── Attributes for the trigger progress sensor ────────────────

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        """Return extra attributes, merging detector + gate attributes."""
        attrs = self._detector.extra_attributes(hass)
        # Rename detector_type -> trigger_type for backwards compatibility
        if "detector_type" in attrs:
            attrs["trigger_type"] = attrs.pop("detector_type")
        if self._gate:
            attrs.update(self._gate.extra_attributes(hass))
        return attrs

    # ── Persistence ───────────────────────────────────────────────

    def snapshot_state(self) -> dict[str, Any]:
        """Return state for persistence."""
        return self._detector.snapshot_state()

    def restore_state(self, data: dict[str, Any]) -> None:
        """Restore state from persistence."""
        self._detector.restore_state(data)


# ═══════════════════════════════════════════════════════════════════════
# Backwards-compatibility class aliases
# ═══════════════════════════════════════════════════════════════════════
#
# The legacy trigger classes (PowerCycleTrigger, DailyTrigger, etc.) are
# replaced by the generic TriggerStage wrapping a detector.  These
# aliases allow existing code and tests to ``import PowerCycleTrigger``
# and instantiate it with a config dict.  Each creates the appropriate
# detector internally and wraps it in a TriggerStage.

BaseTrigger = TriggerStage


def _make_compat_trigger(config: dict[str, Any]) -> TriggerStage:
    """Internal helper: create a TriggerStage from a config dict."""
    detector = create_detector(config)
    gate_config = config.get("gate")
    gate = Gate(gate_config) if gate_config else None
    return TriggerStage(detector, gate)


class _CompatTriggerMeta(type):
    """Metaclass that makes ``ClassName(config)`` produce a TriggerStage."""

    _compat_type: str | None = None

    def __new__(mcs, name, bases, namespace, **kwargs):
        compat_type = kwargs.pop("compat_type", None)
        cls = super().__new__(mcs, name, bases, namespace, **kwargs)
        cls._compat_type = compat_type
        return cls

    def __init__(cls, name, bases, namespace, **kwargs):
        kwargs.pop("compat_type", None)
        super().__init__(name, bases, namespace)

    def __call__(cls, config: dict[str, Any]) -> TriggerStage:
        # Ensure the config has the right type
        if cls._compat_type and "type" not in config:
            config = {"type": cls._compat_type, **config}
        return _make_compat_trigger(config)

    def __instancecheck__(cls, instance):
        if not isinstance(instance, TriggerStage):
            return False
        if cls._compat_type:
            return instance.detector_type.value == cls._compat_type
        return True


class PowerCycleTrigger(metaclass=_CompatTriggerMeta, compat_type="power_cycle"):
    """Backwards-compatible alias for TriggerStage wrapping a PowerCycleDetector."""


class StateChangeTrigger(metaclass=_CompatTriggerMeta, compat_type="state_change"):
    """Backwards-compatible alias for TriggerStage wrapping a StateChangeDetector."""


class DailyTrigger(metaclass=_CompatTriggerMeta, compat_type="daily"):
    """Backwards-compatible alias for TriggerStage wrapping a DailyDetector."""


class WeeklyTrigger(metaclass=_CompatTriggerMeta, compat_type="weekly"):
    """Backwards-compatible alias for TriggerStage wrapping a WeeklyDetector."""


class DurationTrigger(metaclass=_CompatTriggerMeta, compat_type="duration"):
    """Backwards-compatible alias for TriggerStage wrapping a DurationDetector."""


# TRIGGER_FACTORY maps trigger type strings to their compat classes
TRIGGER_FACTORY: dict[str, type] = {
    TriggerType.POWER_CYCLE: PowerCycleTrigger,
    TriggerType.STATE_CHANGE: StateChangeTrigger,
    TriggerType.DAILY: DailyTrigger,
    TriggerType.WEEKLY: WeeklyTrigger,
    TriggerType.DURATION: DurationTrigger,
}


def create_trigger(config: dict[str, Any]) -> TriggerStage:
    """Create a trigger stage from configuration.

    Creates the appropriate detector via ``create_detector()``, validates
    it supports the trigger stage, wraps it with an optional gate, and
    returns a ``TriggerStage``.
    """
    detector = create_detector(config)
    if "trigger" not in detector.supported_stages():
        raise ValueError(
            f"Detector type '{config['type']}' does not support the trigger stage"
        )
    gate_config = config.get("gate")
    gate = Gate(gate_config) if gate_config else None
    return TriggerStage(detector, gate)
