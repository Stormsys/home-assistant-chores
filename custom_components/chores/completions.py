"""Completion stage wrapper for the Chores integration.

CompletionStage composes a generic detector (from detectors/) with
enable/disable gating, steps tracking, and an optional Gate (from gate.py)
to form the completion component of a Chore.

Stage-specific behavior:
- Enable/disable: completions only fire when enabled (chore is due/started).
- Steps tracking: steps_done is derived from detector state.
- check_immediate: delegates to detector for enable-time checks.
- Gate holding: same pattern as TriggerStage.

The old BaseCompletion/SensorStateCompletion/ContactCompletion etc. classes
are replaced by this single wrapper.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant, callback

from .const import CompletionType, DetectorType, SubState
from .detectors import BaseDetector, create_detector
from .gate import Gate

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "CompletionStage",
    "BaseCompletion",
    "create_completion",
]


class CompletionStage:
    """Stage wrapper for completion detection.

    Composes a detector instance with enable/disable gating, steps
    tracking, and an optional Gate.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._detector: BaseDetector = create_detector(config)
        self._gate: Gate | None = None
        if config.get("gate"):
            self._gate = Gate(config["gate"])
        self._gate_holding: bool = False
        self._enabled: bool = False
        self._steps_done: int = 0
        # Stored during setup so enable() can delegate check_immediate
        self._hass: HomeAssistant | None = None
        self._on_detector_change_ref: callback | None = None

    # ── Properties ──────────────────────────────────────────────────

    @property
    def detector(self) -> BaseDetector:
        """Access the underlying detector."""
        return self._detector

    @property
    def completion_type(self) -> CompletionType:
        """Backwards-compat completion type enum."""
        return CompletionType(self._detector.detector_type.value)

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
    def steps_done(self) -> int:
        return self._steps_done

    @property
    def steps_total(self) -> int:
        return self._detector.steps_total

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def has_gate(self) -> bool:
        return self._gate is not None

    # ── Enable/Disable ──────────────────────────────────────────────

    def enable(self) -> None:
        """Enable listening for completion events.

        Resets the detector to IDLE first, clearing any events that fired
        while the completion was disabled (chore not yet due).  Then runs
        check_immediate for detectors that support it (e.g. sensor_threshold)
        to handle the case where the condition is already met.
        """
        self._enabled = True
        self._detector.reset()
        self._steps_done = 0
        # Delegate check_immediate for detectors that support it
        if self._hass and self._on_detector_change_ref:
            self._detector.check_immediate(self._hass, self._on_detector_change_ref)
        self._update_steps()

    def disable(self) -> None:
        """Disable listening."""
        self._enabled = False

    # ── State management ────────────────────────────────────────────

    def _update_steps(self) -> None:
        """Sync steps_done with detector state."""
        if self._detector.state == SubState.ACTIVE:
            self._steps_done = 1
        elif self._detector.state == SubState.DONE:
            self._steps_done = self._detector.steps_total
        else:
            self._steps_done = 0

    def set_state(self, new_state: SubState) -> bool:
        """Set detector state directly (used by force actions)."""
        if new_state == SubState.DONE:
            self._gate_holding = False
        result = self._detector.set_state(new_state)
        self._update_steps()
        return result

    def reset(self) -> None:
        """Reset completion to idle."""
        self._gate_holding = False
        self._enabled = False
        self._steps_done = 0
        self._detector.reset()

    # ── Listener management ─────────────────────────────────────────

    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        """Set up listeners for the detector and optional gate."""
        self._hass = hass

        @callback
        def _on_detector_change() -> None:
            """Intercept detector state changes to apply enable/gate logic."""
            if not self._enabled:
                return
            self._update_steps()
            if self._detector.state == SubState.DONE and self._gate is not None:
                if self._gate.is_met(hass):
                    self._gate_holding = False
                else:
                    self._gate_holding = True
            else:
                self._gate_holding = False
            on_state_change()

        self._on_detector_change_ref = _on_detector_change
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
        if not self._enabled:
            return self.state

        old_state = self._detector.state
        self._detector.evaluate(hass)

        # If detector just transitioned to DONE, apply gate logic
        if self._detector.state == SubState.DONE and old_state != SubState.DONE:
            if self._gate is not None and not self._gate.is_met(hass):
                self._gate_holding = True

        # If holding for gate, check if gate is now met
        if self._gate_holding and self._gate is not None and self._gate.is_met(hass):
            self._gate_holding = False

        self._update_steps()
        return self.state

    # ── Attributes ───────────────────────────────────────────────────

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        """Return attributes for the progress sensor."""
        attrs = self._detector.extra_attributes(hass)
        # Remap detector_type -> completion_type for backwards compat
        if "detector_type" in attrs:
            attrs["completion_type"] = attrs.pop("detector_type")
        attrs["steps_total"] = self.steps_total
        attrs["steps_done"] = self._steps_done
        if self._gate:
            attrs.update(self._gate.extra_attributes(hass))
        return attrs

    # ── Persistence ──────────────────────────────────────────────────

    def snapshot_state(self) -> dict[str, Any]:
        """Return state for persistence."""
        data = self._detector.snapshot_state()
        data["steps_done"] = self._steps_done
        data["enabled"] = self._enabled
        data["gate_holding"] = self._gate_holding
        return data

    def restore_state(self, data: dict[str, Any]) -> None:
        """Restore state from persistence."""
        self._detector.restore_state(data)
        self._steps_done = data.get("steps_done", 0)
        self._enabled = data.get("enabled", False)
        self._gate_holding = data.get("gate_holding", False)


# Backwards-compat alias for type hints in other modules
BaseCompletion = CompletionStage


def create_completion(config: dict[str, Any]) -> CompletionStage:
    """Create a completion stage from configuration."""
    if not config or config.get("type") is None:
        config = {"type": "manual"}
    return CompletionStage(config)
