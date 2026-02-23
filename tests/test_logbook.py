"""Tests for logbook.py — event description messages."""
from __future__ import annotations

from custom_components.chores.logbook import (
    _describe_completed,
    _describe_due,
    _describe_pending,
    _describe_reset,
    _describe_started,
)
from custom_components.chores.const import CompletionType, TriggerType


# ── _describe_pending ────────────────────────────────────────────────


class TestDescribePending:
    def test_forced(self):
        msg = _describe_pending(forced=True, trigger_type=TriggerType.DAILY)
        assert "Manually" in msg

    def test_power_cycle(self):
        msg = _describe_pending(forced=False, trigger_type=TriggerType.POWER_CYCLE)
        assert "Appliance" in msg or "cycle" in msg.lower()

    def test_state_change(self):
        msg = _describe_pending(forced=False, trigger_type=TriggerType.STATE_CHANGE)
        assert "condition" in msg.lower() or "trigger" in msg.lower()

    def test_daily(self):
        msg = _describe_pending(forced=False, trigger_type=TriggerType.DAILY)
        assert "Scheduled" in msg or "time" in msg.lower()

    def test_weekly(self):
        msg = _describe_pending(forced=False, trigger_type=TriggerType.WEEKLY)
        assert "Weekly" in msg or "schedule" in msg.lower()

    def test_duration(self):
        msg = _describe_pending(forced=False, trigger_type=TriggerType.DURATION)
        assert "duration" in msg.lower() or "Entity" in msg

    def test_unknown_fallback(self):
        msg = _describe_pending(forced=False, trigger_type=None)
        assert isinstance(msg, str) and len(msg) > 0


# ── _describe_due ────────────────────────────────────────────────────


class TestDescribeDue:
    def test_forced(self):
        msg = _describe_due(forced=True, trigger_type=TriggerType.DAILY)
        assert "Manually" in msg

    def test_power_cycle(self):
        msg = _describe_due(forced=False, trigger_type=TriggerType.POWER_CYCLE)
        assert "cycle" in msg.lower() or "complete" in msg.lower()

    def test_state_change(self):
        msg = _describe_due(forced=False, trigger_type=TriggerType.STATE_CHANGE)
        assert "condition" in msg.lower() or "trigger" in msg.lower()

    def test_daily(self):
        msg = _describe_due(forced=False, trigger_type=TriggerType.DAILY)
        assert "Scheduled" in msg or "time" in msg.lower() or "ready" in msg.lower()

    def test_weekly(self):
        msg = _describe_due(forced=False, trigger_type=TriggerType.WEEKLY)
        assert "Weekly" in msg or "schedule" in msg.lower() or "triggered" in msg.lower()

    def test_duration(self):
        msg = _describe_due(forced=False, trigger_type=TriggerType.DURATION)
        assert "Duration" in msg or "threshold" in msg.lower() or "reached" in msg.lower()


# ── _describe_started ────────────────────────────────────────────────


class TestDescribeStarted:
    def test_forced(self):
        msg = _describe_started(forced=True, completion_type=CompletionType.CONTACT_CYCLE)
        assert "Manually" in msg

    def test_contact_cycle(self):
        msg = _describe_started(forced=False, completion_type=CompletionType.CONTACT_CYCLE)
        assert "door" in msg.lower() or "step" in msg.lower()

    def test_presence_cycle(self):
        msg = _describe_started(forced=False, completion_type=CompletionType.PRESENCE_CYCLE)
        assert "home" in msg.lower() or "Left" in msg

    def test_unknown_fallback(self):
        msg = _describe_started(forced=False, completion_type=None)
        assert "Step" in msg or "step" in msg.lower()


# ── _describe_completed ──────────────────────────────────────────────


class TestDescribeCompleted:
    def test_forced(self):
        msg = _describe_completed(forced=True, completion_type=CompletionType.MANUAL)
        assert "Manually" in msg

    def test_manual(self):
        msg = _describe_completed(forced=False, completion_type=CompletionType.MANUAL)
        assert "Manually" in msg or "manual" in msg.lower()

    def test_contact(self):
        msg = _describe_completed(forced=False, completion_type=CompletionType.CONTACT)
        assert "contact" in msg.lower() or "Completed" in msg

    def test_contact_cycle(self):
        msg = _describe_completed(forced=False, completion_type=CompletionType.CONTACT_CYCLE)
        assert "door" in msg.lower() or "cycle" in msg.lower() or "Completed" in msg

    def test_presence_cycle(self):
        msg = _describe_completed(forced=False, completion_type=CompletionType.PRESENCE_CYCLE)
        assert "home" in msg.lower() or "returned" in msg.lower() or "Completed" in msg

    def test_sensor_state(self):
        msg = _describe_completed(forced=False, completion_type=CompletionType.SENSOR_STATE)
        assert "sensor" in msg.lower() or "triggered" in msg.lower() or "Completed" in msg


# ── _describe_reset ──────────────────────────────────────────────────


class TestDescribeReset:
    def test_forced(self):
        msg = _describe_reset(forced=True)
        assert "Manually" in msg

    def test_not_forced(self):
        msg = _describe_reset(forced=False)
        assert "Reset" in msg or "reset" in msg.lower() or "cycle" in msg.lower()
