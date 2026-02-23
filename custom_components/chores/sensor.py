"""Sensor entities for the Chores integration.

Creates:
  - ChoreStateSensor: main state machine (inactive/pending/due/started/completed)
  - TriggerProgressSensor: trigger sub-state (idle/active/done) — optional
  - CompletionProgressSensor: completion sub-state (idle/active/done) — optional
  - ResetProgressSensor: reset status (idle/waiting) with next_reset_at etc.
  - LastCompletedSensor: diagnostic timestamp of last completion
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .chore_core import Chore
from .const import (
    ATTR_CHORE_ID,
    DOMAIN,
    SERVICE_FORCE_COMPLETE,
    SERVICE_FORCE_DUE,
    SERVICE_FORCE_INACTIVE,
    ChoreState,
    CompletionType,
    SubState,
    TriggerType,
)
from .coordinator import ChoresCoordinator
_LOGGER = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Detector sensor defaults registry
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class DetectorSensorDefaults:
    """Default name and icons for a detector progress sensor."""

    name: str | None  # None means dynamic (computed from detector config)
    icon_idle: str
    icon_active: str
    icon_done: str


DETECTOR_SENSOR_DEFAULTS: dict[str, DetectorSensorDefaults] = {
    # Trigger-primary detectors
    "power_cycle": DetectorSensorDefaults(
        "Power Monitor", "mdi:power-plug-off", "mdi:power-plug", "mdi:power-plug-outline",
    ),
    "state_change": DetectorSensorDefaults(
        "State Monitor", "mdi:toggle-switch-off-outline", "mdi:toggle-switch", "mdi:check-circle-outline",
    ),
    "daily": DetectorSensorDefaults(
        None, "mdi:calendar-clock", "mdi:calendar-alert", "mdi:calendar-check",
    ),
    "weekly": DetectorSensorDefaults(
        None, "mdi:calendar-week", "mdi:calendar-alert", "mdi:calendar-check",
    ),
    "duration": DetectorSensorDefaults(
        "Duration Monitor", "mdi:timer-off-outline", "mdi:timer-sand", "mdi:timer-check-outline",
    ),
    # Completion-primary detectors
    "contact": DetectorSensorDefaults(
        "Contact", "mdi:door-closed", "mdi:door-open", "mdi:check-circle",
    ),
    "contact_cycle": DetectorSensorDefaults(
        "Contact Cycle", "mdi:door-closed", "mdi:door-open", "mdi:door-closed-lock",
    ),
    "presence_cycle": DetectorSensorDefaults(
        "Presence", "mdi:home", "mdi:home-export-outline", "mdi:home-import-outline",
    ),
    "sensor_state": DetectorSensorDefaults(
        "Sensor State", "mdi:eye-off-outline", "mdi:eye", "mdi:check-circle",
    ),
    "sensor_threshold": DetectorSensorDefaults(
        "Sensor Threshold", "mdi:gauge-empty", "mdi:gauge", "mdi:gauge-full",
    ),
}

_TRIGGER_FALLBACK = DetectorSensorDefaults(
    "Trigger Detector", "mdi:help-circle-outline", "mdi:alert-circle-outline", "mdi:check-circle-outline",
)
_COMPLETION_FALLBACK = DetectorSensorDefaults(
    "Completion Detector", "mdi:checkbox-blank-outline", "mdi:checkbox-marked-circle-outline", "mdi:check-circle",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities."""
    coordinator: ChoresCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities: list[SensorEntity] = []

    for chore in coordinator.chores.values():
        # Main state machine sensor (always created)
        entities.append(ChoreStateSensor(coordinator, chore, entry))

        # Trigger progress sensor (always created; sensor: block overrides defaults)
        entities.append(TriggerProgressSensor(coordinator, chore, entry))

        # Completion progress sensor (always created except for manual, which has
        # no sensor-detectable progress; sensor: block overrides defaults)
        if chore.completion.completion_type != CompletionType.MANUAL:
            entities.append(CompletionProgressSensor(coordinator, chore, entry))

        # Reset progress sensor (always created)
        entities.append(ResetProgressSensor(coordinator, chore, entry))

        # Last completed diagnostic sensor (always created)
        entities.append(LastCompletedSensor(coordinator, chore, entry))

    async_add_entities(entities)

    # Register entity services on the main sensor
    platform = async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_FORCE_DUE,
        {},
        "async_force_due",
    )
    platform.async_register_entity_service(
        SERVICE_FORCE_INACTIVE,
        {},
        "async_force_inactive",
    )
    platform.async_register_entity_service(
        SERVICE_FORCE_COMPLETE,
        {},
        "async_force_complete",
    )


# ═══════════════════════════════════════════════════════════════════════
# ChoreStateSensor (main state machine)
# ═══════════════════════════════════════════════════════════════════════


class ChoreStateSensor(CoordinatorEntity[ChoresCoordinator], SensorEntity):
    """Main chore state machine sensor."""

    _attr_has_entity_name = True
    _attr_translation_key = "chore_state"

    def __init__(
        self,
        coordinator: ChoresCoordinator,
        chore: Chore,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._chore = chore
        self._attr_unique_id = f"{DOMAIN}_{chore.id}"
        self._attr_name = "Chore"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, chore.id)},
        )
        self._attr_options = [s.value for s in ChoreState]
        self._attr_device_class = SensorDeviceClass.ENUM

    @property
    def icon(self) -> str:
        return self._chore.icon

    @property
    def native_value(self) -> str:
        return self._chore.state.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._chore.to_state_dict(self.coordinator.hass)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    # ── Entity services ─────────────────────────────────────────────

    async def async_force_due(self) -> None:
        """Force chore to due."""
        await self.coordinator.async_force_due(self._chore.id)

    async def async_force_inactive(self) -> None:
        """Force chore to inactive."""
        await self.coordinator.async_force_inactive(self._chore.id)

    async def async_force_complete(self) -> None:
        """Force chore to completed."""
        await self.coordinator.async_force_complete(self._chore.id)


