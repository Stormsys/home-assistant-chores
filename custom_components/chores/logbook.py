"""Logbook platform for the Chores integration.

Provides human-readable logbook entries for all chore state transitions.
Entries appear in the Home Assistant logbook linked to the chore's main sensor.

Each chore can opt out of logbook entries by setting ``logbook: false`` in YAML.

Message registries are data-driven dicts mapping detector type strings to
human-readable messages.  Adding a new detector type only requires adding
an entry to the appropriate dict — no if/elif chains to modify.
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
)


# ── Message registries ────────────────────────────────────────────────

_PENDING_MESSAGES: dict[str, str] = {
    # Trigger-primary detectors
    "power_cycle": "Appliance started — cycle in progress",
    "state_change": "Trigger condition met — waiting for gate",
    "daily": "Scheduled time reached — waiting for gate condition",
    "weekly": "Weekly schedule triggered — waiting for gate condition",
    "duration": "Entity in target state — duration timer running",
    # Cross-stage detectors (when used as triggers)
    "sensor_state": "Sensor state condition met — waiting",
    "contact": "Contact event detected — waiting",
    "contact_cycle": "Contact cycle started — waiting",
    "presence_cycle": "Presence change detected — waiting",
    "sensor_threshold": "Sensor threshold reached — waiting",
}
_PENDING_DEFAULT = "Trigger active — waiting to become due"

_DUE_MESSAGES: dict[str, str] = {
    # Trigger-primary detectors
    "power_cycle": "Appliance cycle complete — ready to complete",
    "state_change": "Trigger condition fulfilled — ready to complete",
    "daily": "Scheduled time reached — ready to complete",
    "weekly": "Weekly schedule triggered — ready to complete",
    "duration": "Duration threshold reached — ready to complete",
    # Cross-stage detectors (when used as triggers)
    "sensor_state": "Sensor state triggered — ready to complete",
    "contact": "Contact detected — ready to complete",
    "contact_cycle": "Contact cycle complete — ready to complete",
    "presence_cycle": "Presence cycle complete — ready to complete",
    "sensor_threshold": "Sensor threshold crossed — ready to complete",
}
_DUE_DEFAULT = "Ready to complete"

_STARTED_MESSAGES: dict[str, str] = {
    "contact_cycle": "Step 1 detected — door opened, waiting for close",
    "presence_cycle": "Left home — waiting to return",
    # Cross-stage detectors (when used as completions with 2 steps)
    "power_cycle": "Appliance started — waiting for cycle to finish",
    "duration": "Duration counting — waiting for threshold",
}
_STARTED_DEFAULT = "Step 1 of 2 complete — waiting for step 2"

_COMPLETED_MESSAGES: dict[str, str] = {
    # Completion-primary detectors
    "manual": "Manually completed",
    "contact": "Completed — contact detected",
    "contact_cycle": "Completed — door cycle complete",
    "presence_cycle": "Completed — returned home",
    "sensor_state": "Completed — sensor triggered",
    "sensor_threshold": "Completed — sensor threshold crossed",
    # Cross-stage detectors (when used as completions)
    "power_cycle": "Completed — appliance cycle finished",
    "state_change": "Completed — state change detected",
    "duration": "Completed — duration threshold reached",
}
_COMPLETED_DEFAULT = "Completed"


# ── Helper functions ──────────────────────────────────────────────────


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
    return _PENDING_MESSAGES.get(trigger_type, _PENDING_DEFAULT)


def _describe_due(forced: bool, trigger_type: str | None) -> str:
    """Return a logbook message for the chore_due event."""
    if forced:
        return "Manually marked as due"
    return _DUE_MESSAGES.get(trigger_type, _DUE_DEFAULT)


def _describe_started(forced: bool, completion_type: str | None) -> str:
    """Return a logbook message for the chore_started event."""
    if forced:
        return "Manually started (step 1 complete)"
    return _STARTED_MESSAGES.get(completion_type, _STARTED_DEFAULT)


def _describe_completed(forced: bool, completion_type: str | None) -> str:
    """Return a logbook message for the chore_completed event."""
    if forced:
        return "Manually marked as complete"
    return _COMPLETED_MESSAGES.get(completion_type, _COMPLETED_DEFAULT)


def _describe_reset(forced: bool) -> str:
    """Return a logbook message for the chore_reset event."""
    if forced:
        return "Manually reset to inactive"
    return "Reset — ready for next cycle"


# ── Registration ──────────────────────────────────────────────────────


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
