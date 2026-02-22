"""The Chores integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .chore_core import Chore
from .const import CONF_LOGBOOK, DOMAIN
from .coordinator import ChoresCoordinator
from .store import ChoreStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
]

# ── YAML Schema ─────────────────────────────────────────────────────

GATE_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("state"): cv.string,
    }
)

SENSOR_DISPLAY_SCHEMA = vol.Schema(
    {
        vol.Optional("name"): cv.string,
        vol.Optional("icon_idle"): cv.icon,
        vol.Optional("icon_active"): cv.icon,
        vol.Optional("icon_done"): cv.icon,
    }
)

TRIGGER_SCHEMA = vol.Any(
    # power_cycle
    vol.Schema(
        {
            vol.Required("type"): "power_cycle",
            vol.Optional("power_sensor"): cv.entity_id,
            vol.Optional("current_sensor"): cv.entity_id,
            vol.Optional("power_threshold", default=10.0): cv.positive_float,
            vol.Optional("current_threshold", default=0.04): cv.positive_float,
            vol.Optional("cooldown_minutes", default=5): cv.positive_int,
            vol.Optional("sensor"): SENSOR_DISPLAY_SCHEMA,
        }
    ),
    # state_change
    vol.Schema(
        {
            vol.Required("type"): "state_change",
            vol.Required("entity_id"): cv.entity_id,
            vol.Required("from"): cv.string,
            vol.Required("to"): cv.string,
            vol.Optional("sensor"): SENSOR_DISPLAY_SCHEMA,
        }
    ),
    # daily
    vol.Schema(
        {
            vol.Required("type"): "daily",
            vol.Required("time"): cv.string,
            vol.Optional("gate"): GATE_SCHEMA,
            vol.Optional("sensor"): SENSOR_DISPLAY_SCHEMA,
        }
    ),
    # weekly (specific days with per-day times)
    vol.Schema(
        {
            vol.Required("type"): "weekly",
            vol.Required("schedule"): vol.All(
                cv.ensure_list,
                [
                    vol.Schema(
                        {
                            vol.Required("day"): vol.In(
                                ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
                            ),
                            vol.Required("time"): cv.string,
                        }
                    )
                ],
                vol.Length(min=1),
            ),
            vol.Optional("gate"): GATE_SCHEMA,
            vol.Optional("sensor"): SENSOR_DISPLAY_SCHEMA,
        }
    ),
)

COMPLETION_SCHEMA = vol.Any(
    # manual
    vol.Schema(
        {
            vol.Required("type"): "manual",
        }
    ),
    # sensor_state
    vol.Schema(
        {
            vol.Required("type"): "sensor_state",
            vol.Required("entity_id"): cv.entity_id,
            vol.Optional("state", default="on"): cv.string,
            vol.Optional("sensor"): SENSOR_DISPLAY_SCHEMA,
        }
    ),
    # contact (single step)
    vol.Schema(
        {
            vol.Required("type"): "contact",
            vol.Required("entity_id"): cv.entity_id,
            vol.Optional("sensor"): SENSOR_DISPLAY_SCHEMA,
        }
    ),
    # contact_cycle (two step)
    vol.Schema(
        {
            vol.Required("type"): "contact_cycle",
            vol.Required("entity_id"): cv.entity_id,
            vol.Optional("debounce_seconds", default=2): vol.All(int, vol.Range(min=0)),
            vol.Optional("sensor"): SENSOR_DISPLAY_SCHEMA,
        }
    ),
    # presence_cycle (two step)
    vol.Schema(
        {
            vol.Required("type"): "presence_cycle",
            vol.Required("entity_id"): cv.entity_id,
            vol.Optional("sensor"): SENSOR_DISPLAY_SCHEMA,
        }
    ),
)

RESET_SCHEMA = vol.Any(
    vol.Schema(
        {
            vol.Required("type"): "delay",
            vol.Optional("minutes", default=0): vol.All(int, vol.Range(min=0)),
        }
    ),
    vol.Schema(
        {
            vol.Required("type"): "daily_reset",
            vol.Required("time"): cv.time,
        }
    ),
)

CHORE_SCHEMA = vol.Schema(
    {
        vol.Required("id"): cv.string,
        vol.Required("name"): cv.string,
        vol.Optional("icon", default="mdi:checkbox-marked-circle-outline"): cv.icon,
        vol.Optional("icon_inactive"): cv.icon,
        vol.Optional("icon_pending"): cv.icon,
        vol.Optional("icon_due"): cv.icon,
        vol.Optional("icon_started"): cv.icon,
        vol.Optional("icon_completed"): cv.icon,
        vol.Required("trigger"): TRIGGER_SCHEMA,
        vol.Optional("completion", default={"type": "manual"}): COMPLETION_SCHEMA,
        vol.Optional("reset"): RESET_SCHEMA,
        vol.Optional("state_labels", default={}): vol.Schema({
            vol.Optional("inactive"): cv.string,
            vol.Optional("pending"): cv.string,
            vol.Optional("due"): cv.string,
            vol.Optional("started"): cv.string,
            vol.Optional("completed"): cv.string,
        }),
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_LOGBOOK, default=True): cv.boolean,
                vol.Optional("chores", default=[]): vol.All(
                    cv.ensure_list, [CHORE_SCHEMA]
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


# ── Setup ───────────────────────────────────────────────────────────


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Chores integration from YAML configuration."""
    if DOMAIN not in config:
        return True

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["yaml_config"] = config[DOMAIN]

    # Create a config entry if one doesn't exist (for YAML-based setup)
    existing_entries = hass.config_entries.async_entries(DOMAIN)
    if not existing_entries:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": "import"},
                data={},
            )
        )
    else:
        for entry in existing_entries:
            hass.async_create_task(
                hass.config_entries.async_reload(entry.entry_id)
            )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Chores from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Initialize store
    store = ChoreStore(hass)
    await store.async_load()

    # Load chores from YAML
    yaml_config = hass.data[DOMAIN].get("yaml_config", {})
    chores_config = yaml_config.get("chores", [])
    logbook_enabled: bool = yaml_config.get(CONF_LOGBOOK, True)

    # Initialize coordinator
    coordinator = ChoresCoordinator(hass, entry, store, logbook_enabled=logbook_enabled)

    for chore_config in chores_config:
        try:
            chore = Chore(chore_config)
            coordinator.register_chore(chore)

            # Create device for this chore
            device_registry = dr.async_get(hass)
            device_registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, chore.id)},
                name=chore.name,
                manufacturer="Chores",
                model=chore.trigger_type.replace("_", " ").title(),
                sw_version="2.0.0",
            )
        except Exception as err:
            _LOGGER.error(
                "Error creating chore %s: %s",
                chore_config.get("id", "unknown"),
                err,
            )

    # Store coordinator
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "store": store,
    }

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Resolve completion_button entity_id for manual-completion chores
    await coordinator.async_refresh_completion_buttons()

    # Set up listeners for all chores
    coordinator.setup_listeners()

    # Initial data fetch
    await coordinator.async_config_entry_first_refresh()

    # Register services
    _async_setup_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: ChoresCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    coordinator.remove_listeners()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    # Remove services if no more entries
    remaining = {
        k: v for k, v in hass.data[DOMAIN].items()
        if k != "yaml_config" and isinstance(v, dict) and "coordinator" in v
    }
    if not remaining:
        _async_remove_services(hass)

    return unload_ok