# ═══════════════════════════════════════════════════════════════════════
# DetectorProgressSensor (shared base for trigger/completion progress)
# ═══════════════════════════════════════════════════════════════════════


class DetectorProgressSensor(CoordinatorEntity[ChoresCoordinator], SensorEntity):
    """Base class for trigger and completion progress sensors.

    Uses the DETECTOR_SENSOR_DEFAULTS registry for default names and icons,
    with support for dynamic names (daily/weekly) and YAML sensor: overrides.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ChoresCoordinator,
        chore: Chore,
        entry: ConfigEntry,
        *,
        stage: Any,
        suffix: str,
        fallback: DetectorSensorDefaults,
    ) -> None:
        super().__init__(coordinator)
        self._chore = chore
        self._stage = stage
        sensor_cfg = stage.sensor_config or {}
        self._attr_unique_id = f"{DOMAIN}_{chore.id}_{suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, chore.id)},
        )
        self._attr_options = [s.value for s in SubState]
        self._attr_device_class = SensorDeviceClass.ENUM

        # Look up defaults from registry for icons, with fallback
        detector_type = stage.detector_type.value
        defaults = DETECTOR_SENSOR_DEFAULTS.get(detector_type, fallback)

        # Name: always use fallback default unless YAML sensor: block overrides
        self._attr_name = sensor_cfg.get("name", fallback.name)
        self._icon_idle = sensor_cfg.get("icon_idle", defaults.icon_idle)
        self._icon_active = sensor_cfg.get("icon_active", defaults.icon_active)
        self._icon_done = sensor_cfg.get("icon_done", defaults.icon_done)

    @property
    def native_value(self) -> str:
        return self._stage.state.value

    @property
    def icon(self) -> str | None:
        state = self._stage.state
        if state == SubState.IDLE:
            return self._icon_idle
        if state == SubState.ACTIVE:
            return self._icon_active
        if state == SubState.DONE:
            return self._icon_done
        return self._icon_idle

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._stage.extra_attributes(self.coordinator.hass)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


# ═══════════════════════════════════════════════════════════════════════
# TriggerProgressSensor
# ═══════════════════════════════════════════════════════════════════════


class TriggerProgressSensor(DetectorProgressSensor):
    """Trigger progress sub-sensor (idle/active/done)."""

    def __init__(
        self,
        coordinator: ChoresCoordinator,
        chore: Chore,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            coordinator, chore, entry,
            stage=chore.trigger,
            suffix="trigger",
            fallback=_TRIGGER_FALLBACK,
        )


# ═══════════════════════════════════════════════════════════════════════
# CompletionProgressSensor
# ═══════════════════════════════════════════════════════════════════════


class CompletionProgressSensor(DetectorProgressSensor):
    """Completion progress sub-sensor (idle/active/done)."""

    def __init__(
        self,
        coordinator: ChoresCoordinator,
        chore: Chore,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            coordinator, chore, entry,
            stage=chore.completion,
            suffix="completion",
            fallback=_COMPLETION_FALLBACK,
        )


# ═══════════════════════════════════════════════════════════════════════
# ResetProgressSensor
# ═══════════════════════════════════════════════════════════════════════


class ResetProgressSensor(CoordinatorEntity[ChoresCoordinator], SensorEntity):
    """Reset progress sensor — shows idle/waiting and reset attributes."""

    _attr_has_entity_name = True
    _attr_translation_key = "reset_progress"

    # Native value is a simple two-value enum: "idle" or "waiting".
    # "idle"    = chore is not completed, reset has nothing to do.
    # "waiting" = chore is completed, counting down / waiting for reset.
    _RESET_STATES = ["idle", "waiting"]

    def __init__(
        self,
        coordinator: ChoresCoordinator,
        chore: Chore,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._chore = chore
        self._attr_unique_id = f"{DOMAIN}_{chore.id}_reset"
        self._attr_name = "Reset Detector"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, chore.id)},
        )
        self._attr_options = self._RESET_STATES
        self._attr_device_class = SensorDeviceClass.ENUM

    @property
    def native_value(self) -> str:
        if self._chore.state == ChoreState.COMPLETED:
            return "waiting"
        return "idle"

    @property
    def icon(self) -> str:
        if self._chore.state == ChoreState.COMPLETED:
            return "mdi:timer-sand"
        return "mdi:restart"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        completed_at = (
            self._chore.state_entered_at
            if self._chore.state == ChoreState.COMPLETED
            else None
        )
        return self._chore.reset_handler.extra_attributes(completed_at)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


# ═══════════════════════════════════════════════════════════════════════
# LastCompletedSensor (diagnostic)
# ═══════════════════════════════════════════════════════════════════════


class LastCompletedSensor(CoordinatorEntity[ChoresCoordinator], SensorEntity):
    """Diagnostic sensor showing last completion timestamp."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: ChoresCoordinator,
        chore: Chore,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._chore = chore
        self._attr_unique_id = f"{DOMAIN}_{chore.id}_last_completed"
        self._attr_name = "Last Completed"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, chore.id)},
        )

    @property
    def icon(self) -> str:
        return "mdi:history"

    @property
    def native_value(self) -> datetime | None:
        return self._chore.last_completed

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        now = dt_util.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = now - timedelta(days=7)

        return {
            "completed_by": self._chore.last_completed_by(),
            "completion_count_today": self._chore.completion_count_since(today_start),
            "completion_count_7d": self._chore.completion_count_since(week_ago),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
