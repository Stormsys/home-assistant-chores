"""Chore state machine orchestrator.

A Chore holds exactly one Trigger, one Completion, and one Reset.
It does not contain any type-specific logic -- that lives in the
trigger/completion/reset modules.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .completions import BaseCompletion, create_completion
from .const import (
    ATTR_CHORE_ID,
    ATTR_CHORE_NAME,
    ATTR_CHORE_TYPE,
    ATTR_COMPLETION_BUTTON,
    ATTR_COMPLETION_STATE,
    ATTR_COMPLETION_TYPE,
    ATTR_DUE_SINCE,
    ATTR_FORCED,
    ATTR_LAST_COMPLETED,
    ATTR_NEXT_DUE,
    ATTR_STATE_ENTERED_AT,
    ATTR_STATE_LABEL,
    ATTR_TRIGGER_STATE,
    ChoreState,
    CONF_LOGBOOK,
    CompletionType,
    DEFAULT_ICON,
    SubState,
)
from .resets import BaseReset, create_reset
from .triggers import BaseTrigger, DailyTrigger, create_trigger

_LOGGER = logging.getLogger(__name__)


class Chore:
    """State machine orchestrator for a single chore.

    Manages the lifecycle: inactive -> pending -> due -> started -> completed -> inactive
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._id: str = config["id"]
        self._name: str = config["name"]
        self._icon: str = config.get("icon", "mdi:checkbox-marked-circle-outline")

        # Build components from config
        self._trigger: BaseTrigger = create_trigger(config["trigger"])
        self._completion: BaseCompletion = create_completion(
            config.get("completion", {"type": "manual"})
        )
        self._reset: BaseReset = create_reset(
            config.get("reset"),
            self._trigger.trigger_type,
            config["trigger"],
        )

        # State labels (default to capitalized state names)
        state_labels_config = config.get("state_labels", {})
        self._state_labels: dict[str, str] = {
            "inactive": state_labels_config.get("inactive", "Inactive"),
            "pending": state_labels_config.get("pending", "Pending"),
            "due": state_labels_config.get("due", "Due"),
            "started": state_labels_config.get("started", "Started"),
            "completed": state_labels_config.get("completed", "Completed"),
        }

        # Per-state icons (optional; fall back to single icon then DEFAULT_ICON)
        default_icon = config.get("icon", DEFAULT_ICON)
        self._state_icons: dict[ChoreState, str] = {
            ChoreState.INACTIVE: config.get("icon_inactive") or default_icon,
            ChoreState.PENDING: config.get("icon_pending") or default_icon,
            ChoreState.DUE: config.get("icon_due") or default_icon,
            ChoreState.STARTED: config.get("icon_started") or default_icon,
            ChoreState.COMPLETED: config.get("icon_completed") or default_icon,
        }

        # Resolved entity_id for completion button (manual only); set by coordinator
        self._completion_button_entity_id: str | None = None

        # State
        self._state: ChoreState = ChoreState.INACTIVE
        self._state_entered_at: datetime = dt_util.utcnow()
        self._due_since: datetime | None = None
        self._last_completed: datetime | None = None
        self._forced: bool = False

        # Logbook setting
        self._logbook_enabled: bool = config.get(CONF_LOGBOOK, True)

        # Completion history for stats
        self._completion_history: list[dict[str, Any]] = []

    # ── Properties ──────────────────────────────────────────────────

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def icon(self) -> str:
        return self.icon_for_state(self._state)

    def icon_for_state(self, state: ChoreState) -> str:
        """Return icon for a given chore state (uses per-state config or fallback)."""
        return self._state_icons.get(state, self._icon or DEFAULT_ICON)

    @property
    def state(self) -> ChoreState:
        return self._state

    @property
    def state_entered_at(self) -> datetime:
        return self._state_entered_at

    @property
    def due_since(self) -> datetime | None:
        return self._due_since

    @property
    def last_completed(self) -> datetime | None:
        return self._last_completed

    @property
    def forced(self) -> bool:
        return self._forced

    @property
    def trigger(self) -> BaseTrigger:
        return self._trigger

    @property
    def completion(self) -> BaseCompletion:
        return self._completion

    @property
    def reset_handler(self) -> BaseReset:
        return self._reset

    @property
    def trigger_type(self) -> str:
        return self._trigger.trigger_type.value

    @property
    def completion_type(self) -> str:
        return self._completion.completion_type.value

    @property
    def next_due(self) -> datetime | None:
        """Next predicted due time (daily triggers only)."""
        if isinstance(self._trigger, DailyTrigger):
            return self._trigger.next_trigger_datetime
        return None

    @property
    def state_label(self) -> str:
        """Return human-readable label for current state."""
        return self._state_labels.get(self._state.value, self._state.value.capitalize())

    @property
    def logbook_enabled(self) -> bool:
        """Return whether logbook entries are enabled for this chore."""
        return self._logbook_enabled

    # ── State transitions ───────────────────────────────────────────

    def _set_state(self, new_state: ChoreState, forced: bool = False) -> ChoreState | None:
        """Set chore state. Returns old state if changed, None otherwise."""
        if new_state == self._state:
            return None
        old = self._state
        self._state = new_state
        self._state_entered_at = dt_util.utcnow()
        self._forced = forced

        if new_state == ChoreState.DUE:
            self._due_since = dt_util.utcnow()
        elif new_state == ChoreState.COMPLETED:
            self._last_completed = dt_util.utcnow()
            self._record_completion(forced)
        elif new_state == ChoreState.INACTIVE:
            self._due_since = None

        _LOGGER.debug("Chore %s: %s -> %s%s", self._id, old, new_state, " (forced)" if forced else "")
        return old

    def _record_completion(self, forced: bool) -> None:
        """Record a completion in history."""
        record = {
            "completed_at": dt_util.utcnow().isoformat(),
            "completed_by": "forced" if forced else (
                "manual" if self._completion.completion_type.value == "manual"
                else "sensor"
            ),
        }
        self._completion_history.append(record)
        # Keep last 100 records in memory
        if len(self._completion_history) > 100:
            self._completion_history = self._completion_history[-100:]

    # ── Core evaluate (called on every coordinator poll) ────────────

    def evaluate(self, hass: HomeAssistant) -> ChoreState | None:
        """Evaluate state machine. Returns old state if changed, None if unchanged."""
        # Let trigger evaluate (for time-based checks like cooldown)
        self._trigger.evaluate(hass)

        # Check for state transitions based on current state
        if self._state == ChoreState.INACTIVE:
            return self._evaluate_inactive()
        elif self._state == ChoreState.PENDING:
            return self._evaluate_pending()
        elif self._state == ChoreState.DUE:
            return self._evaluate_due()
        elif self._state == ChoreState.STARTED:
            return self._evaluate_started()
        elif self._state == ChoreState.COMPLETED:
            return self._evaluate_completed()
        return None

    def _evaluate_inactive(self) -> ChoreState | None:
        """inactive: wait for trigger."""
        if self._trigger.state == SubState.DONE:
            self._completion.enable()
            return self._set_state(ChoreState.DUE)
        if self._trigger.state == SubState.ACTIVE:
            return self._set_state(ChoreState.PENDING)
        return None

    def _evaluate_pending(self) -> ChoreState | None:
        """pending: wait for trigger to complete (gate) or fall back to idle."""
        if self._trigger.state == SubState.DONE:
            self._completion.enable()
            return self._set_state(ChoreState.DUE)
        if self._trigger.state == SubState.IDLE:
            return self._set_state(ChoreState.INACTIVE)
        return None

    def _evaluate_due(self) -> ChoreState | None:
        """due: wait for completion."""
        if self._completion.state == SubState.DONE:
            return self._set_state(ChoreState.COMPLETED)
        if self._completion.state == SubState.ACTIVE:
            return self._set_state(ChoreState.STARTED)
        return None

    def _evaluate_started(self) -> ChoreState | None:
        """started: wait for completion step 2."""
        if self._completion.state == SubState.DONE:
            return self._set_state(ChoreState.COMPLETED)
        return None

    def _evaluate_completed(self) -> ChoreState | None:
        """completed: wait for reset condition."""
        if self._reset.should_reset(self._state_entered_at):
            self._trigger.reset()
            self._completion.reset()
            return self._set_state(ChoreState.INACTIVE)
        return None

    # ── Force actions ───────────────────────────────────────────────

    def force_due(self) -> ChoreState | None:
        """Force chore to due from any state."""
        self._trigger.set_state(SubState.DONE)
        self._completion.reset()
        self._completion.enable()
        return self._set_state(ChoreState.DUE, forced=True)

    def force_inactive(self) -> ChoreState | None:
        """Force chore to inactive from any state."""
        self._trigger.reset()
        self._completion.reset()
        return self._set_state(ChoreState.INACTIVE, forced=True)

    def force_complete(self) -> ChoreState | None:
        """Force chore to completed from any state."""
        self._completion.set_state(SubState.DONE)
        self._completion.disable()
        return self._set_state(ChoreState.COMPLETED, forced=True)

    # ── Listener setup ──────────────────────────────────────────────

    def async_setup_listeners(self, hass: HomeAssistant, on_update: callback) -> None:
        """Set up all event listeners for this chore."""

        @callback
        def _on_trigger_change() -> None:
            """Called when trigger state changes."""
            old = self.evaluate(hass)
            if old is not None:
                on_update(self._id, old, self._state)

        @callback
        def _on_completion_change() -> None:
            """Called when completion state changes."""
            old = self.evaluate(hass)
            if old is not None:
                on_update(self._id, old, self._state)

        self._trigger.async_setup_listeners(hass, _on_trigger_change)
        self._completion.async_setup_listeners(hass, _on_completion_change)

    def async_remove_listeners(self) -> None:
        """Remove all event listeners."""
        self._trigger.async_remove_listeners()
        self._completion.async_remove_listeners()

    # ── State dict (for entities to read) ───────────────────────────

    def to_state_dict(self, hass: HomeAssistant) -> dict[str, Any]:
        """Return the full state dict for entities to consume."""
        result: dict[str, Any] = {
            ATTR_CHORE_ID: self._id,
            ATTR_CHORE_TYPE: self._trigger.trigger_type.value,
            ATTR_DUE_SINCE: self._due_since.isoformat() if self._due_since else None,
            ATTR_LAST_COMPLETED: self._last_completed.isoformat() if self._last_completed else None,
            ATTR_NEXT_DUE: self.next_due.isoformat() if self.next_due else None,
            ATTR_STATE_ENTERED_AT: self._state_entered_at.isoformat(),
            ATTR_STATE_LABEL: self.state_label,
            ATTR_TRIGGER_STATE: self._trigger.state.value,
            ATTR_COMPLETION_STATE: self._completion.state.value,
            ATTR_COMPLETION_TYPE: self._completion.completion_type.value,
            ATTR_FORCED: self._forced,
        }
        if self._completion.completion_type == CompletionType.MANUAL and self._completion_button_entity_id:
            result[ATTR_COMPLETION_BUTTON] = self._completion_button_entity_id
        return result

    # ── Persistence ─────────────────────────────────────────────────

    def snapshot_state(self) -> dict[str, Any]:
        """Return full state for persistence."""
        return {
            "chore_state": self._state.value,
            "state_entered_at": self._state_entered_at.isoformat(),
            "due_since": self._due_since.isoformat() if self._due_since else None,
            "last_completed": self._last_completed.isoformat() if self._last_completed else None,
            "forced": self._forced,
            "trigger": self._trigger.snapshot_state(),
            "completion": self._completion.snapshot_state(),
            "completion_history": self._completion_history[-100:],
        }

    def restore_state(self, data: dict[str, Any]) -> None:
        """Restore state from persistence."""
        if "chore_state" in data:
            self._state = ChoreState(data["chore_state"])
        if "state_entered_at" in data:
            self._state_entered_at = dt_util.parse_datetime(data["state_entered_at"]) or dt_util.utcnow()
        if data.get("due_since"):
            self._due_since = dt_util.parse_datetime(data["due_since"])
        if data.get("last_completed"):
            self._last_completed = dt_util.parse_datetime(data["last_completed"])
        self._forced = data.get("forced", False)
        if "trigger" in data:
            self._trigger.restore_state(data["trigger"])
        if "completion" in data:
            self._completion.restore_state(data["completion"])
        self._completion_history = data.get("completion_history", [])

    # ── Completion history helpers ──────────────────────────────────

    @property
    def completion_history(self) -> list[dict[str, Any]]:
        return self._completion_history

    def completion_count_since(self, since: datetime) -> int:
        """Count completions since a given datetime."""
        count = 0
        for record in self._completion_history:
            completed_at = dt_util.parse_datetime(record["completed_at"])
            if completed_at and completed_at >= since:
                count += 1
        return count

    def last_completed_by(self) -> str | None:
        """Return how the last completion was triggered."""
        if self._completion_history:
            return self._completion_history[-1].get("completed_by")
        return None
