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
        # Trigger display info
        trigger_sensor_cfg = chore.trigger.sensor_config or {}
        trigger_info = {
            "type": chore.trigger_type,
            "state": chore.trigger.state.value,
            "name": trigger_sensor_cfg.get("name"),
            "snapshot": chore.trigger.snapshot_state(),
        }

        # Completion display info
        completion_sensor_cfg = chore.completion.sensor_config or {}
        completion_info = {
            "type": chore.completion_type,
            "state": chore.completion.state.value,
            "name": completion_sensor_cfg.get("name"),
            "snapshot": chore.completion.snapshot_state(),
        }

        chores_data[chore_id] = {
            "chore_name": chore.name,
            "description": getattr(chore, "_description", None),
            "context": getattr(chore, "_context", None),
            "icon": chore.icon,
            "state": chore.state.value,
            "state_entered_at": chore.state_entered_at.isoformat(),
            "trigger": trigger_info,
            "completion": completion_info,
            "due_since": chore.due_since.isoformat() if chore.due_since else None,
            "last_completed": chore.last_completed.isoformat() if chore.last_completed else None,
            "forced": chore.forced,
            "notify_at": chore.notify_at_str,
            "notify_after_minutes": chore.notify_after_minutes,
            "completion_history_count": len(chore.completion_history),
        }

    return {
        "config_entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
        },
        "chores": chores_data,
    }
