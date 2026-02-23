"""Logbook platform for the Chores integration.

Provides human-readable logbook entries for all chore state transitions.
Entries appear in the Home Assistant logbook linked to the chore's main sensor.

Each chore can opt out of logbook entries by setting ``logbook: false`` in YAML.
"""
from __future__ import annotations

from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import (
    ATTR_CHORE_ID,
    ATTR_CHORE_NAME,
    ATTR_FORCED,
    DOMAIN,
    EVENT_CHORE_COMPLETED,
    EVENT_CHORE_DUE,
    EVENT_CHORE_PENDING,
    EVENT_CHORE_RESET,
    EVENT_CHORE_STARTED,
    CompletionType,
    TriggerType,
)


def _get_chore(hass: HomeAssistant, chore_id: str) -> Any | None:
    """Look up a Chore instance from hass.data."""
    for entry_data in hass.data.get(DOMAIN, {}).values():
        if isinstance(entry_data, dict) and "coordinator" in entry_data:
            coordinator = entry_data["coordinator"]
            chore = coordinator.get_chore(chore_id)
            if chore:
                return chore
    return None


def _get_entity_id(hass: HomeAssistant, chore_id: str) -> str | None:
    """Look up the main sensor entity_id for a chore from the entity registry."""
    registry = er.async_get(hass)
    return registry.async_get_entity_id("sensor", DOMAIN, f"{DOMAIN}_{chore_id}")


def _describe_pending(forced: bool, trigger_type: str | None) -> str:
    """Return a logbook message for the chore_pending event."""
    if forced:
        return "Manually triggered — waiting to complete"
    if trigger_type == TriggerType.POWER_CYCLE:
        return "Appliance started — cycle in progress"
    if trigger_type == TriggerType.STATE_CHANGE:
        return "Trigger condition met — waiting for gate"
    if trigger_type == TriggerType.DAILY:
        return "Scheduled time reached — waiting for gate condition"
    if trigger_type == TriggerType.WEEKLY:
        return "Weekly schedule triggered — waiting for gate condition"
    if trigger_type == TriggerType.DURATION:
        return "Entity in target state — duration timer running"
    return "Trigger active — waiting to become due"


def _describe_due(forced: bool, trigger_type: str | None) -> str:
    """Return a logbook message for the chore_due event."""
    if forced:
        return "Manually marked as due"
    if trigger_type == TriggerType.POWER_CYCLE:
        return "Appliance cycle complete — ready to complete"
    if trigger_type == TriggerType.STATE_CHANGE:
        return "Trigger condition fulfilled — ready to complete"
    if trigger_type == TriggerType.DAILY:
        return "Scheduled time reached — ready to complete"
    if trigger_type == TriggerType.WEEKLY:
        return "Weekly schedule triggered — ready to complete"
    if trigger_type == TriggerType.DURATION:
        return "Duration threshold reached — ready to complete"
    return "Ready to complete"


def _describe_started(forced: bool, completion_type: str | None) -> str:
    """Return a logbook message for the chore_started event."""
    if forced:
        return "Manually started (step 1 complete)"
    if completion_type == CompletionType.CONTACT_CYCLE:
        return "Step 1 detected — door opened, waiting for close"
    if completion_type == CompletionType.PRESENCE_CYCLE:
        return "Left home — waiting to return"
    return "Step 1 of 2 complete — waiting for step 2"


def _describe_completed(forced: bool, completion_type: str | None) -> str:
    """Return a logbook message for the chore_completed event."""
    if forced:
        return "Manually marked as complete"
    if completion_type == CompletionType.MANUAL:
        return "Manually completed"
    if completion_type == CompletionType.CONTACT:
        return "Completed — contact detected"
    if completion_type == CompletionType.CONTACT_CYCLE:
        return "Completed — door cycle complete"
    if completion_type == CompletionType.PRESENCE_CYCLE:
        return "Completed — returned home"
    if completion_type == CompletionType.SENSOR_STATE:
        return "Completed — sensor triggered"
    return "Completed"


def _describe_reset(forced: bool) -> str:
    """Return a logbook message for the chore_reset event."""
    if forced:
        return "Manually reset to inactive"
    return "Reset — ready for next cycle"


def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Any,
) -> None:
    """Describe chore state-transition events for the logbook."""

    @callback
    def _describe(event: Event) -> dict[str, str] | None:
        data = event.data

        # Respect the per-chore logbook toggle
        if not data.get("logbook_enabled", True):
            return None

        chore_id: str = data.get(ATTR_CHORE_ID, "")
        chore_name: str = data.get(ATTR_CHORE_NAME, chore_id)
        forced: bool = data.get(ATTR_FORCED, False)
        event_type: str = event.event_type

        # Look up chore for trigger / completion context
        chore = _get_chore(hass, chore_id)
        trigger_type: str | None = chore.trigger_type if chore else None
        completion_type: str | None = chore.completion_type if chore else None

        # Build message based on which state was entered
        if event_type == EVENT_CHORE_PENDING:
            message = _describe_pending(forced, trigger_type)
        elif event_type == EVENT_CHORE_DUE:
            message = _describe_due(forced, trigger_type)
        elif event_type == EVENT_CHORE_STARTED:
            message = _describe_started(forced, completion_type)
        elif event_type == EVENT_CHORE_COMPLETED:
            message = _describe_completed(forced, completion_type)
        elif event_type == EVENT_CHORE_RESET:
            message = _describe_reset(forced)
        else:
            return None

        entry: dict[str, str] = {
            "name": chore_name,
            "message": message,
        }

        # Link the entry to the chore's main sensor entity so it appears
        # in the device / entity logbook timeline.
        entity_id = _get_entity_id(hass, chore_id)
        if entity_id:
            entry["entity_id"] = entity_id

        return entry

    for event_name in (
        EVENT_CHORE_PENDING,
        EVENT_CHORE_DUE,
        EVENT_CHORE_STARTED,
        EVENT_CHORE_COMPLETED,
        EVENT_CHORE_RESET,
    ):
        async_describe_event(DOMAIN, event_name, _describe)
