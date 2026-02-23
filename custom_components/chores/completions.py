"""Completion stage wrapper for the Chores integration.

The CompletionStage wraps a generic detector for the completion role.
Unlike triggers, completions are disabled by default and only listen
when the chore is in the DUE or STARTED state.

The stage wrapper adds:
  - Enable/disable gating (detector callbacks are suppressed when disabled)
  - Steps tracking (1-step or 2-step completions)
  - Optional gate support (same as triggers)
  - ``check_immediate()`` delegation for detectors like SensorThreshold
    that need to check pre-existing state at enable time
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import CompletionType, DetectorType, SubState
from .detectors import BaseDetector, create_detector
from .gate import Gate

_LOGGER = logging.getLogger(__name__)

# Mapping from DetectorType to CompletionType for backwards compatibility
_DETECTOR_TO_COMPLETION_TYPE: dict[DetectorType, CompletionType] = {
    DetectorType.MANUAL: CompletionType.MANUAL,
    DetectorType.SENSOR_STATE: CompletionType.SENSOR_STATE,
    DetectorType.CONTACT: CompletionType.CONTACT,
    DetectorType.CONTACT_CYCLE: CompletionType.CONTACT_CYCLE,
    DetectorType.PRESENCE_CYCLE: CompletionType.PRESENCE_CYCLE,
    DetectorType.SENSOR_THRESHOLD: CompletionType.SENSOR_THRESHOLD,
}


class CompletionStage:
    """Wraps a detector for the completion role.

    Enable/disable controlled, optional gate, step tracking.
    Preserves the same public interface as the legacy ``BaseCompletion``
    for backwards compatibility.
    """

    def __init__(self, detector: BaseDetector, gate: Gate | None = None) -> None:
        self._detector = detector
        self._gate = gate
        self._gate_holding: bool = False
        self._enabled: bool = False
        self._steps_done: int = 0
        # Stored for check_immediate delegation
        self._hass: HomeAssistant | None = None
        self._on_state_change: callback | None = None

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
    def completion_type(self) -> CompletionType:
        """Backwards-compatible completion type enum value."""
        return _DETECTOR_TO_COMPLETION_TYPE.get(
            self._detector.detector_type,
            CompletionType(self._detector.detector_type.value),
        )

    @property
    def steps_total(self) -> int:
        return self._detector.steps_total

    @property
    def steps_done(self) -> int:
        return self._steps_done

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def has_gate(self) -> bool:
        return self._gate is not None

    # ── Enable / disable ──────────────────────────────────────────

    def enable(self) -> None:
        """Enable listening for completion events (called when chore becomes due)."""
        self._enabled = True
        # Update the detector guard so it allows state changes
        self._detector._guard = lambda: self._enabled
        # Delegate check_immediate to the detector (e.g. SensorThresholdDetector)
        if self._hass is not None and self._on_state_change is not None:
            self._detector.check_immediate(self._hass, self._on_state_change)

    def disable(self) -> None:
        """Disable listening (called when chore resets)."""
        self._enabled = False

    # ── State management ──────────────────────────────────────────

    def set_state(self, new_state: SubState) -> bool:
        """Set the completion state, updating steps tracking.

        Bypasses the detector guard so explicit state changes from the
        stage wrapper (e.g. ``force_complete``) always succeed.
        """
        if new_state != SubState.DONE:
            self._gate_holding = False
        saved_guard = self._detector._guard
        self._detector._guard = None
        try:
            result = self._detector.set_state(new_state)
        finally:
            self._detector._guard = saved_guard
        if result:
            if new_state == SubState.ACTIVE:
                self._steps_done = 1
            elif new_state == SubState.DONE:
                self._steps_done = self._detector.steps_total
        return result

    def reset(self) -> None:
        """Reset completion to idle."""
        self._gate_holding = False
        saved_guard = self._detector._guard
        self._detector._guard = None
        try:
            self._detector.reset()
        finally:
            self._detector._guard = saved_guard
        self._steps_done = 0
        self._enabled = False

    # ── Listener management ───────────────────────────────────────

    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        """Set up listeners with enable gating and optional gate logic."""
        self._hass = hass
        self._on_state_change = on_state_change
        # Set the guard so the detector won't change state when disabled
        self._detector._guard = lambda: self._enabled

        if self._gate:

            @callback
            def _gated_enabled_callback() -> None:
                if not self._enabled:
                    return
                if (
                    self._detector.state == SubState.DONE
                    and not self._gate.is_met(hass)
                ):
                    self._gate_holding = True
                    self._steps_done = 1
                else:
                    self._gate_holding = False
                    if self._detector.state == SubState.ACTIVE:
                        self._steps_done = 1
                    elif self._detector.state == SubState.DONE:
                        self._steps_done = self._detector.steps_total
                on_state_change()

            self._detector.async_setup_listeners(hass, _gated_enabled_callback)

            @callback
            def _on_gate_change() -> None:
                if not self._enabled:
                    return
                if (
                    self._detector.state == SubState.DONE
                    and self._gate.is_met(hass)
                ):
                    self._gate_holding = False
                    self._steps_done = self._detector.steps_total
                    on_state_change()

            self._gate.async_setup_listener(hass, _on_gate_change)
        else:

            @callback
            def _enabled_callback() -> None:
                if not self._enabled:
                    return
                if self._detector.state == SubState.ACTIVE:
                    self._steps_done = 1
                elif self._detector.state == SubState.DONE:
                    self._steps_done = self._detector.steps_total
                on_state_change()

            self._detector.async_setup_listeners(hass, _enabled_callback)

    def async_remove_listeners(self) -> None:
        """Remove all registered listeners."""
        self._detector.async_remove_listeners()
        if self._gate:
            self._gate.async_remove_listeners()

    # ── Attributes for the completion progress sensor ─────────────

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        """Return extra attributes, merging detector + gate attributes."""
        attrs = self._detector.extra_attributes(hass)
        # Rename detector_type -> completion_type for backwards compat
        if "detector_type" in attrs:
            attrs["completion_type"] = attrs.pop("detector_type")
        # Ensure steps tracking is included
        attrs["steps_total"] = self.steps_total
        attrs["steps_done"] = self._steps_done
        if self._gate:
            attrs.update(self._gate.extra_attributes(hass))
        return attrs

    # ── Persistence ───────────────────────────────────────────────

    def snapshot_state(self) -> dict[str, Any]:
        """Return state for persistence."""
        return {
            **self._detector.snapshot_state(),
            "steps_done": self._steps_done,
            "enabled": self._enabled,
        }

    def restore_state(self, data: dict[str, Any]) -> None:
        """Restore state from persistence."""
        self._detector.restore_state(data)
        self._steps_done = data.get("steps_done", 0)
        self._enabled = data.get("enabled", False)


# ═══════════════════════════════════════════════════════════════════════
# Backwards-compatibility class aliases
# ═══════════════════════════════════════════════════════════════════════
#
# The legacy completion classes (ManualCompletion, ContactCompletion, etc.)
# are replaced by the generic CompletionStage wrapping a detector.  These
# aliases allow existing code and tests to ``import ManualCompletion``
# and instantiate it with a config dict.

BaseCompletion = CompletionStage


def _make_compat_completion(config: dict[str, Any]) -> CompletionStage:
    """Internal helper: create a CompletionStage from a config dict."""
    completion_type = config.get("type", "manual")
    detector = create_detector({"type": completion_type, **config})
    gate_config = config.get("gate")
    gate = Gate(gate_config) if gate_config else None
    return CompletionStage(detector, gate)


class _CompatCompletionMeta(type):
    """Metaclass that makes ``ClassName(config)`` produce a CompletionStage."""

    _compat_type: str | None = None

    def __new__(mcs, name, bases, namespace, **kwargs):
        compat_type = kwargs.pop("compat_type", None)
        cls = super().__new__(mcs, name, bases, namespace, **kwargs)
        cls._compat_type = compat_type
        return cls

    def __init__(cls, name, bases, namespace, **kwargs):
        kwargs.pop("compat_type", None)
        super().__init__(name, bases, namespace)

    def __call__(cls, config: dict[str, Any]) -> CompletionStage:
        if cls._compat_type and "type" not in config:
            config = {"type": cls._compat_type, **config}
        return _make_compat_completion(config)

    def __instancecheck__(cls, instance):
        if not isinstance(instance, CompletionStage):
            return False
        if cls._compat_type:
            return instance.detector_type.value == cls._compat_type
        return True


class ManualCompletion(metaclass=_CompatCompletionMeta, compat_type="manual"):
    """Backwards-compatible alias for CompletionStage wrapping a ManualDetector."""


class SensorStateCompletion(metaclass=_CompatCompletionMeta, compat_type="sensor_state"):
    """Backwards-compatible alias for CompletionStage wrapping a SensorStateDetector."""


class ContactCompletion(metaclass=_CompatCompletionMeta, compat_type="contact"):
    """Backwards-compatible alias for CompletionStage wrapping a ContactDetector."""


class ContactCycleCompletion(metaclass=_CompatCompletionMeta, compat_type="contact_cycle"):
    """Backwards-compatible alias for CompletionStage wrapping a ContactCycleDetector."""


class PresenceCycleCompletion(metaclass=_CompatCompletionMeta, compat_type="presence_cycle"):
    """Backwards-compatible alias for CompletionStage wrapping a PresenceCycleDetector."""


class SensorThresholdCompletion(metaclass=_CompatCompletionMeta, compat_type="sensor_threshold"):
    """Backwards-compatible alias for CompletionStage wrapping a SensorThresholdDetector."""


# COMPLETION_FACTORY maps completion type strings to their compat classes
COMPLETION_FACTORY: dict[str, type] = {
    CompletionType.MANUAL: ManualCompletion,
    CompletionType.SENSOR_STATE: SensorStateCompletion,
    CompletionType.CONTACT: ContactCompletion,
    CompletionType.CONTACT_CYCLE: ContactCycleCompletion,
    CompletionType.PRESENCE_CYCLE: PresenceCycleCompletion,
    CompletionType.SENSOR_THRESHOLD: SensorThresholdCompletion,
}


def create_completion(config: dict[str, Any]) -> CompletionStage:
    """Create a completion stage from configuration.

    Creates the appropriate detector via ``create_detector()``, validates
    it supports the completion stage, wraps it with an optional gate, and
    returns a ``CompletionStage``.
    """
    completion_type = config.get("type", "manual")
    detector = create_detector({"type": completion_type, **config})
    if "completion" not in detector.supported_stages():
        raise ValueError(
            f"Detector type '{completion_type}' does not support the completion stage"
        )
    gate_config = config.get("gate")
    gate = Gate(gate_config) if gate_config else None
    return CompletionStage(detector, gate)
