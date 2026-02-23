"""Manual detector for the Chores integration."""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback

from ..const import DetectorType
from .base import BaseDetector


class ManualDetector(BaseDetector):
    """No automatic detection -- completed only via force_complete."""

    detector_type = DetectorType.MANUAL

    @classmethod
    def supported_stages(cls) -> frozenset[str]:
        return frozenset({"completion"})

    def _reset_internal(self) -> None:
        pass

    def async_setup_listeners(
        self, hass: HomeAssistant, on_state_change: callback
    ) -> None:
        pass

    def extra_attributes(self, hass: HomeAssistant) -> dict[str, Any]:
        return {
            "detector_type": self.detector_type.value,
            "state_entered_at": self._state_entered_at.isoformat(),
        }

    def _snapshot_internal(self) -> dict[str, Any]:
        return {}

    def _restore_internal(self, data: dict[str, Any]) -> None:
        pass
