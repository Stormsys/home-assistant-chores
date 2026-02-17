"""DataUpdateCoordinator for the Chores integration.

The coordinator:
  - Holds all Chore objects
  - Polls every 60 seconds (for cooldown timers, reset checks)
  - Fires events on state transitions
  - Persists state to the store
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .chore_core import Chore
from .const import (
    ATTR_CHORE_ID,
    ATTR_CHORE_NAME,
    ATTR_NEW_STATE,
    ATTR_PREVIOUS_STATE,
    DOMAIN,
    EVENT_CHORE_COMPLETED,
    EVENT_CHORE_DUE,
    EVENT_CHORE_PENDING,
    EVENT_CHORE_RESET,
    EVENT_CHORE_STARTED,
    ChoreState,
    CompletionType,
)
from .store import ChoreStore

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(seconds=60)

# Map chore states to event names
STATE_EVENT_MAP: dict[ChoreState, str] = {
    ChoreState.PENDING: EVENT_CHORE_PENDING,
    ChoreState.DUE: EVENT_CHORE_DUE,
    ChoreState.STARTED: EVENT_CHORE_STARTED,
    ChoreState.COMPLETED: EVENT_CHORE_COMPLETED,
    ChoreState.INACTIVE: EVENT_CHORE_RESET,
}


class ChoresCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for managing all chores."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: ChoreStore,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self._entry = entry
        self._store = store
        self._chores: dict[str, Chore] = {}

    # ── Chore management ────────────────────────────────────────────

    def register_chore(self, chore: Chore) -> None:
        """Register a chore and restore its persisted state."""
        self._chores[chore.id] = chore
        # Restore persisted state
        stored = self._store.get_chore_state(chore.id)
        if stored:
            chore.restore_state(stored)
            _LOGGER.debug("Restored state for chore %s: %s", chore.id, chore.state)

    def get_chore(self, chore_id: str) -> Chore | None:
        """Get a chore by ID."""
        return self._chores.get(chore_id)

    @property
    def chores(self) -> dict[str, Chore]:
        """Return all chores."""
        return self._chores

    # ── Listener setup ──────────────────────────────────────────────

    def setup_listeners(self) -> None:
        """Set up state change listeners for all chores."""
        for chore in self._chores.values():
            chore.async_setup_listeners(self.hass, self._on_chore_state_change)

    def remove_listeners(self) -> None:
        """Remove all state change listeners."""
        for chore in self._chores.values():
            chore.async_remove_listeners()

    async def async_refresh_completion_buttons(self) -> None:
        """Resolve force-complete button entity_id for manual-completion chores."""
        registry = er.async_get(self.hass)
        for chore in self._chores.values():
            if chore.completion_type != CompletionType.MANUAL.value:
                continue
            unique_id = f"{DOMAIN}_{chore.id}_force_complete"
            entity_id = registry.async_get_entity_id("button", DOMAIN, unique_id)
            chore._completion_button_entity_id = entity_id  # noqa: SLF001

    @callback
    def _on_chore_state_change(
        self, chore_id: str, old_state: ChoreState, new_state: ChoreState
    ) -> None:
        """Handle a chore state change (from event listener)."""
        chore = self._chores.get(chore_id)
        if not chore:
            return

        self._fire_event(chore, old_state, new_state)
        self._persist_chore(chore)
        self.async_set_updated_data(self._build_data())

    # ── Force actions (called by buttons/services) ──────────────────

    async def async_force_due(self, chore_id: str) -> None:
        """Force a chore to due."""
        chore = self._chores.get(chore_id)
        if not chore:
            _LOGGER.warning("Chore not found: %s", chore_id)
            return
        old = chore.force_due()
        if old is not None:
            self._fire_event(chore, old, chore.state)
            self._persist_chore(chore)
            self.async_set_updated_data(self._build_data())

    async def async_force_inactive(self, chore_id: str) -> None:
        """Force a chore to inactive."""
        chore = self._chores.get(chore_id)
        if not chore:
            _LOGGER.warning("Chore not found: %s", chore_id)
            return
        old = chore.force_inactive()
        if old is not None:
            self._fire_event(chore, old, chore.state)
            self._persist_chore(chore)
            self.async_set_updated_data(self._build_data())

    async def async_force_complete(self, chore_id: str) -> None:
        """Force a chore to completed."""
        chore = self._chores.get(chore_id)
        if not chore:
            _LOGGER.warning("Chore not found: %s", chore_id)
            return
        old = chore.force_complete()
        if old is not None:
            self._fire_event(chore, old, chore.state)
            self._persist_chore(chore)
            self.async_set_updated_data(self._build_data())

    # ── Polling update ──────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """Poll all chores (called every 60s)."""
        for chore in self._chores.values():
            old = chore.evaluate(self.hass)
            if old is not None:
                self._fire_event(chore, old, chore.state)
                self._persist_chore(chore)

        # Persist all state periodically
        await self._store.async_save()
        return self._build_data()

    # ── Internal helpers ────────────────────────────────────────────

    def _build_data(self) -> dict[str, Any]:
        """Build the data dict that entities read from."""
        return {
            chore_id: chore.to_state_dict(self.hass)
            for chore_id, chore in self._chores.items()
        }

    def _fire_event(
        self, chore: Chore, old_state: ChoreState, new_state: ChoreState
    ) -> None:
        """Fire a Home Assistant event for a state transition."""
        event_name = STATE_EVENT_MAP.get(new_state)
        if not event_name:
            return

        event_data = {
            ATTR_CHORE_ID: chore.id,
            ATTR_CHORE_NAME: chore.name,
            ATTR_PREVIOUS_STATE: old_state.value,
            ATTR_NEW_STATE: new_state.value,
        }
        self.hass.bus.async_fire(event_name, event_data)
        _LOGGER.debug("Fired event %s for chore %s", event_name, chore.id)

    def _persist_chore(self, chore: Chore) -> None:
        """Persist a single chore's state (in memory; saved on next poll)."""
        self._store.set_chore_state(chore.id, chore.snapshot_state())
