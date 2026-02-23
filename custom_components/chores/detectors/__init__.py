"""Generic detector types for the Chores integration.

Each detector monitors external conditions and transitions through:
    idle -> active (optional) -> done

Detectors are stage-agnostic -- they contain pure detection logic.
Stage-specific behavior (enable/disable for completions, gate wrapping)
is added by TriggerStage and CompletionStage wrappers in triggers.py
and completions.py.

Adding a new detector: create a module in this package, subclass
BaseDetector, implement the abstract methods, and register it in
DETECTOR_REGISTRY below.
"""
from __future__ import annotations

from typing import Any

from ..const import DetectorType
from .base import BaseDetector
from .contact import ContactDetector
from .contact_cycle import ContactCycleDetector
from .daily import DailyDetector
from .duration import DurationDetector
from .helpers import WEEKDAY_MAP, WEEKDAY_SHORT_NAMES
from .manual import ManualDetector
from .power_cycle import PowerCycleDetector
from .presence_cycle import PresenceCycleDetector
from .sensor_state import SensorStateDetector
from .sensor_threshold import SensorThresholdDetector
from .state_change import StateChangeDetector
from .weekly import WeeklyDetector

__all__ = [
    "BaseDetector",
    "ContactCycleDetector",
    "ContactDetector",
    "DailyDetector",
    "DurationDetector",
    "ManualDetector",
    "PowerCycleDetector",
    "PresenceCycleDetector",
    "SensorStateDetector",
    "SensorThresholdDetector",
    "StateChangeDetector",
    "WeeklyDetector",
    "DETECTOR_REGISTRY",
    "WEEKDAY_MAP",
    "WEEKDAY_SHORT_NAMES",
    "create_detector",
]

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
    """Create a detector instance from configuration."""
    detector_type = DetectorType(config["type"])
    cls = DETECTOR_REGISTRY.get(detector_type)
    if cls is None:
        raise ValueError(f"Unknown detector type: {config['type']}")
    return cls(config)
