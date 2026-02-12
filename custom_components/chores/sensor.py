"""Sensor entities for the Chores integration.

Creates:
  - ChoreStateSensor: main state machine (inactive/pending/due/started/completed)
  - TriggerProgressSensor: trigger sub-state (idle/active/done) — optional
  - CompletionProgressSensor: completion sub-state (idle/active/done) — optional
  - LastCompletedSensor: diagnostic timestamp of last completion
"""
from __future__ import annotations

import logging
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

from .chore import Chore
from .const import (
    ATTR_CHORE_ID,
    DOMAIN,
    SERVICE_FORCE_COMPLETE,
    SERVICE_FORCE_DUE,
    SERVICE_FORCE_INACTIVE,
    ChoreState,
    SubState,
)
from .coordinator import ChoresCoordinator

_LOGGER = logging.getLogger(__name__)


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

        # Trigger progress sensor (only if trigger.sensor configured)
        if chore.trigger.has_sensor:
            entities.append(TriggerProgressSensor(coordinator, chore, entry))

        # Completion progress sensor (only if completion.sensor configured)
        if chore.completion.has_sensor:
            entities.append(CompletionProgressSensor(coordinator, chore, entry))

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

    def __init__(
        self,
        coordinator: ChoresCoordinator,
        chore: Chore,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._chore = chore
        self._attr_unique_id = f"{DOMAIN}_{chore.id}"
        self._attr_name = chore.name
        self._attr_icon = chore.icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, chore.id)},
        )
        self._attr_options = [s.value for s in ChoreState]
        self._attr_device_class = SensorDeviceClass.ENUM

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
# TriggerProgressSensor
# ═══════════════════════════════════════════════════════════════════════


class TriggerProgressSensor(CoordinatorEntity[ChoresCoordinator], SensorEntity):
    """Trigger progress sub-sensor (idle/active/done)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ChoresCoordinator,
        chore: Chore,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._chore = chore
        sensor_cfg = chore.trigger.sensor_config or {}
        self._attr_unique_id = f"{DOMAIN}_{chore.id}_trigger"
        self._attr_name = sensor_cfg.get("name", f"{chore.name} Trigger")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, chore.id)},
        )
        self._icon_idle = sensor_cfg.get("icon_idle")
        self._icon_active = sensor_cfg.get("icon_active")
        self._icon_done = sensor_cfg.get("icon_done")
        self._attr_options = [s.value for s in SubState]
        self._attr_device_class = SensorDeviceClass.ENUM

    @property
    def native_value(self) -> str:
        return self._chore.trigger.state.value

    @property
    def icon(self) -> str | None:
        state = self._chore.trigger.state
        if state == SubState.IDLE:
            return self._icon_idle or "mdi:cog"
        if state == SubState.ACTIVE:
            return self._icon_active or "mdi:cog-play"
        if state == SubState.DONE:
            return self._icon_done or "mdi:check-circle"
        return "mdi:cog"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._chore.trigger.extra_attributes(self.coordinator.hass)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


# ═══════════════════════════════════════════════════════════════════════
# CompletionProgressSensor
# ═══════════════════════════════════════════════════════════════════════


class CompletionProgressSensor(CoordinatorEntity[ChoresCoordinator], SensorEntity):
    """Completion progress sub-sensor (idle/active/done)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ChoresCoordinator,
        chore: Chore,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._chore = chore
        sensor_cfg = chore.completion.sensor_config or {}
        self._attr_unique_id = f"{DOMAIN}_{chore.id}_completion"
        self._attr_name = sensor_cfg.get("name", f"{chore.name} Completion")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, chore.id)},
        )
        self._icon_idle = sensor_cfg.get("icon_idle")
        self._icon_active = sensor_cfg.get("icon_active")
        self._icon_done = sensor_cfg.get("icon_done")
        self._attr_options = [s.value for s in SubState]
        self._attr_device_class = SensorDeviceClass.ENUM

    @property
    def native_value(self) -> str:
        return self._chore.completion.state.value

    @property
    def icon(self) -> str | None:
        state = self._chore.completion.state
        if state == SubState.IDLE:
            return self._icon_idle or "mdi:checkbox-blank-outline"
        if state == SubState.ACTIVE:
            return self._icon_active or "mdi:checkbox-marked-circle-outline"
        if state == SubState.DONE:
            return self._icon_done or "mdi:check-circle"
        return "mdi:checkbox-blank-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._chore.completion.extra_attributes(self.coordinator.hass)

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
        self._attr_name = f"{chore.name} Last Completed"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, chore.id)},
        )

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
