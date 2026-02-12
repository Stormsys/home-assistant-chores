"""Diagnostics support for Chores integration."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import ChoresCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: ChoresCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    chores_data = {}
    for chore_id, chore in coordinator.chores.items():
        chores_data[chore_id] = {
            "name": chore.name,
            "icon": chore.icon,
            "state": chore.state.value,
            "state_entered_at": chore.state_entered_at.isoformat(),
            "trigger_type": chore.trigger_type,
            "trigger_state": chore.trigger.state.value,
            "completion_type": chore.completion_type,
            "completion_state": chore.completion.state.value,
            "due_since": chore.due_since.isoformat() if chore.due_since else None,
            "last_completed": chore.last_completed.isoformat() if chore.last_completed else None,
            "forced": chore.forced,
            "trigger_snapshot": chore.trigger.snapshot_state(),
            "completion_snapshot": chore.completion.snapshot_state(),
            "completion_history_count": len(chore.completion_history),
        }

    return {
        "config_entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
        },
        "chores": chores_data,
    }
