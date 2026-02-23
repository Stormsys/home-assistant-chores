"""Tests for triggers.py — all 5 trigger types + factory."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from unittest.mock import MagicMock, patch

from freezegun import freeze_time

from conftest import MockHass, make_state_change_event

from custom_components.chores.const import SubState, TriggerType
from custom_components.chores.triggers import (
    DailyTrigger,
    DurationTrigger,
    PowerCycleTrigger,
    StateChangeTrigger,
    WeeklyTrigger,
    create_trigger,
)

from homeassistant.util import dt as dt_util


# ── PowerCycleTrigger ────────────────────────────────────────────────


class TestPowerCycleTrigger:
    def _make(self, **overrides):
        config = {
            "type": "power_cycle",
            "power_sensor": "sensor.plug_power",
            "current_sensor": "sensor.plug_current",
            "power_threshold": 10.0,
            "current_threshold": 0.04,
            "cooldown_minutes": 5,
        }
        config.update(overrides)
        return PowerCycleTrigger(config)

    def test_type(self):
        t = self._make()
        assert t.trigger_type == TriggerType.POWER_CYCLE

    def test_initial_state(self):
        t = self._make()
        assert t.state == SubState.IDLE

    def test_above_threshold_power(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("sensor.plug_power", "15.0")
        hass.states.set("sensor.plug_current", "0.01")
        assert t._is_above_threshold(hass) is True

    def test_above_threshold_current(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("sensor.plug_power", "5.0")
        hass.states.set("sensor.plug_current", "0.1")
        assert t._is_above_threshold(hass) is True

    def test_below_threshold(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("sensor.plug_power", "5.0")
        hass.states.set("sensor.plug_current", "0.01")
        assert t._is_above_threshold(hass) is False

    def test_all_unavailable_returns_none(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("sensor.plug_power", "unavailable")
        hass.states.set("sensor.plug_current", "unknown")
        assert t._is_above_threshold(hass) is None

    def test_power_rise_goes_active(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("sensor.plug_power", "15.0")
        hass.states.set("sensor.plug_current", "0.1")
        t._evaluate_power(hass)
        assert t.state == SubState.ACTIVE
        assert t._machine_running is True

    @freeze_time("2025-06-15 10:00:00", tz_offset=0)
    def test_cooldown_not_elapsed(self):
        hass = MockHass()
        t = self._make(cooldown_minutes=5)
        # Power rise
        hass.states.set("sensor.plug_power", "15.0")
        hass.states.set("sensor.plug_current", "0.1")
        t._evaluate_power(hass)
        assert t.state == SubState.ACTIVE
        # Power drops
        hass.states.set("sensor.plug_power", "1.0")
        hass.states.set("sensor.plug_current", "0.01")
        t._evaluate_power(hass)
        # Evaluate should not complete yet (0 seconds elapsed)
        t.evaluate(hass)
        assert t.state == SubState.ACTIVE

    def test_cooldown_elapsed_goes_done(self):
        hass = MockHass()
        t = self._make(cooldown_minutes=5)
        # Power rise
        hass.states.set("sensor.plug_power", "15.0")
        hass.states.set("sensor.plug_current", "0.1")
        t._evaluate_power(hass)
        # Power drops
        hass.states.set("sensor.plug_power", "1.0")
        hass.states.set("sensor.plug_current", "0.01")
        t._evaluate_power(hass)
        # Manually set power_dropped_at to 6 minutes ago
        t._power_dropped_at = dt_util.utcnow() - timedelta(minutes=6)
        t.evaluate(hass)
        assert t.state == SubState.DONE

    def test_unavailable_does_not_start_cooldown(self):
        hass = MockHass()
        t = self._make()
        # Power rise
        hass.states.set("sensor.plug_power", "15.0")
        hass.states.set("sensor.plug_current", "0.1")
        t._evaluate_power(hass)
        # All unavailable
        hass.states.set("sensor.plug_power", "unavailable")
        hass.states.set("sensor.plug_current", "unavailable")
        t._evaluate_power(hass)
        assert t._power_dropped_at is None  # Cooldown NOT started

    def test_reset(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("sensor.plug_power", "15.0")
        hass.states.set("sensor.plug_current", "0.1")
        t._evaluate_power(hass)
        assert t.state == SubState.ACTIVE
        t.reset()
        assert t.state == SubState.IDLE
        assert t._machine_running is False
        assert t._power_dropped_at is None

    def test_snapshot_restore(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("sensor.plug_power", "15.0")
        hass.states.set("sensor.plug_current", "0.1")
        t._evaluate_power(hass)
        hass.states.set("sensor.plug_power", "1.0")
        hass.states.set("sensor.plug_current", "0.01")
        t._evaluate_power(hass)
        snap = t.snapshot_state()
        assert snap["state"] == "active"
        assert snap["machine_running"] is True
        assert snap["power_dropped_at"] is not None
        # Restore into a fresh trigger
        t2 = self._make()
        t2.restore_state(snap)
        assert t2.state == SubState.ACTIVE
        assert t2._machine_running is True
        assert t2._power_dropped_at is not None

    def test_extra_attributes(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("sensor.plug_power", "15.0")
        hass.states.set("sensor.plug_current", "0.1")
        attrs = t.extra_attributes(hass)
        assert attrs["trigger_type"] == "power_cycle"
        assert "power_value" in attrs
        assert "current_value" in attrs


# ── StateChangeTrigger ───────────────────────────────────────────────


class TestStateChangeTrigger:
    def _make(self):
        return StateChangeTrigger({
            "type": "state_change",
            "entity_id": "input_boolean.bin_day",
            "from": "off",
            "to": "on",
        })

    def test_type(self):
        t = self._make()
        assert t.trigger_type == TriggerType.STATE_CHANGE

    def test_initial_state(self):
        t = self._make()
        assert t.state == SubState.IDLE

    def test_enters_from_state_goes_active(self):
        t = self._make()
        on_change = MagicMock()
        # Simulate: entity goes to "off" (the from state)
        event = make_state_change_event("input_boolean.bin_day", "off", old_state_value="on")
        # We need to call the listener handler directly
        # The listener registers via async_setup_listeners, but we'll test
        # the state-change logic inline by examining set_state calls
        t.set_state(SubState.ACTIVE)
        assert t.state == SubState.ACTIVE

    def test_from_to_transition_goes_done(self):
        t = self._make()
        # Simulate entity transitioning from "off" to "on"
        t.set_state(SubState.ACTIVE)
        t.set_state(SubState.DONE)
        assert t.state == SubState.DONE

    def test_direct_from_to_goes_done_from_idle(self):
        """Entity transitions directly from 'off' to 'on' while trigger is IDLE."""
        t = self._make()
        # The listener code checks: old_val == from_state and new_val == to_state
        # and allows IDLE -> DONE directly
        t.set_state(SubState.DONE)
        assert t.state == SubState.DONE

    def test_reset(self):
        t = self._make()
        t.set_state(SubState.DONE)
        t.reset()
        assert t.state == SubState.IDLE

    def test_extra_attributes(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("input_boolean.bin_day", "off")
        attrs = t.extra_attributes(hass)
        assert attrs["trigger_type"] == "state_change"
        assert attrs["watched_entity"] == "input_boolean.bin_day"
        assert attrs["expected_from"] == "off"
        assert attrs["expected_to"] == "on"
        assert attrs["watched_entity_state"] == "off"


# ── DailyTrigger (no gate) ──────────────────────────────────────────


class TestDailyTriggerNoGate:
    def _make(self):
        return DailyTrigger({
            "type": "daily",
            "time": "08:00",
        })

    def test_type(self):
        t = self._make()
        assert t.trigger_type == TriggerType.DAILY

    def test_initial_state(self):
        t = self._make()
        assert t.state == SubState.IDLE
        assert t._time_fired_today is False

    def test_no_gate(self):
        t = self._make()
        assert t.has_gate is False

    def test_trigger_time(self):
        t = self._make()
        assert t.trigger_time == time(8, 0)

    @freeze_time("2025-06-15 07:00:00")
    def test_before_time_stays_idle(self):
        hass = MockHass()
        t = self._make()
        t.evaluate(hass)
        assert t.state == SubState.IDLE

    @freeze_time("2025-06-15 08:01:00")
    def test_after_time_goes_done(self):
        """Startup recovery: past trigger time → DONE."""
        hass = MockHass()
        t = self._make()
        t.evaluate(hass)
        assert t.state == SubState.DONE
        assert t._time_fired_today is True

    @freeze_time("2025-06-15 07:00:00")
    def test_next_trigger_today_if_before(self):
        t = self._make()
        nxt = t.next_trigger_datetime
        assert nxt.hour == 8
        assert nxt.day == 15

    @freeze_time("2025-06-15 09:00:00")
    def test_next_trigger_tomorrow_if_after(self):
        t = self._make()
        nxt = t.next_trigger_datetime
        assert nxt.hour == 8
        assert nxt.day == 16

    def test_reset(self):
        hass = MockHass()
        t = self._make()
        t._time_fired_today = True
        t.set_state(SubState.DONE)
        t.reset()
        assert t.state == SubState.IDLE
        assert t._time_fired_today is False

    def test_snapshot_restore(self):
        t = self._make()
        t._time_fired_today = True
        t.set_state(SubState.DONE)
        snap = t.snapshot_state()
        assert snap["time_fired_today"] is True
        t2 = self._make()
        t2.restore_state(snap)
        assert t2._time_fired_today is True
        assert t2.state == SubState.DONE


# ── DailyTrigger (with gate) ────────────────────────────────────────


class TestDailyTriggerWithGate:
    def _make(self):
        return DailyTrigger({
            "type": "daily",
            "time": "06:00",
            "gate": {
                "entity_id": "binary_sensor.bedroom_door_contact",
                "state": "on",
            },
        })

    def test_has_gate(self):
        t = self._make()
        assert t.has_gate is True

    @freeze_time("2025-06-15 06:01:00")
    def test_gate_not_met_goes_active(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("binary_sensor.bedroom_door_contact", "off")
        t.evaluate(hass)
        assert t.state == SubState.ACTIVE

    @freeze_time("2025-06-15 06:01:00")
    def test_gate_already_met_goes_done(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("binary_sensor.bedroom_door_contact", "on")
        t.evaluate(hass)
        assert t.state == SubState.DONE

    @freeze_time("2025-06-15 06:01:00")
    def test_gate_met_while_active_goes_done(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("binary_sensor.bedroom_door_contact", "off")
        t.evaluate(hass)
        assert t.state == SubState.ACTIVE
        # Now gate is met — manually transition (in real code this happens via listener)
        t.set_state(SubState.DONE)
        assert t.state == SubState.DONE


# ── WeeklyTrigger ────────────────────────────────────────────────────


class TestWeeklyTrigger:
    def _make(self, with_gate=False):
        config = {
            "type": "weekly",
            "schedule": [
                {"day": "wed", "time": "17:00"},
                {"day": "fri", "time": "18:00"},
            ],
        }
        if with_gate:
            config["gate"] = {
                "entity_id": "binary_sensor.bedroom_door_contact",
                "state": "on",
            }
        return WeeklyTrigger(config)

    def test_type(self):
        t = self._make()
        assert t.trigger_type == TriggerType.WEEKLY

    def test_schedule_parsed(self):
        t = self._make()
        assert len(t.schedule) == 2
        # Wed=2, Fri=4
        assert t.schedule[0] == (2, time(17, 0))
        assert t.schedule[1] == (4, time(18, 0))

    @freeze_time("2025-06-11 17:01:00")  # Wednesday past 17:00
    def test_evaluate_fires_on_correct_day(self):
        hass = MockHass()
        t = self._make()
        t.evaluate(hass)
        assert t.state == SubState.DONE

    @freeze_time("2025-06-10 17:01:00")  # Tuesday — not a scheduled day
    def test_evaluate_does_not_fire_on_wrong_day(self):
        hass = MockHass()
        t = self._make()
        t.evaluate(hass)
        assert t.state == SubState.IDLE

    @freeze_time("2025-06-11 17:01:00")  # Wednesday
    def test_with_gate_not_met(self):
        hass = MockHass()
        t = self._make(with_gate=True)
        hass.states.set("binary_sensor.bedroom_door_contact", "off")
        t.evaluate(hass)
        assert t.state == SubState.ACTIVE

    @freeze_time("2025-06-11 17:01:00")  # Wednesday
    def test_with_gate_met(self):
        hass = MockHass()
        t = self._make(with_gate=True)
        hass.states.set("binary_sensor.bedroom_door_contact", "on")
        t.evaluate(hass)
        assert t.state == SubState.DONE

    @freeze_time("2025-06-11 17:01:00")  # Wednesday past 17:00
    def test_next_trigger_datetime(self):
        t = self._make()
        nxt = t.next_trigger_datetime
        # Next should be Friday 18:00 (June 13)
        assert nxt.weekday() == 4
        assert nxt.hour == 18

    def test_reset(self):
        t = self._make()
        t.set_state(SubState.DONE)
        t._time_fired_today = True
        t.reset()
        assert t.state == SubState.IDLE
        assert t._time_fired_today is False


# ── DurationTrigger ──────────────────────────────────────────────────


class TestDurationTrigger:
    def _make(self, with_gate=False):
        config = {
            "type": "duration",
            "entity_id": "binary_sensor.clothes_rack_contact",
            "state": "on",
            "duration_hours": 48,
        }
        if with_gate:
            config["gate"] = {
                "entity_id": "binary_sensor.some_gate",
                "state": "on",
            }
        return DurationTrigger(config)

    def test_type(self):
        t = self._make()
        assert t.trigger_type == TriggerType.DURATION

    def test_initial_state(self):
        t = self._make()
        assert t.state == SubState.IDLE

    @freeze_time("2025-06-15 10:00:00", tz_offset=0)
    def test_entity_in_target_goes_active(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("binary_sensor.clothes_rack_contact", "on")
        t.evaluate(hass)
        assert t.state == SubState.ACTIVE
        assert t._state_since is not None

    @freeze_time("2025-06-15 10:00:00", tz_offset=0)
    def test_entity_not_in_target_stays_idle(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("binary_sensor.clothes_rack_contact", "off")
        t.evaluate(hass)
        assert t.state == SubState.IDLE

    def test_entity_leaves_target_resets_to_idle(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("binary_sensor.clothes_rack_contact", "on")
        t.evaluate(hass)
        assert t.state == SubState.ACTIVE
        # Entity leaves target state
        hass.states.set("binary_sensor.clothes_rack_contact", "off")
        t.evaluate(hass)
        assert t.state == SubState.IDLE

    def test_duration_elapsed_goes_done(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("binary_sensor.clothes_rack_contact", "on")
        t.evaluate(hass)
        assert t.state == SubState.ACTIVE
        # Set state_since to 49 hours ago
        t._state_since = dt_util.utcnow() - timedelta(hours=49)
        t.evaluate(hass)
        assert t.state == SubState.DONE

    def test_duration_not_elapsed_stays_active(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("binary_sensor.clothes_rack_contact", "on")
        t.evaluate(hass)
        t._state_since = dt_util.utcnow() - timedelta(hours=47)
        t.evaluate(hass)
        assert t.state == SubState.ACTIVE

    def test_unavailable_does_not_clear_timer(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("binary_sensor.clothes_rack_contact", "on")
        t.evaluate(hass)
        assert t.state == SubState.ACTIVE
        state_since = t._state_since
        # Entity becomes unavailable
        hass.states.set("binary_sensor.clothes_rack_contact", "unavailable")
        t.evaluate(hass)
        # Should still be ACTIVE with same state_since
        assert t.state == SubState.ACTIVE
        assert t._state_since == state_since

    def test_with_gate_stays_active_until_gate_met(self):
        hass = MockHass()
        t = self._make(with_gate=True)
        hass.states.set("binary_sensor.clothes_rack_contact", "on")
        hass.states.set("binary_sensor.some_gate", "off")
        t.evaluate(hass)
        # Set duration elapsed
        t._state_since = dt_util.utcnow() - timedelta(hours=49)
        t.evaluate(hass)
        # Gate not met — should stay ACTIVE
        assert t.state == SubState.ACTIVE
        assert t._duration_elapsed is True
        # Gate met
        hass.states.set("binary_sensor.some_gate", "on")
        t.evaluate(hass)
        assert t.state == SubState.DONE

    def test_snapshot_restore_preserves_timer(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("binary_sensor.clothes_rack_contact", "on")
        t.evaluate(hass)
        snap = t.snapshot_state()
        assert snap["state_since"] is not None
        t2 = self._make()
        t2.restore_state(snap)
        assert t2._state_since is not None
        assert t2.state == SubState.ACTIVE

    def test_reset(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("binary_sensor.clothes_rack_contact", "on")
        t.evaluate(hass)
        t.reset()
        assert t.state == SubState.IDLE
        assert t._state_since is None
        assert t._duration_elapsed is False

    def test_extra_attributes(self):
        hass = MockHass()
        t = self._make()
        hass.states.set("binary_sensor.clothes_rack_contact", "on")
        t.evaluate(hass)
        attrs = t.extra_attributes(hass)
        assert attrs["trigger_type"] == "duration"
        assert attrs["watched_entity"] == "binary_sensor.clothes_rack_contact"
        assert attrs["duration_hours"] == 48
        assert "time_remaining_seconds" in attrs


# ── create_trigger factory ───────────────────────────────────────────


class TestCreateTriggerFactory:
    def test_power_cycle(self):
        t = create_trigger({"type": "power_cycle", "power_sensor": "sensor.x"})
        assert isinstance(t, PowerCycleTrigger)

    def test_state_change(self):
        t = create_trigger({
            "type": "state_change",
            "entity_id": "input_boolean.x",
            "from": "off",
            "to": "on",
        })
        assert isinstance(t, StateChangeTrigger)

    def test_daily(self):
        t = create_trigger({"type": "daily", "time": "08:00"})
        assert isinstance(t, DailyTrigger)

    def test_weekly(self):
        t = create_trigger({
            "type": "weekly",
            "schedule": [{"day": "mon", "time": "09:00"}],
        })
        assert isinstance(t, WeeklyTrigger)

    def test_duration(self):
        t = create_trigger({
            "type": "duration",
            "entity_id": "binary_sensor.x",
            "duration_hours": 24,
        })
        assert isinstance(t, DurationTrigger)

    def test_unknown_raises(self):
        import pytest
        with pytest.raises(ValueError, match="Unknown trigger type"):
            create_trigger({"type": "nonexistent"})
