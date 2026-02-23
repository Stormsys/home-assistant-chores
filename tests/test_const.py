"""Tests for const.py — enum and constant smoke tests."""
from __future__ import annotations

from custom_components.chores.const import (
    ATTR_CHORE_ID,
    ATTR_CHORE_NAME,
    ATTR_COMPLETION_STATE,
    ATTR_FORCED,
    ATTR_NEW_STATE,
    ATTR_PREVIOUS_STATE,
    ATTR_TRIGGER_STATE,
    DEFAULT_COOLDOWN_MINUTES,
    DEFAULT_CURRENT_THRESHOLD,
    DEFAULT_ICON,
    DEFAULT_POWER_THRESHOLD,
    DOMAIN,
    EVENT_CHORE_COMPLETED,
    EVENT_CHORE_DUE,
    EVENT_CHORE_PENDING,
    EVENT_CHORE_RESET,
    EVENT_CHORE_STARTED,
    PLATFORMS,
    SERVICE_FORCE_COMPLETE,
    SERVICE_FORCE_DUE,
    SERVICE_FORCE_INACTIVE,
    ChoreState,
    CompletionType,
    ResetType,
    SubState,
    TriggerType,
)


class TestChoreState:
    def test_has_five_states(self):
        assert len(ChoreState) == 5

    def test_values(self):
        assert ChoreState.INACTIVE == "inactive"
        assert ChoreState.PENDING == "pending"
        assert ChoreState.DUE == "due"
        assert ChoreState.STARTED == "started"
        assert ChoreState.COMPLETED == "completed"

    def test_is_str_enum(self):
        assert isinstance(ChoreState.INACTIVE, str)


class TestSubState:
    def test_has_three_states(self):
        assert len(SubState) == 3

    def test_values(self):
        assert SubState.IDLE == "idle"
        assert SubState.ACTIVE == "active"
        assert SubState.DONE == "done"


class TestTriggerType:
    def test_has_five_types(self):
        assert len(TriggerType) == 5

    def test_values(self):
        expected = {"power_cycle", "state_change", "daily", "weekly", "duration"}
        assert {t.value for t in TriggerType} == expected


class TestCompletionType:
    def test_has_five_types(self):
        assert len(CompletionType) == 5

    def test_values(self):
        expected = {"manual", "sensor_state", "contact", "contact_cycle", "presence_cycle"}
        assert {t.value for t in CompletionType} == expected


class TestResetType:
    def test_has_five_types(self):
        assert len(ResetType) == 5

    def test_values(self):
        expected = {"delay", "daily_reset", "implicit_daily", "implicit_weekly", "implicit_event"}
        assert {t.value for t in ResetType} == expected


class TestEventNames:
    def test_event_names_have_domain_prefix(self):
        for event in [
            EVENT_CHORE_PENDING,
            EVENT_CHORE_DUE,
            EVENT_CHORE_STARTED,
            EVENT_CHORE_COMPLETED,
            EVENT_CHORE_RESET,
        ]:
            assert event.startswith("chores."), f"{event} should start with 'chores.'"


class TestConstants:
    def test_domain(self):
        assert DOMAIN == "chores"

    def test_defaults(self):
        assert DEFAULT_COOLDOWN_MINUTES == 5
        assert DEFAULT_POWER_THRESHOLD == 10.0
        assert DEFAULT_CURRENT_THRESHOLD == 0.04
        assert DEFAULT_ICON == "mdi:checkbox-marked-circle-outline"

    def test_platforms(self):
        assert "binary_sensor" in PLATFORMS
        assert "sensor" in PLATFORMS
        assert "button" in PLATFORMS

    def test_services(self):
        assert SERVICE_FORCE_DUE == "force_due"
        assert SERVICE_FORCE_INACTIVE == "force_inactive"
        assert SERVICE_FORCE_COMPLETE == "force_complete"
