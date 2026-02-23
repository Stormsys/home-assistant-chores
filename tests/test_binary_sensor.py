"""Tests for binary_sensor.py — NeedsAttentionBinarySensor."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.chores.binary_sensor import NeedsAttentionBinarySensor
from custom_components.chores.chore_core import Chore
from custom_components.chores.const import DOMAIN, ChoreState
from conftest import daily_manual_config


def _make_coordinator_mock() -> MagicMock:
    coord = MagicMock()
    coord.hass = MagicMock()
    return coord


def _make_entry_mock() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "test_entry"
    return entry


class TestNeedsAttentionBinarySensor:
    def test_unique_id(self):
        chore = Chore(daily_manual_config())
        sensor = NeedsAttentionBinarySensor(
            _make_coordinator_mock(), chore, _make_entry_mock()
        )
        assert sensor._attr_unique_id == f"{DOMAIN}_{chore.id}_attention"

    def test_name(self):
        chore = Chore(daily_manual_config())
        sensor = NeedsAttentionBinarySensor(
            _make_coordinator_mock(), chore, _make_entry_mock()
        )
        assert chore.name in sensor._attr_name

    def test_off_when_inactive(self):
        chore = Chore(daily_manual_config())
        sensor = NeedsAttentionBinarySensor(
            _make_coordinator_mock(), chore, _make_entry_mock()
        )
        assert chore.state == ChoreState.INACTIVE
        assert sensor.is_on is False

    def test_on_when_due(self):
        chore = Chore(daily_manual_config())
        sensor = NeedsAttentionBinarySensor(
            _make_coordinator_mock(), chore, _make_entry_mock()
        )
        chore.force_due()
        assert chore.state == ChoreState.DUE
        assert sensor.is_on is True

    def test_on_when_started(self):
        """For a 2-step completion, STARTED also needs attention."""
        from conftest import daily_presence_config

        chore = Chore(daily_presence_config())
        sensor = NeedsAttentionBinarySensor(
            _make_coordinator_mock(), chore, _make_entry_mock()
        )
        chore.force_due()
        # Simulate step 1 of presence_cycle
        chore.completion.enable()
        chore.completion.set_state(
            __import__("custom_components.chores.const", fromlist=["SubState"]).SubState.ACTIVE
        )
        chore.evaluate(MagicMock())
        assert chore.state == ChoreState.STARTED
        assert sensor.is_on is True

    def test_off_when_completed(self):
        chore = Chore(daily_manual_config())
        sensor = NeedsAttentionBinarySensor(
            _make_coordinator_mock(), chore, _make_entry_mock()
        )
        chore.force_complete()
        assert chore.state == ChoreState.COMPLETED
        assert sensor.is_on is False

    def test_off_when_pending(self):
        chore = Chore(daily_manual_config())
        sensor = NeedsAttentionBinarySensor(
            _make_coordinator_mock(), chore, _make_entry_mock()
        )
        # Pending = trigger active but not done yet
        from custom_components.chores.const import SubState

        chore.trigger.set_state(SubState.ACTIVE)
        chore.evaluate(MagicMock())
        assert chore.state == ChoreState.PENDING
        assert sensor.is_on is False

    def test_extra_state_attributes(self):
        chore = Chore(daily_manual_config())
        sensor = NeedsAttentionBinarySensor(
            _make_coordinator_mock(), chore, _make_entry_mock()
        )
        attrs = sensor.extra_state_attributes
        assert attrs["chore_id"] == chore.id
        assert attrs["chore_state"] == ChoreState.INACTIVE.value
        assert attrs["due_since"] is None

    def test_attributes_when_due(self):
        chore = Chore(daily_manual_config())
        sensor = NeedsAttentionBinarySensor(
            _make_coordinator_mock(), chore, _make_entry_mock()
        )
        chore.force_due()
        attrs = sensor.extra_state_attributes
        assert attrs["chore_state"] == ChoreState.DUE.value
        assert attrs["due_since"] is not None
