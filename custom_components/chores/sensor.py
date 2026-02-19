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
from .triggers import DailyTrigger

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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, chore.id)},
        )
        self._attr_options = [s.value for s in SubState]
        self._attr_device_class = SensorDeviceClass.ENUM

        # Type-aware defaults (overridden by any sensor: block in YAML)
        trigger = chore.trigger
        if trigger.trigger_type == TriggerType.DAILY:
            assert isinstance(trigger, DailyTrigger)
            time_str = trigger.trigger_time.strftime("%H:%M")
            default_name = f"Daily at {time_str}"
            default_icon_idle = "mdi:calendar-clock"
            default_icon_active = "mdi:calendar-alert"
            default_icon_done = "mdi:calendar-check"
        elif trigger.trigger_type == TriggerType.POWER_CYCLE:
            default_name = "Power Monitor"
            default_icon_idle = "mdi:power-plug-off"
            default_icon_active = "mdi:power-plug"
            default_icon_done = "mdi:power-plug-outline"
        else:  # state_change
            default_name = "State Monitor"
            default_icon_idle = "mdi:toggle-switch-off-outline"
            default_icon_active = "mdi:toggle-switch"
            default_icon_done = "mdi:check-circle-outline"

        self._attr_name = sensor_cfg.get("name", default_name)
        self._icon_idle = sensor_cfg.get("icon_idle", default_icon_idle)
        self._icon_active = sensor_cfg.get("icon_active", default_icon_active)
        self._icon_done = sensor_cfg.get("icon_done", default_icon_done)

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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, chore.id)},
        )
        self._attr_options = [s.value for s in SubState]
        self._attr_device_class = SensorDeviceClass.ENUM

        # Type-aware defaults (overridden by any sensor: block in YAML)
        completion = chore.completion
        if completion.completion_type == CompletionType.CONTACT:
            default_name = "Contact"
            default_icon_idle = "mdi:door-closed"
            default_icon_active = "mdi:door-open"
            default_icon_done = "mdi:check-circle"
        elif completion.completion_type == CompletionType.CONTACT_CYCLE:
            default_name = "Contact Cycle"
            default_icon_idle = "mdi:door-closed"
            default_icon_active = "mdi:door-open"
            default_icon_done = "mdi:door-closed-lock"
        elif completion.completion_type == CompletionType.PRESENCE_CYCLE:
            default_name = "Presence"
            default_icon_idle = "mdi:home"
            default_icon_active = "mdi:walk"
            default_icon_done = "mdi:home-account"
        elif completion.completion_type == CompletionType.SENSOR_STATE:
            default_name = "Sensor State"
            default_icon_idle = "mdi:eye-off-outline"
            default_icon_active = "mdi:eye"
            default_icon_done = "mdi:check-circle"
        else:
            default_name = "Completion"
            default_icon_idle = "mdi:checkbox-blank-outline"
            default_icon_active = "mdi:checkbox-marked-circle-outline"
            default_icon_done = "mdi:check-circle"

        self._attr_name = sensor_cfg.get("name", default_name)
        self._icon_idle = sensor_cfg.get("icon_idle", default_icon_idle)
        self._icon_active = sensor_cfg.get("icon_active", default_icon_active)
        self._icon_done = sensor_cfg.get("icon_done", default_icon_done)

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
