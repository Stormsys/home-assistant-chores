"""Tests for chore_core.py — Chore state machine orchestrator."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

from freezegun import freeze_time

from conftest import (
    MockHass,
    daily_gate_contact_config,
    daily_manual_config,
    duration_contact_cycle_config,
    power_cycle_config,
    state_change_presence_config,
    weekly_gate_manual_config,
)

from custom_components.chores.chore_core import Chore
from custom_components.chores.const import ChoreState, CompletionType, SubState

from homeassistant.util import dt as dt_util


# ── Initialization ───────────────────────────────────────────────────


class TestChoreInit:
    def test_basic_properties(self):
        c = Chore(daily_manual_config())
        assert c.id == "feed_fay_morning"
        assert c.name == "Feed Fay Morning"
        assert c.trigger_type == "daily"
        assert c.completion_type == "manual"

    def test_initial_state(self):
        c = Chore(daily_manual_config())
        assert c.state == ChoreState.INACTIVE
        assert c.due_since is None
        assert c.last_completed is None
        assert c.forced is False

    def test_custom_icon(self):
        c = Chore(daily_manual_config())
        assert c.icon == "mdi:dog-bowl"

    def test_default_icon(self):
        config = daily_manual_config()
        del config["icon"]
        c = Chore(config)
        assert "mdi:" in c.icon

    def test_default_state_labels(self):
        c = Chore(daily_manual_config())
        assert c.state_label == "Inactive"

    def test_custom_state_labels(self):
        config = daily_manual_config()
        config["state_labels"] = {"inactive": "All Good", "due": "Do it!"}
        c = Chore(config)
        assert c.state_label == "All Good"

    def test_description_and_context(self):
        c = Chore(daily_gate_contact_config())
        state_dict = c.to_state_dict(MockHass())
        assert state_dict["description"] is not None
        assert state_dict["context"] is not None

    def test_per_state_icons(self):
        config = daily_manual_config()
        config["icon_due"] = "mdi:alert"
        c = Chore(config)
        assert c.icon_for_state(ChoreState.DUE) == "mdi:alert"
        assert c.icon_for_state(ChoreState.INACTIVE) == "mdi:dog-bowl"

    def test_different_trigger_types(self):
        assert Chore(power_cycle_config()).trigger_type == "power_cycle"
        assert Chore(weekly_gate_manual_config()).trigger_type == "weekly"
        assert Chore(duration_contact_cycle_config()).trigger_type == "duration"
        assert Chore(state_change_presence_config()).trigger_type == "state_change"


# ── State transitions via evaluate() ────────────────────────────────


class TestEvaluateTransitions:
    def test_inactive_trigger_done_goes_due(self):
        c = Chore(daily_manual_config())
        c._trigger.set_state(SubState.DONE)
        hass = MockHass()
        old = c.evaluate(hass)
        assert c.state == ChoreState.DUE
        assert old == ChoreState.INACTIVE
        assert c.completion.enabled is True

    def test_inactive_trigger_active_goes_pending(self):
        c = Chore(daily_gate_contact_config())
        c._trigger.set_state(SubState.ACTIVE)
        hass = MockHass()
        old = c.evaluate(hass)
        assert c.state == ChoreState.PENDING
        assert old == ChoreState.INACTIVE

    def test_pending_trigger_done_goes_due(self):
        c = Chore(daily_gate_contact_config())
        c._trigger.set_state(SubState.ACTIVE)
        hass = MockHass()
        c.evaluate(hass)
        assert c.state == ChoreState.PENDING
        c._trigger.set_state(SubState.DONE)
        old = c.evaluate(hass)
        assert c.state == ChoreState.DUE
        assert old == ChoreState.PENDING

    def test_pending_trigger_idle_goes_inactive(self):
        # Use state_change config — its evaluate() is a no-op so it won't
        # re-trigger when we manually set the sub-state back to IDLE.
        c = Chore(state_change_presence_config())
        c._trigger.set_state(SubState.ACTIVE)
        hass = MockHass()
        c.evaluate(hass)
        assert c.state == ChoreState.PENDING
        c._trigger.set_state(SubState.IDLE)
        old = c.evaluate(hass)
        assert c.state == ChoreState.INACTIVE
        assert old == ChoreState.PENDING

    def test_due_completion_done_goes_completed(self):
        c = Chore(daily_manual_config())
        c._trigger.set_state(SubState.DONE)
        hass = MockHass()
        c.evaluate(hass)  # → DUE
        c._completion.set_state(SubState.DONE)
        old = c.evaluate(hass)
        assert c.state == ChoreState.COMPLETED
        assert old == ChoreState.DUE

    def test_due_completion_active_goes_started(self):
        """2-step completion: ACTIVE → STARTED."""
        c = Chore(duration_contact_cycle_config())
        c._trigger.set_state(SubState.DONE)
        hass = MockHass()
        c.evaluate(hass)  # → DUE
        c._completion.set_state(SubState.ACTIVE)
        old = c.evaluate(hass)
        assert c.state == ChoreState.STARTED
        assert old == ChoreState.DUE

    def test_started_completion_done_goes_completed(self):
        c = Chore(duration_contact_cycle_config())
        c._trigger.set_state(SubState.DONE)
        hass = MockHass()
        c.evaluate(hass)  # → DUE
        c._completion.set_state(SubState.ACTIVE)
        c.evaluate(hass)  # → STARTED
        c._completion.set_state(SubState.DONE)
        old = c.evaluate(hass)
        assert c.state == ChoreState.COMPLETED
        assert old == ChoreState.STARTED

    def test_completed_reset_goes_inactive(self):
        """ImplicitEventReset always resets → completed should immediately go inactive."""
        c = Chore(power_cycle_config())
        c._trigger.set_state(SubState.DONE)
        hass = MockHass()
        c.evaluate(hass)  # → DUE
        c._completion.set_state(SubState.DONE)
        c.evaluate(hass)  # → COMPLETED
        old = c.evaluate(hass)  # → INACTIVE (implicit event reset)
        assert c.state == ChoreState.INACTIVE
        assert old == ChoreState.COMPLETED

    def test_no_change_returns_none(self):
        # Use state_change config — DailyTrigger.evaluate() auto-fires when
        # past trigger time, so we use a trigger whose evaluate() is a no-op.
        c = Chore(state_change_presence_config())
        hass = MockHass()
        result = c.evaluate(hass)
        assert result is None


# ── Timestamps ───────────────────────────────────────────────────────


class TestTimestamps:
    def test_state_entered_at_updated(self):
        c = Chore(daily_manual_config())
        initial = c.state_entered_at
        c._trigger.set_state(SubState.DONE)
        c.evaluate(MockHass())
        assert c.state_entered_at > initial or c.state_entered_at == initial

    def test_due_sets_due_since(self):
        c = Chore(daily_manual_config())
        assert c.due_since is None
        c._trigger.set_state(SubState.DONE)
        c.evaluate(MockHass())
        assert c.due_since is not None

    def test_completed_sets_last_completed(self):
        c = Chore(daily_manual_config())
        assert c.last_completed is None
        c.force_complete()
        assert c.last_completed is not None

    def test_inactive_clears_due_since(self):
        c = Chore(daily_manual_config())
        c.force_due()
        assert c.due_since is not None
        c.force_inactive()
        assert c.due_since is None


# ── Force actions ────────────────────────────────────────────────────


class TestForceActions:
    def test_force_due(self):
        c = Chore(daily_manual_config())
        old = c.force_due()
        assert c.state == ChoreState.DUE
        assert c.forced is True
        assert old == ChoreState.INACTIVE

    def test_force_due_enables_completion(self):
        c = Chore(daily_manual_config())
        c.force_due()
        assert c.completion.enabled is True

    def test_force_inactive(self):
        c = Chore(daily_manual_config())
        c.force_due()
        old = c.force_inactive()
        assert c.state == ChoreState.INACTIVE
        assert c.forced is True
        assert old == ChoreState.DUE

    def test_force_complete(self):
        c = Chore(daily_manual_config())
        old = c.force_complete()
        assert c.state == ChoreState.COMPLETED
        assert c.forced is True
        assert old == ChoreState.INACTIVE

    def test_force_complete_disables_completion(self):
        c = Chore(daily_manual_config())
        c.force_complete()
        assert c.completion.enabled is False

    def test_force_due_already_due_returns_none(self):
        c = Chore(daily_manual_config())
        c.force_due()
        result = c.force_due()
        assert result is None

    def test_force_inactive_already_inactive_returns_none(self):
        c = Chore(daily_manual_config())
        result = c.force_inactive()
        assert result is None

    def test_force_from_any_state(self):
        """Force actions work from any state."""
        c = Chore(daily_manual_config())
        # INACTIVE → force_complete → COMPLETED
        c.force_complete()
        assert c.state == ChoreState.COMPLETED
        # COMPLETED → force_due → DUE
        c.force_due()
        assert c.state == ChoreState.DUE
        # DUE → force_inactive → INACTIVE
        c.force_inactive()
        assert c.state == ChoreState.INACTIVE


# ── Completion history ───────────────────────────────────────────────


class TestCompletionHistory:
    def test_records_completion(self):
        c = Chore(daily_manual_config())
        c.force_complete()
        assert len(c.completion_history) == 1
        assert c.completion_history[0]["completed_by"] == "forced"

    def test_manual_completion_recorded_as_manual(self):
        c = Chore(daily_manual_config())
        c._trigger.set_state(SubState.DONE)
        c.evaluate(MockHass())  # → DUE
        c._completion.set_state(SubState.DONE)
        c.evaluate(MockHass())  # → COMPLETED (natural)
        assert len(c.completion_history) == 1
        assert c.completion_history[0]["completed_by"] == "manual"

    def test_sensor_completion_recorded_as_sensor(self):
        config = daily_gate_contact_config()
        c = Chore(config)
        c._trigger.set_state(SubState.DONE)
        c.evaluate(MockHass())  # → DUE
        c._completion.set_state(SubState.DONE)
        c.evaluate(MockHass())  # → COMPLETED
        assert c.completion_history[0]["completed_by"] == "sensor"

    def test_history_capped_at_100(self):
        c = Chore(daily_manual_config())
        for _ in range(110):
            c.force_complete()
            c.force_inactive()
        assert len(c.completion_history) <= 100

    def test_completion_count_since(self):
        c = Chore(daily_manual_config())
        before = dt_util.utcnow()
        c.force_complete()
        c.force_inactive()
        c.force_complete()
        assert c.completion_count_since(before) == 2

    def test_last_completed_by(self):
        c = Chore(daily_manual_config())
        assert c.last_completed_by() is None
        c.force_complete()
        assert c.last_completed_by() == "forced"


# ── Persistence ──────────────────────────────────────────────────────


class TestPersistence:
    def test_snapshot_restore_round_trip(self):
        c = Chore(daily_manual_config())
        c.force_due()
        c.force_complete()
        snap = c.snapshot_state()
        c2 = Chore(daily_manual_config())
        c2.restore_state(snap)
        assert c2.state == ChoreState.COMPLETED
        assert c2.last_completed is not None
        assert c2.forced is True

    def test_snapshot_includes_trigger_and_completion(self):
        c = Chore(daily_manual_config())
        c.force_due()
        snap = c.snapshot_state()
        assert "trigger" in snap
        assert "completion" in snap
        assert "chore_state" in snap
        assert "completion_history" in snap

    def test_restore_preserves_history(self):
        c = Chore(daily_manual_config())
        c.force_complete()
        c.force_inactive()
        c.force_complete()
        snap = c.snapshot_state()
        c2 = Chore(daily_manual_config())
        c2.restore_state(snap)
        assert len(c2.completion_history) == 2

    def test_restore_with_empty_data(self):
        c = Chore(daily_manual_config())
        c.restore_state({})
        assert c.state == ChoreState.INACTIVE


# ── to_state_dict() ──────────────────────────────────────────────────


class TestToStateDict:
    def test_contains_required_fields(self):
        hass = MockHass()
        c = Chore(daily_manual_config())
        d = c.to_state_dict(hass)
        assert d["chore_id"] == "feed_fay_morning"
        assert d["trigger_state"] == "idle"
        assert d["completion_state"] == "idle"
        assert d["completion_type"] == "manual"
        assert d["state_label"] == "Inactive"
        assert d["forced"] is False
        assert "state_entered_at" in d

    def test_includes_due_since_when_due(self):
        hass = MockHass()
        c = Chore(daily_manual_config())
        c.force_due()
        d = c.to_state_dict(hass)
        assert d["due_since"] is not None

    def test_includes_completion_button_for_manual(self):
        hass = MockHass()
        c = Chore(daily_manual_config())
        c._completion_button_entity_id = "button.feed_fay_morning_force_complete"
        d = c.to_state_dict(hass)
        assert d["completion_button"] == "button.feed_fay_morning_force_complete"

    def test_no_completion_button_for_sensor(self):
        hass = MockHass()
        c = Chore(daily_gate_contact_config())
        d = c.to_state_dict(hass)
        assert "completion_button" not in d

    def test_next_due_for_daily(self):
        hass = MockHass()
        c = Chore(daily_manual_config())
        d = c.to_state_dict(hass)
        assert d["next_due"] is not None

    def test_no_next_due_for_power_cycle(self):
        hass = MockHass()
        c = Chore(power_cycle_config())
        d = c.to_state_dict(hass)
        assert d["next_due"] is None
