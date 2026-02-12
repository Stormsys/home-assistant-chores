"""Binary sensor entities for the Chores integration.

Creates one binary sensor per chore:
  - NeedsAttentionBinarySensor: ON when chore is 'due' or 'started'
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .chore import Chore
from .const import DOMAIN, ChoreState
from .coordinator import ChoresCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor entities."""
    coordinator: ChoresCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities = [
        NeedsAttentionBinarySensor(coordinator, chore, entry)
        for chore in coordinator.chores.values()
    ]
    async_add_entities(entities)


class NeedsAttentionBinarySensor(
    CoordinatorEntity[ChoresCoordinator], BinarySensorEntity
):
    """Binary sensor that is ON when a chore needs attention (due or started)."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        coordinator: ChoresCoordinator,
        chore: Chore,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._chore = chore
        self._attr_unique_id = f"{DOMAIN}_{chore.id}_attention"
        self._attr_name = f"{chore.name} Attention"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, chore.id)},
        )

    @property
    def is_on(self) -> bool:
        return self._chore.state in (ChoreState.DUE, ChoreState.STARTED)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "chore_id": self._chore.id,
            "chore_state": self._chore.state.value,
            "due_since": (
                self._chore.due_since.isoformat() if self._chore.due_since else None
            ),
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
