"""Tests for diagnostics.py — async_get_config_entry_diagnostics."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from conftest import MockHass, daily_manual_config, power_cycle_config

from custom_components.chores.chore_core import Chore
from custom_components.chores.const import ChoreState, DOMAIN


class TestDiagnostics:
    @pytest.mark.asyncio
    async def test_returns_chore_data(self):
        from custom_components.chores.diagnostics import async_get_config_entry_diagnostics

        hass = MockHass()
        entry = MagicMock()
        entry.entry_id = "test_entry"
        entry.version = 2

        # Build a coordinator with chores
        from custom_components.chores.coordinator import ChoresCoordinator

        store = MagicMock()
        store.get_chore_state = MagicMock(return_value=None)

        coord = ChoresCoordinator(hass, entry, store)
        c1 = Chore(daily_manual_config())
        c2 = Chore(power_cycle_config())
        coord.register_chore(c1)
        coord.register_chore(c2)

        hass.data[DOMAIN] = {
            entry.entry_id: {"coordinator": coord},
        }

        result = await async_get_config_entry_diagnostics(hass, entry)

        assert "config_entry" in result
        assert result["config_entry"]["entry_id"] == "test_entry"
        assert result["config_entry"]["version"] == 2

        assert "chores" in result
        assert c1.id in result["chores"]
        assert c2.id in result["chores"]

        c1_data = result["chores"][c1.id]
        assert c1_data["chore_name"] == c1.name
        assert c1_data["state"] == ChoreState.INACTIVE.value
        assert c1_data["trigger"]["type"] == c1.trigger_type
        assert c1_data["completion"]["type"] == c1.completion_type
        assert "snapshot" in c1_data["trigger"]
        assert "snapshot" in c1_data["completion"]

    @pytest.mark.asyncio
    async def test_includes_due_since_when_due(self):
        from custom_components.chores.diagnostics import async_get_config_entry_diagnostics
        from custom_components.chores.coordinator import ChoresCoordinator

        hass = MockHass()
        entry = MagicMock()
        entry.entry_id = "test"
        entry.version = 2

        store = MagicMock()
        store.get_chore_state = MagicMock(return_value=None)

        coord = ChoresCoordinator(hass, entry, store)
        chore = Chore(daily_manual_config())
        coord.register_chore(chore)
        chore.force_due()

        hass.data[DOMAIN] = {entry.entry_id: {"coordinator": coord}}

        result = await async_get_config_entry_diagnostics(hass, entry)
        assert result["chores"][chore.id]["due_since"] is not None
