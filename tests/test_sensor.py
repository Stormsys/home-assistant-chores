"""Tests for sensor.py — sensor entity classes."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.chores.chore_core import Chore
from custom_components.chores.const import (
    DOMAIN,
    ChoreState,
    CompletionType,
    SubState,
    TriggerType,
)
from custom_components.chores.sensor import (
    ChoreStateSensor,
    CompletionProgressSensor,
    LastCompletedSensor,
    ResetProgressSensor,
    TriggerProgressSensor,
)
from conftest import (
    daily_manual_config,
    daily_gate_contact_config,
    daily_presence_config,
    daily_sensor_threshold_config,
    weekly_gate_manual_config,
    power_cycle_config,
    state_change_presence_config,
    duration_contact_cycle_config,
)


def _make_coordinator_mock(chore: Chore) -> MagicMock:
    """Build a minimal mock coordinator."""
    coord = MagicMock()
    coord.hass = MagicMock()
    coord.hass.data = {}
    return coord


def _make_entry_mock() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "test_entry"
    return entry


# ── ChoreStateSensor ──────────────────────────────────────────────────


class TestChoreStateSensor:
    def test_unique_id_and_name(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = ChoreStateSensor(coord, chore, entry)

        assert sensor._attr_unique_id == f"{DOMAIN}_{chore.id}"
        assert sensor._attr_name == chore.name

    def test_native_value_reflects_state(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = ChoreStateSensor(coord, chore, entry)

        assert sensor.native_value == ChoreState.INACTIVE.value

    def test_icon_from_chore(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = ChoreStateSensor(coord, chore, entry)

        assert sensor.icon == chore.icon

    def test_options_contain_all_states(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = ChoreStateSensor(coord, chore, entry)

        for state in ChoreState:
            assert state.value in sensor._attr_options


# ── TriggerProgressSensor ─────────────────────────────────────────────


class TestTriggerProgressSensor:
    def test_daily_defaults(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = TriggerProgressSensor(coord, chore, entry)

        assert sensor._attr_unique_id == f"{DOMAIN}_{chore.id}_trigger"
        assert "Daily at" in sensor._attr_name
        assert "08:00" in sensor._attr_name
        assert sensor._icon_idle == "mdi:calendar-clock"
        assert sensor._icon_active == "mdi:calendar-alert"
        assert sensor._icon_done == "mdi:calendar-check"

    def test_weekly_defaults(self):
        chore = Chore(weekly_gate_manual_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = TriggerProgressSensor(coord, chore, entry)

        assert "Wed" in sensor._attr_name
        assert "Fri" in sensor._attr_name
        assert sensor._icon_idle == "mdi:calendar-week"

    def test_power_cycle_defaults(self):
        chore = Chore(power_cycle_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = TriggerProgressSensor(coord, chore, entry)

        assert sensor._attr_name == "Washing Machine"  # from sensor config
        assert sensor._icon_idle == "mdi:washing-machine-off"  # from sensor config

    def test_power_cycle_no_sensor_config(self):
        """Power cycle with no sensor config uses defaults."""
        config = power_cycle_config()
        del config["trigger"]["sensor"]
        chore = Chore(config)
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = TriggerProgressSensor(coord, chore, entry)

        assert sensor._attr_name == "Power Monitor"
        assert sensor._icon_idle == "mdi:power-plug-off"

    def test_state_change_defaults(self):
        chore = Chore(state_change_presence_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = TriggerProgressSensor(coord, chore, entry)

        assert sensor._attr_name == "State Monitor"
        assert sensor._icon_idle == "mdi:toggle-switch-off-outline"

    def test_duration_defaults(self):
        chore = Chore(duration_contact_cycle_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = TriggerProgressSensor(coord, chore, entry)

        # Has sensor config override
        assert sensor._attr_name == "Rack Timer"

    def test_duration_no_sensor_config(self):
        config = duration_contact_cycle_config()
        del config["trigger"]["sensor"]
        chore = Chore(config)
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = TriggerProgressSensor(coord, chore, entry)

        assert sensor._attr_name == "Duration Monitor"
        assert sensor._icon_idle == "mdi:timer-off-outline"

    def test_native_value(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = TriggerProgressSensor(coord, chore, entry)

        assert sensor.native_value == SubState.IDLE.value

    def test_icon_per_sub_state(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = TriggerProgressSensor(coord, chore, entry)

        # IDLE
        assert sensor.icon == "mdi:calendar-clock"

        # Force trigger to ACTIVE
        chore.trigger.set_state(SubState.ACTIVE)
        assert sensor.icon == "mdi:calendar-alert"

        # Force trigger to DONE
        chore.trigger.set_state(SubState.DONE)
        assert sensor.icon == "mdi:calendar-check"

    def test_sensor_config_override(self):
        """sensor: block in YAML overrides defaults."""
        chore = Chore(daily_gate_contact_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = TriggerProgressSensor(coord, chore, entry)

        # daily_gate_contact_config has sensor: {name: "Morning Vitamins Schedule"}
        assert sensor._attr_name == "Morning Vitamins Schedule"


# ── CompletionProgressSensor ──────────────────────────────────────────


class TestCompletionProgressSensor:
    def test_contact_defaults(self):
        chore = Chore(daily_gate_contact_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = CompletionProgressSensor(coord, chore, entry)

        assert sensor._attr_unique_id == f"{DOMAIN}_{chore.id}_completion"
        assert sensor._attr_name == "Contact"
        assert sensor._icon_idle == "mdi:door-closed"

    def test_contact_cycle_defaults(self):
        chore = Chore(duration_contact_cycle_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = CompletionProgressSensor(coord, chore, entry)

        assert sensor._attr_name == "Contact Cycle"
        assert sensor._icon_active == "mdi:door-open"
        assert sensor._icon_done == "mdi:door-closed-lock"

    def test_presence_cycle_defaults(self):
        chore = Chore(daily_presence_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = CompletionProgressSensor(coord, chore, entry)

        assert sensor._attr_name == "Presence"
        assert sensor._icon_idle == "mdi:home"
        assert sensor._icon_active == "mdi:home-export-outline"
        assert sensor._icon_done == "mdi:home-import-outline"

    def test_sensor_threshold_defaults(self):
        chore = Chore(daily_sensor_threshold_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = CompletionProgressSensor(coord, chore, entry)

        assert sensor._attr_name == "Sensor Threshold"
        assert sensor._icon_idle == "mdi:gauge-empty"
        assert sensor._icon_active == "mdi:gauge"
        assert sensor._icon_done == "mdi:gauge-full"

    def test_not_created_for_manual(self):
        """Manual completion chores should not have CompletionProgressSensor."""
        chore = Chore(daily_manual_config())
        assert chore.completion.completion_type == CompletionType.MANUAL
        # The async_setup_entry function skips creation for manual;
        # we just verify the type check works.

    def test_native_value(self):
        chore = Chore(daily_gate_contact_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = CompletionProgressSensor(coord, chore, entry)

        assert sensor.native_value == SubState.IDLE.value

    def test_icon_per_sub_state(self):
        chore = Chore(daily_gate_contact_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = CompletionProgressSensor(coord, chore, entry)

        # IDLE
        assert sensor.icon == "mdi:door-closed"

        # ACTIVE
        chore.completion.set_state(SubState.ACTIVE)
        assert sensor.icon == "mdi:door-open"

        # DONE
        chore.completion.set_state(SubState.DONE)
        assert sensor.icon == "mdi:check-circle"


# ── ResetProgressSensor ───────────────────────────────────────────────


class TestResetProgressSensor:
    def test_unique_id_and_name(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = ResetProgressSensor(coord, chore, entry)

        assert sensor._attr_unique_id == f"{DOMAIN}_{chore.id}_reset"
        assert sensor._attr_name == "Reset"

    def test_idle_when_not_completed(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = ResetProgressSensor(coord, chore, entry)

        assert chore.state == ChoreState.INACTIVE
        assert sensor.native_value == "idle"
        assert sensor.icon == "mdi:restart"

    def test_waiting_when_completed(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = ResetProgressSensor(coord, chore, entry)

        # Force to completed
        chore.force_complete()
        assert chore.state == ChoreState.COMPLETED
        assert sensor.native_value == "waiting"
        assert sensor.icon == "mdi:timer-sand"


# ── LastCompletedSensor ───────────────────────────────────────────────


class TestLastCompletedSensor:
    def test_unique_id_and_name(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = LastCompletedSensor(coord, chore, entry)

        assert sensor._attr_unique_id == f"{DOMAIN}_{chore.id}_last_completed"
        assert sensor._attr_name == "Last Completed"

    def test_native_value_none_when_no_completion(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = LastCompletedSensor(coord, chore, entry)

        assert sensor.native_value is None

    def test_native_value_after_completion(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = LastCompletedSensor(coord, chore, entry)

        chore.force_complete()
        assert sensor.native_value is not None

    def test_icon(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = LastCompletedSensor(coord, chore, entry)

        assert sensor.icon == "mdi:history"

    def test_extra_state_attributes(self):
        chore = Chore(daily_manual_config())
        coord = _make_coordinator_mock(chore)
        entry = _make_entry_mock()
        sensor = LastCompletedSensor(coord, chore, entry)

        attrs = sensor.extra_state_attributes
        assert "completed_by" in attrs
        assert "completion_count_today" in attrs
        assert "completion_count_7d" in attrs
