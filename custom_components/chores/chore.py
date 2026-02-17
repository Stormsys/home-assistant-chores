"""Chore platform: main state machine entity (chore.xxx).

One entity per chore; entity_id is chore.<slug>.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback, async_get_current_platform
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .chore_core import Chore
from .const import (
    DOMAIN,
    SERVICE_FORCE_COMPLETE,
    SERVICE_FORCE_DUE,
    SERVICE_FORCE_INACTIVE,
    ChoreState,
)
from .coordinator import ChoresCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up chore entities (main state machine per chore)."""
    coordinator: ChoresCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities = [
        ChoreStateEntity(coordinator, chore, entry)
        for chore in coordinator.chores.values()
    ]
    async_add_entities(entities)

    platform = async_get_current_platform()
    platform.async_register_entity_service(SERVICE_FORCE_DUE, {}, "async_force_due")
    platform.async_register_entity_service(SERVICE_FORCE_INACTIVE, {}, "async_force_inactive")
    platform.async_register_entity_service(SERVICE_FORCE_COMPLETE, {}, "async_force_complete")


class ChoreStateEntity(CoordinatorEntity[ChoresCoordinator], SensorEntity):
    """Main chore state machine entity (entity_id: chore.xxx)."""

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
        self._attr_name = chore.name
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

    async def async_force_due(self) -> None:
        """Force chore to due."""
        await self.coordinator.async_force_due(self._chore.id)

    async def async_force_inactive(self) -> None:
        """Force chore to inactive."""
        await self.coordinator.async_force_inactive(self._chore.id)

    async def async_force_complete(self) -> None:
        """Force chore to completed."""
        await self.coordinator.async_force_complete(self._chore.id)
