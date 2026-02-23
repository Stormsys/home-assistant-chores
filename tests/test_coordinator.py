"""Tests for coordinator.py — ChoresCoordinator."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from conftest import MockHass, daily_manual_config, power_cycle_config

from custom_components.chores.chore_core import Chore
from custom_components.chores.const import (
    ChoreState,
    EVENT_CHORE_COMPLETED,
    EVENT_CHORE_DUE,
    EVENT_CHORE_PENDING,
    EVENT_CHORE_RESET,
    EVENT_CHORE_STARTED,
    SubState,
)
from custom_components.chores.coordinator import (
    STATE_EVENT_MAP,
    ChoresCoordinator,
)
from custom_components.chores.store import ChoreStore


def _make_coordinator(hass=None, logbook_enabled=True):
    """Create a coordinator with a mock hass, entry, and store."""
    if hass is None:
        hass = MockHass()
    entry = MagicMock()
    entry.entry_id = "test_entry"
    store = MagicMock(spec=ChoreStore)
    store.get_chore_state = MagicMock(return_value=None)
    store.set_chore_state = MagicMock()
    store.async_save = AsyncMock()
    coord = ChoresCoordinator(hass, entry, store, logbook_enabled=logbook_enabled)
    return coord, store


class TestStateEventMap:
    def test_all_states_mapped(self):
        assert ChoreState.PENDING in STATE_EVENT_MAP
        assert ChoreState.DUE in STATE_EVENT_MAP
        assert ChoreState.STARTED in STATE_EVENT_MAP
        assert ChoreState.COMPLETED in STATE_EVENT_MAP
        assert ChoreState.INACTIVE in STATE_EVENT_MAP

    def test_correct_events(self):
        assert STATE_EVENT_MAP[ChoreState.PENDING] == EVENT_CHORE_PENDING
        assert STATE_EVENT_MAP[ChoreState.DUE] == EVENT_CHORE_DUE
        assert STATE_EVENT_MAP[ChoreState.STARTED] == EVENT_CHORE_STARTED
        assert STATE_EVENT_MAP[ChoreState.COMPLETED] == EVENT_CHORE_COMPLETED
        assert STATE_EVENT_MAP[ChoreState.INACTIVE] == EVENT_CHORE_RESET


class TestRegisterChore:
    def test_registers_chore(self):
        coord, store = _make_coordinator()
        chore = Chore(daily_manual_config())
        coord.register_chore(chore)
        assert coord.get_chore("feed_fay_morning") is chore

    def test_restores_persisted_state(self):
        coord, store = _make_coordinator()
        store.get_chore_state.return_value = {
            "chore_state": "due",
            "state_entered_at": "2025-06-15T10:00:00+00:00",
            "trigger": {"state": "done", "state_entered_at": "2025-06-15T10:00:00+00:00", "time_fired_today": True},
            "completion": {"state": "idle", "state_entered_at": "2025-06-15T10:00:00+00:00", "steps_done": 0, "enabled": True},
            "completion_history": [],
        }
        chore = Chore(daily_manual_config())
        coord.register_chore(chore)
        assert chore.state == ChoreState.DUE

    def test_no_persisted_state(self):
        coord, store = _make_coordinator()
        store.get_chore_state.return_value = None
        chore = Chore(daily_manual_config())
        coord.register_chore(chore)
        assert chore.state == ChoreState.INACTIVE

    def test_chores_property(self):
        coord, store = _make_coordinator()
        c1 = Chore(daily_manual_config())
        c2 = Chore(power_cycle_config())
        coord.register_chore(c1)
        coord.register_chore(c2)
        assert len(coord.chores) == 2
        assert "feed_fay_morning" in coord.chores
        assert "unload_washing" in coord.chores


class TestGetChore:
    def test_existing(self):
        coord, _ = _make_coordinator()
        chore = Chore(daily_manual_config())
        coord.register_chore(chore)
        assert coord.get_chore("feed_fay_morning") is chore

    def test_nonexistent(self):
        coord, _ = _make_coordinator()
        assert coord.get_chore("nonexistent") is None


class TestFireEvent:
    def test_fires_event_with_correct_data(self):
        hass = MockHass()
        coord, _ = _make_coordinator(hass)
        chore = Chore(daily_manual_config())
        coord.register_chore(chore)
        coord._fire_event(chore, ChoreState.INACTIVE, ChoreState.DUE)
        assert len(hass.bus.events) == 1
        event_type, event_data = hass.bus.events[0]
        assert event_type == EVENT_CHORE_DUE
        assert event_data["chore_id"] == "feed_fay_morning"
        assert event_data["chore_name"] == "Feed Fay Morning"
        assert event_data["previous_state"] == "inactive"
        assert event_data["new_state"] == "due"
        assert event_data["logbook_enabled"] is True

    def test_logbook_disabled_in_event(self):
        hass = MockHass()
        coord, _ = _make_coordinator(hass, logbook_enabled=False)
        chore = Chore(daily_manual_config())
        coord.register_chore(chore)
        coord._fire_event(chore, ChoreState.INACTIVE, ChoreState.DUE)
        _, event_data = hass.bus.events[0]
        assert event_data["logbook_enabled"] is False

    def test_forced_flag_in_event(self):
        hass = MockHass()
        coord, _ = _make_coordinator(hass)
        chore = Chore(daily_manual_config())
        chore.force_due()
        coord.register_chore(chore)
        coord._fire_event(chore, ChoreState.INACTIVE, ChoreState.DUE)
        _, event_data = hass.bus.events[0]
        assert event_data["forced"] is True


class TestForceActions:
    @pytest.mark.asyncio
    async def test_force_due(self):
        hass = MockHass()
        coord, store = _make_coordinator(hass)
        chore = Chore(daily_manual_config())
        coord.register_chore(chore)
        await coord.async_force_due("feed_fay_morning")
        assert chore.state == ChoreState.DUE
        assert len(hass.bus.events) == 1
        store.set_chore_state.assert_called()

    @pytest.mark.asyncio
    async def test_force_inactive(self):
        hass = MockHass()
        coord, store = _make_coordinator(hass)
        chore = Chore(daily_manual_config())
        coord.register_chore(chore)
        chore.force_due()
        hass.bus.clear()
        await coord.async_force_inactive("feed_fay_morning")
        assert chore.state == ChoreState.INACTIVE
        assert len(hass.bus.events) == 1

    @pytest.mark.asyncio
    async def test_force_complete(self):
        hass = MockHass()
        coord, store = _make_coordinator(hass)
        chore = Chore(daily_manual_config())
        coord.register_chore(chore)
        await coord.async_force_complete("feed_fay_morning")
        assert chore.state == ChoreState.COMPLETED

    @pytest.mark.asyncio
    async def test_force_nonexistent_logs_warning(self):
        coord, _ = _make_coordinator()
        # Should not raise
        await coord.async_force_due("nonexistent")
        await coord.async_force_inactive("nonexistent")
        await coord.async_force_complete("nonexistent")


class TestPersistChore:
    def test_persist_calls_store(self):
        coord, store = _make_coordinator()
        chore = Chore(daily_manual_config())
        coord.register_chore(chore)
        coord._persist_chore(chore)
        store.set_chore_state.assert_called_once_with(
            "feed_fay_morning", chore.snapshot_state()
        )