# ── Services ────────────────────────────────────────────────────────


def _async_setup_services(hass: HomeAssistant) -> None:
    """Set up global Chores services."""
    from .const import ATTR_CHORE_ID, SERVICE_FORCE_COMPLETE, SERVICE_FORCE_DUE, SERVICE_FORCE_INACTIVE

    if hass.services.has_service(DOMAIN, SERVICE_FORCE_DUE):
        return  # Already registered

    async def _get_coordinator(chore_id: str) -> ChoresCoordinator | None:
        for entry_data in hass.data[DOMAIN].values():
            if isinstance(entry_data, dict) and "coordinator" in entry_data:
                coordinator: ChoresCoordinator = entry_data["coordinator"]
                if coordinator.get_chore(chore_id):
                    return coordinator
        return None

    async def handle_force_due(call) -> None:
        chore_id = call.data[ATTR_CHORE_ID]
        coordinator = await _get_coordinator(chore_id)
        if coordinator:
            await coordinator.async_force_due(chore_id)
        else:
            _LOGGER.warning("Chore not found: %s", chore_id)

    async def handle_force_inactive(call) -> None:
        chore_id = call.data[ATTR_CHORE_ID]
        coordinator = await _get_coordinator(chore_id)
        if coordinator:
            await coordinator.async_force_inactive(chore_id)
        else:
            _LOGGER.warning("Chore not found: %s", chore_id)

    async def handle_force_complete(call) -> None:
        chore_id = call.data[ATTR_CHORE_ID]
        coordinator = await _get_coordinator(chore_id)
        if coordinator:
            await coordinator.async_force_complete(chore_id)
        else:
            _LOGGER.warning("Chore not found: %s", chore_id)

    service_schema = vol.Schema(
        {
            vol.Required(ATTR_CHORE_ID): cv.string,
        }
    )

    hass.services.async_register(
        DOMAIN, SERVICE_FORCE_DUE, handle_force_due, schema=service_schema
    )
    hass.services.async_register(
        DOMAIN, SERVICE_FORCE_INACTIVE, handle_force_inactive, schema=service_schema
    )
    hass.services.async_register(
        DOMAIN, SERVICE_FORCE_COMPLETE, handle_force_complete, schema=service_schema
    )


def _async_remove_services(hass: HomeAssistant) -> None:
    """Remove Chores services."""
    from .const import SERVICE_FORCE_COMPLETE, SERVICE_FORCE_DUE, SERVICE_FORCE_INACTIVE

    hass.services.async_remove(DOMAIN, SERVICE_FORCE_DUE)
    hass.services.async_remove(DOMAIN, SERVICE_FORCE_INACTIVE)
    hass.services.async_remove(DOMAIN, SERVICE_FORCE_COMPLETE)
