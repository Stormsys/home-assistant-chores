"""Persistent state store for the Chores integration.

Stores chore state and completion history to survive HA restarts.
Uses Home Assistant's built-in Store helper (writes to .storage/chores).
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 2


class ChoreStore:
    """Persistent store for chore state."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, Any] = {}

    async def async_load(self) -> None:
        """Load stored data."""
        stored = await self._store.async_load()
        if stored and isinstance(stored, dict):
            self._data = stored
        else:
            self._data = {"chores": {}}
        _LOGGER.debug("Loaded store with %d chores", len(self._data.get("chores", {})))

    async def async_save(self) -> None:
        """Save current data to disk."""
        await self._store.async_save(self._data)

    def get_chore_state(self, chore_id: str) -> dict[str, Any] | None:
        """Get persisted state for a chore."""
        return self._data.get("chores", {}).get(chore_id)

    def set_chore_state(self, chore_id: str, state_data: dict[str, Any]) -> None:
        """Set state for a chore (in memory, call async_save to persist)."""
        if "chores" not in self._data:
            self._data["chores"] = {}
        self._data["chores"][chore_id] = state_data

    def remove_chore_state(self, chore_id: str) -> None:
        """Remove stored state for a chore."""
        if "chores" in self._data:
            self._data["chores"].pop(chore_id, None)

    @property
    def chore_ids(self) -> list[str]:
        """Return all stored chore IDs."""
        return list(self._data.get("chores", {}).keys())

    async def async_remove(self) -> None:
        """Remove the store file entirely."""
        await self._store.async_remove()

