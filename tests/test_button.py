"""Tests for button.py — force action button entities."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.chores.button import (
    ForceCompleteButton,
    ForceDueButton,
    ForceInactiveButton,
)
from custom_components.chores.chore_core import Chore
from custom_components.chores.const import DOMAIN
from conftest import daily_manual_config


def _make_coordinator_mock() -> MagicMock:
    coord = MagicMock()
    coord.async_force_due = AsyncMock()
    coord.async_force_inactive = AsyncMock()
    coord.async_force_complete = AsyncMock()
    return coord


class TestForceDueButton:
    def test_unique_id(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock()
        btn = ForceDueButton(coord, chore)

        assert btn._attr_unique_id == f"{DOMAIN}_{chore.id}_force_due"

    def test_name(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock()
        btn = ForceDueButton(coord, chore)

        assert btn._attr_name == "Force Due"

    def test_icon(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock()
        btn = ForceDueButton(coord, chore)

        assert btn._attr_icon == "mdi:alert-circle"

    @pytest.mark.asyncio
    async def test_press_calls_coordinator(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock()
        btn = ForceDueButton(coord, chore)

        await btn.async_press()
        coord.async_force_due.assert_awaited_once_with(chore.id)


class TestForceInactiveButton:
    def test_unique_id(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock()
        btn = ForceInactiveButton(coord, chore)

        assert btn._attr_unique_id == f"{DOMAIN}_{chore.id}_force_inactive"

    def test_name(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock()
        btn = ForceInactiveButton(coord, chore)

        assert btn._attr_name == "Force Inactive"

    def test_icon(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock()
        btn = ForceInactiveButton(coord, chore)

        assert btn._attr_icon == "mdi:cancel"

    @pytest.mark.asyncio
    async def test_press_calls_coordinator(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock()
        btn = ForceInactiveButton(coord, chore)

        await btn.async_press()
        coord.async_force_inactive.assert_awaited_once_with(chore.id)


class TestForceCompleteButton:
    def test_unique_id(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock()
        btn = ForceCompleteButton(coord, chore)

        assert btn._attr_unique_id == f"{DOMAIN}_{chore.id}_force_complete"

    def test_name(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock()
        btn = ForceCompleteButton(coord, chore)

        assert btn._attr_name == "Force Complete"

    def test_icon(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock()
        btn = ForceCompleteButton(coord, chore)

        assert btn._attr_icon == "mdi:check-circle"

    @pytest.mark.asyncio
    async def test_press_calls_coordinator(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock()
        btn = ForceCompleteButton(coord, chore)

        await btn.async_press()
        coord.async_force_complete.assert_awaited_once_with(chore.id)


class TestDeviceInfo:
    """All buttons should have proper device_info linking them to the chore device."""

    def test_device_identifiers(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock()

        for BtnClass in [ForceDueButton, ForceInactiveButton, ForceCompleteButton]:
            btn = BtnClass(coord, chore)
            info = btn._attr_device_info
            assert info is not None
            # DeviceInfo is our _StubDeviceInfo (dict subclass with attrs)
            identifiers = getattr(info, "identifiers", None) or info.get("identifiers")
            assert identifiers is not None
            assert (DOMAIN, chore.id) in identifiers
