"""Button entities for the Chores integration.

Creates 3 buttons per chore:
  - ForceDueButton: force to 'due' from any state
  - ForceInactiveButton: force to 'inactive' from any state
  - ForceCompleteButton: force to 'completed' from any state
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .chore_core import Chore
from .const import DOMAIN
from .coordinator import ChoresCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities."""
    coordinator: ChoresCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities: list[ButtonEntity] = []
    for chore in coordinator.chores.values():
        entities.append(ForceDueButton(coordinator, chore))
        entities.append(ForceInactiveButton(coordinator, chore))
        entities.append(ForceCompleteButton(coordinator, chore))

    async_add_entities(entities)


class _ChoreButtonBase(ButtonEntity):
    """Base class for chore force buttons."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ChoresCoordinator, chore: Chore) -> None:
        self._coordinator = coordinator
        self._chore = chore
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, chore.id)},
        )


class ForceDueButton(_ChoreButtonBase):
    """Button to force chore to 'due'."""

    def __init__(self, coordinator: ChoresCoordinator, chore: Chore) -> None:
        super().__init__(coordinator, chore)
        self._attr_unique_id = f"{DOMAIN}_{chore.id}_force_due"
        self._attr_name = f"Force {chore.name} Due"
        self._attr_icon = "mdi:alert-circle"

    async def async_press(self) -> None:
        await self._coordinator.async_force_due(self._chore.id)


class ForceInactiveButton(_ChoreButtonBase):
    """Button to force chore to 'inactive'."""

    def __init__(self, coordinator: ChoresCoordinator, chore: Chore) -> None:
        super().__init__(coordinator, chore)
        self._attr_unique_id = f"{DOMAIN}_{chore.id}_force_inactive"
        self._attr_name = f"Force {chore.name} Inactive"
        self._attr_icon = "mdi:cancel"

    async def async_press(self) -> None:
        await self._coordinator.async_force_inactive(self._chore.id)


class ForceCompleteButton(_ChoreButtonBase):
    """Button to force chore to 'completed'."""

    def __init__(self, coordinator: ChoresCoordinator, chore: Chore) -> None:
        super().__init__(coordinator, chore)
        self._attr_unique_id = f"{DOMAIN}_{chore.id}_force_complete"
        self._attr_name = f"Force {chore.name} Complete"
        self._attr_icon = "mdi:check-circle"

    async def async_press(self) -> None:
        await self._coordinator.async_force_complete(self._chore.id)
