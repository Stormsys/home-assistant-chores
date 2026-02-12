"""Constants for the Chores integration."""
from __future__ import annotations

from enum import StrEnum
from typing import Final

DOMAIN: Final = "chores"

# ── Configuration keys ──────────────────────────────────────────────
CONF_CHORES: Final = "chores"

# ── Chore states (main state machine) ───────────────────────────────
class ChoreState(StrEnum):
    """Main chore state machine.

    inactive -> pending -> due -> started -> completed -> inactive
    """

    INACTIVE = "inactive"
    PENDING = "pending"
    DUE = "due"
    STARTED = "started"
    COMPLETED = "completed"


# ── Sub-sensor states (unified for trigger + completion) ────────────
class SubState(StrEnum):
    """Shared states for trigger and completion progress sensors."""

    IDLE = "idle"
    ACTIVE = "active"
    DONE = "done"


# ── Trigger types ───────────────────────────────────────────────────
class TriggerType(StrEnum):
    """Available trigger types."""

    POWER_CYCLE = "power_cycle"
    STATE_CHANGE = "state_change"
    DAILY = "daily"


# ── Completion types ────────────────────────────────────────────────
class CompletionType(StrEnum):
    """Available completion types."""

    MANUAL = "manual"
    SENSOR_STATE = "sensor_state"
    CONTACT = "contact"
    CONTACT_CYCLE = "contact_cycle"
    PRESENCE_CYCLE = "presence_cycle"


# ── Reset types ─────────────────────────────────────────────────────
class ResetType(StrEnum):
    """Available reset types."""

    DELAY = "delay"
    IMPLICIT_DAILY = "implicit_daily"
    IMPLICIT_EVENT = "implicit_event"


# ── Events ──────────────────────────────────────────────────────────
EVENT_CHORE_PENDING: Final = f"{DOMAIN}.chore_pending"
EVENT_CHORE_DUE: Final = f"{DOMAIN}.chore_due"
EVENT_CHORE_STARTED: Final = f"{DOMAIN}.chore_started"
EVENT_CHORE_COMPLETED: Final = f"{DOMAIN}.chore_completed"
EVENT_CHORE_RESET: Final = f"{DOMAIN}.chore_reset"

# ── Services ────────────────────────────────────────────────────────
SERVICE_FORCE_DUE: Final = "force_due"
SERVICE_FORCE_INACTIVE: Final = "force_inactive"
SERVICE_FORCE_COMPLETE: Final = "force_complete"

# ── Attributes ──────────────────────────────────────────────────────
ATTR_CHORE_ID: Final = "chore_id"
ATTR_CHORE_NAME: Final = "chore_name"
ATTR_CHORE_TYPE: Final = "chore_type"
ATTR_DUE_SINCE: Final = "due_since"
ATTR_LAST_COMPLETED: Final = "last_completed"
ATTR_NEXT_DUE: Final = "next_due"
ATTR_STATE_ENTERED_AT: Final = "state_entered_at"
ATTR_TRIGGER_STATE: Final = "trigger_state"
ATTR_COMPLETION_STATE: Final = "completion_state"
ATTR_COMPLETION_TYPE: Final = "completion_type"
ATTR_FORCED: Final = "forced"
ATTR_PREVIOUS_STATE: Final = "previous_state"
ATTR_NEW_STATE: Final = "new_state"
ATTR_STATE_LABEL: Final = "state_label"

# ── Defaults ────────────────────────────────────────────────────────
DEFAULT_ICON: Final = "mdi:checkbox-marked-circle-outline"
DEFAULT_COOLDOWN_MINUTES: Final = 5
DEFAULT_POWER_THRESHOLD: Final = 10.0
DEFAULT_CURRENT_THRESHOLD: Final = 0.04

# ── Platforms ───────────────────────────────────────────────────────
PLATFORMS: Final = ["binary_sensor", "sensor", "button"]
