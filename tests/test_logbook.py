"""Tests for logbook.py — event description messages and dispatcher."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from conftest import MockHass

from custom_components.chores.logbook import (
    _describe_completed,
    _describe_due,
    _describe_pending,
    _describe_reset,
    _describe_started,
    _get_chore,
    _get_entity_id,
    async_describe_events,
)
from custom_components.chores.const import (
    ATTR_CHORE_ID,
    ATTR_CHORE_NAME,
    ATTR_FORCED,
    CompletionType,
    DOMAIN,
    EVENT_CHORE_COMPLETED,
    EVENT_CHORE_DUE,
    EVENT_CHORE_PENDING,
    EVENT_CHORE_RESET,
    EVENT_CHORE_STARTED,
    TriggerType,
)


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


# ── _get_chore helper ─────────────────────────────────────────────────


class TestGetChore:
    def test_finds_chore(self):
        hass = MockHass()
        mock_chore = MagicMock()
        mock_coordinator = MagicMock()
        mock_coordinator.get_chore.return_value = mock_chore
        hass.data[DOMAIN] = {
            "yaml_config": {},
            "entry_1": {"coordinator": mock_coordinator},
        }
        result = _get_chore(hass, "my_chore")
        assert result == mock_chore

    def test_returns_none_when_not_found(self):
        hass = MockHass()
        mock_coordinator = MagicMock()
        mock_coordinator.get_chore.return_value = None
        hass.data[DOMAIN] = {
            "entry_1": {"coordinator": mock_coordinator},
        }
        result = _get_chore(hass, "nonexistent")
        assert result is None

    def test_returns_none_when_no_domain_data(self):
        hass = MockHass()
        result = _get_chore(hass, "any")
        assert result is None

    def test_skips_non_dict_entries(self):
        hass = MockHass()
        hass.data[DOMAIN] = {
            "yaml_config": {"chores": []},  # Not a dict with "coordinator"
        }
        result = _get_chore(hass, "any")
        assert result is None


# ── async_describe_events registration ────────────────────────────────


class TestAsyncDescribeEvents:
    def test_registers_all_five_events(self):
        hass = MockHass()
        registered = {}

        def fake_describe_event(domain, event_name, callback):
            registered[event_name] = callback

        async_describe_events(hass, fake_describe_event)
        assert EVENT_CHORE_PENDING in registered
        assert EVENT_CHORE_DUE in registered
        assert EVENT_CHORE_STARTED in registered
        assert EVENT_CHORE_COMPLETED in registered
        assert EVENT_CHORE_RESET in registered

    @patch("custom_components.chores.logbook._get_entity_id", return_value=None)
    def test_describe_callback_returns_none_when_logbook_disabled(self, _mock_eid):
        hass = MockHass()
        registered = {}

        def fake_describe_event(domain, event_name, callback):
            registered[event_name] = callback

        async_describe_events(hass, fake_describe_event)
        cb = registered[EVENT_CHORE_DUE]

        event = MagicMock()
        event.data = {
            ATTR_CHORE_ID: "test_chore",
            ATTR_CHORE_NAME: "Test Chore",
            ATTR_FORCED: False,
            "logbook_enabled": False,
        }
        event.event_type = EVENT_CHORE_DUE

        result = cb(event)
        assert result is None

    @patch("custom_components.chores.logbook._get_entity_id", return_value=None)
    def test_describe_callback_returns_entry_for_due(self, _mock_eid):
        hass = MockHass()
        # Set up a chore in hass.data so _get_chore finds it
        mock_chore = MagicMock()
        mock_chore.trigger_type = TriggerType.DAILY
        mock_chore.completion_type = CompletionType.MANUAL
        mock_coordinator = MagicMock()
        mock_coordinator.get_chore.return_value = mock_chore
        hass.data[DOMAIN] = {
            "entry_1": {"coordinator": mock_coordinator},
        }

        registered = {}

        def fake_describe_event(domain, event_name, callback):
            registered[event_name] = callback

        async_describe_events(hass, fake_describe_event)
        cb = registered[EVENT_CHORE_DUE]

        event = MagicMock()
        event.data = {
            ATTR_CHORE_ID: "test_chore",
            ATTR_CHORE_NAME: "Test Chore",
            ATTR_FORCED: False,
            "logbook_enabled": True,
        }
        event.event_type = EVENT_CHORE_DUE

        result = cb(event)
        assert result is not None
        assert result["name"] == "Test Chore"
        assert "message" in result
        assert "Scheduled" in result["message"] or "ready" in result["message"]

    @patch("custom_components.chores.logbook._get_entity_id", return_value=None)
    def test_describe_callback_for_pending(self, _mock_eid):
        hass = MockHass()
        mock_chore = MagicMock()
        mock_chore.trigger_type = TriggerType.POWER_CYCLE
        mock_coordinator = MagicMock()
        mock_coordinator.get_chore.return_value = mock_chore
        hass.data[DOMAIN] = {"e1": {"coordinator": mock_coordinator}}

        registered = {}
        async_describe_events(hass, lambda d, e, c: registered.update({e: c}))
        cb = registered[EVENT_CHORE_PENDING]

        event = MagicMock()
        event.data = {ATTR_CHORE_ID: "x", ATTR_CHORE_NAME: "X", ATTR_FORCED: False, "logbook_enabled": True}
        event.event_type = EVENT_CHORE_PENDING

        result = cb(event)
        assert result is not None
        assert "Appliance" in result["message"]

    @patch("custom_components.chores.logbook._get_entity_id", return_value=None)
    def test_describe_callback_for_started(self, _mock_eid):
        hass = MockHass()
        mock_chore = MagicMock()
        mock_chore.completion_type = CompletionType.CONTACT_CYCLE
        mock_coordinator = MagicMock()
        mock_coordinator.get_chore.return_value = mock_chore
        hass.data[DOMAIN] = {"e1": {"coordinator": mock_coordinator}}

        registered = {}
        async_describe_events(hass, lambda d, e, c: registered.update({e: c}))
        cb = registered[EVENT_CHORE_STARTED]

        event = MagicMock()
        event.data = {ATTR_CHORE_ID: "x", ATTR_CHORE_NAME: "X", ATTR_FORCED: False, "logbook_enabled": True}
        event.event_type = EVENT_CHORE_STARTED

        result = cb(event)
        assert result is not None
        assert "door" in result["message"].lower() or "step" in result["message"].lower()

    @patch("custom_components.chores.logbook._get_entity_id", return_value=None)
    def test_describe_callback_for_completed(self, _mock_eid):
        hass = MockHass()
        mock_chore = MagicMock()
        mock_chore.completion_type = CompletionType.PRESENCE_CYCLE
        mock_coordinator = MagicMock()
        mock_coordinator.get_chore.return_value = mock_chore
        hass.data[DOMAIN] = {"e1": {"coordinator": mock_coordinator}}

        registered = {}
        async_describe_events(hass, lambda d, e, c: registered.update({e: c}))
        cb = registered[EVENT_CHORE_COMPLETED]

        event = MagicMock()
        event.data = {ATTR_CHORE_ID: "x", ATTR_CHORE_NAME: "X", ATTR_FORCED: False, "logbook_enabled": True}
        event.event_type = EVENT_CHORE_COMPLETED

        result = cb(event)
        assert "home" in result["message"].lower() or "returned" in result["message"].lower()

    @patch("custom_components.chores.logbook._get_entity_id", return_value=None)
    def test_describe_callback_for_reset(self, _mock_eid):
        hass = MockHass()
        hass.data[DOMAIN] = {}

        registered = {}
        async_describe_events(hass, lambda d, e, c: registered.update({e: c}))
        cb = registered[EVENT_CHORE_RESET]

        event = MagicMock()
        event.data = {ATTR_CHORE_ID: "x", ATTR_CHORE_NAME: "X", ATTR_FORCED: True, "logbook_enabled": True}
        event.event_type = EVENT_CHORE_RESET

        result = cb(event)
        assert "Manually" in result["message"]

    @patch("custom_components.chores.logbook._get_entity_id", return_value=None)
    def test_describe_callback_unknown_event_returns_none(self, _mock_eid):
        hass = MockHass()
        hass.data[DOMAIN] = {}

        registered = {}
        async_describe_events(hass, lambda d, e, c: registered.update({e: c}))
        # Use the reset callback but with a bogus event_type
        cb = registered[EVENT_CHORE_RESET]

        event = MagicMock()
        event.data = {ATTR_CHORE_ID: "x", ATTR_CHORE_NAME: "X", ATTR_FORCED: False, "logbook_enabled": True}
        event.event_type = "chores.unknown_event"

        result = cb(event)
        assert result is None

    @patch("custom_components.chores.logbook._get_entity_id", return_value=None)
    def test_describe_callback_forced_due(self, _mock_eid):
        hass = MockHass()
        hass.data[DOMAIN] = {}

        registered = {}
        async_describe_events(hass, lambda d, e, c: registered.update({e: c}))
        cb = registered[EVENT_CHORE_DUE]

        event = MagicMock()
        event.data = {ATTR_CHORE_ID: "x", ATTR_CHORE_NAME: "X", ATTR_FORCED: True, "logbook_enabled": True}
        event.event_type = EVENT_CHORE_DUE

        result = cb(event)
        assert "Manually" in result["message"]
