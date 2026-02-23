"""Tests for resets.py — all 5 reset types + factory."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from freezegun import freeze_time

from custom_components.chores.const import ResetType, TriggerType
from custom_components.chores.resets import (
    DailyReset,
    DelayReset,
    ImplicitDailyReset,
    ImplicitEventReset,
    ImplicitWeeklyReset,
    create_reset,
)

from homeassistant.util import dt as dt_util


# ── DelayReset ───────────────────────────────────────────────────────


class TestDelayReset:
    def test_type(self):
        r = DelayReset(minutes=0)
        assert r.reset_type == ResetType.DELAY

    def test_immediate_reset(self):
        r = DelayReset(minutes=0)
        assert r.should_reset(dt_util.utcnow()) is True

    def test_immediate_next_reset_at_is_none(self):
        r = DelayReset(minutes=0)
        assert r.next_reset_at(dt_util.utcnow()) is None

    @freeze_time("2025-06-15 10:00:00", tz_offset=0)
    def test_delay_not_elapsed(self):
        r = DelayReset(minutes=30)
        completed_at = dt_util.utcnow()
        assert r.should_reset(completed_at) is False

    @freeze_time("2025-06-15 10:30:01", tz_offset=0)
    def test_delay_elapsed(self):
        r = DelayReset(minutes=30)
        completed_at = dt_util.utcnow() - timedelta(minutes=31)
        assert r.should_reset(completed_at) is True

    @freeze_time("2025-06-15 10:00:00", tz_offset=0)
    def test_next_reset_at(self):
        r = DelayReset(minutes=60)
        completed_at = dt_util.utcnow()
        expected = completed_at + timedelta(minutes=60)
        assert r.next_reset_at(completed_at) == expected

    def test_extra_attributes(self):
        r = DelayReset(minutes=15)
        attrs = r.extra_attributes(None)
        assert attrs["reset_type"] == "delay"
        assert attrs["delay_minutes"] == 15


# ── DailyReset ───────────────────────────────────────────────────────


class TestDailyReset:
    def test_type(self):
        r = DailyReset(reset_time=time(5, 0))
        assert r.reset_type == ResetType.DAILY_RESET

    @freeze_time("2025-06-15 04:59:00")
    def test_before_reset_time_no_reset(self):
        r = DailyReset(reset_time=time(5, 0))
        # Completed at 04:00 today — reset at 05:00 today hasn't happened yet
        completed_at = dt_util.now().replace(hour=4, minute=0, second=0) - timedelta(hours=1)
        assert r.should_reset(completed_at) is False

    @freeze_time("2025-06-15 05:01:00")
    def test_after_reset_time_resets(self):
        r = DailyReset(reset_time=time(5, 0))
        # Completed at 04:00 today — reset at 05:00 already passed
        completed_at = dt_util.now().replace(hour=4, minute=0, second=0, microsecond=0)
        assert r.should_reset(completed_at) is True

    @freeze_time("2025-06-15 10:00:00")
    def test_next_reset_wraps_to_tomorrow(self):
        r = DailyReset(reset_time=time(5, 0))
        completed_at = dt_util.now()
        next_reset = r.next_reset_at(completed_at)
        assert next_reset is not None
        # Should be 05:00 tomorrow since we're at 10:00
        assert next_reset.hour == 5
        assert next_reset.day == 16

    def test_extra_attributes(self):
        r = DailyReset(reset_time=time(5, 30))
        attrs = r.extra_attributes(None)
        assert attrs["reset_type"] == "daily_reset"
        assert attrs["reset_time"] == "05:30:00"


# ── ImplicitDailyReset ───────────────────────────────────────────────


class TestImplicitDailyReset:
    def test_type(self):
        r = ImplicitDailyReset(trigger_time=time(8, 0))
        assert r.reset_type == ResetType.IMPLICIT_DAILY

    @freeze_time("2025-06-15 07:59:00")
    def test_before_trigger_time_no_reset(self):
        r = ImplicitDailyReset(trigger_time=time(8, 0))
        completed_at = dt_util.now().replace(hour=7, minute=0, second=0, microsecond=0)
        assert r.should_reset(completed_at) is False

    @freeze_time("2025-06-15 08:01:00")
    def test_after_trigger_time_resets(self):
        r = ImplicitDailyReset(trigger_time=time(8, 0))
        completed_at = dt_util.now().replace(hour=7, minute=0, second=0, microsecond=0)
        assert r.should_reset(completed_at) is True

    @freeze_time("2025-06-15 12:00:00")
    def test_next_scheduled_reset(self):
        r = ImplicitDailyReset(trigger_time=time(8, 0))
        nsr = r.next_scheduled_reset()
        assert nsr is not None
        # Should be 08:00 tomorrow
        assert nsr.hour == 8
        assert nsr.day == 16

    def test_extra_attributes(self):
        r = ImplicitDailyReset(trigger_time=time(6, 0))
        attrs = r.extra_attributes(None)
        assert attrs["reset_type"] == "implicit_daily"
        assert attrs["trigger_time"] == "06:00:00"


# ── ImplicitWeeklyReset ──────────────────────────────────────────────


class TestImplicitWeeklyReset:
    def test_type(self):
        # Wed=2, Fri=4
        r = ImplicitWeeklyReset(schedule=[(2, time(17, 0)), (4, time(18, 0))])
        assert r.reset_type == ResetType.IMPLICIT_WEEKLY

    @freeze_time("2025-06-11 16:00:00")  # Wednesday
    def test_before_scheduled_time_no_reset(self):
        r = ImplicitWeeklyReset(schedule=[(2, time(17, 0))])
        completed_at = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
        assert r.should_reset(completed_at) is False

    @freeze_time("2025-06-11 17:01:00")  # Wednesday past 17:00
    def test_after_scheduled_time_resets(self):
        r = ImplicitWeeklyReset(schedule=[(2, time(17, 0))])
        completed_at = dt_util.now().replace(hour=12, minute=0, second=0, microsecond=0)
        assert r.should_reset(completed_at) is True

    @freeze_time("2025-06-11 17:01:00")  # Wednesday
    def test_next_scheduled_reset_picks_nearest(self):
        r = ImplicitWeeklyReset(schedule=[(2, time(17, 0)), (4, time(18, 0))])
        nsr = r.next_scheduled_reset()
        assert nsr is not None
        # Next should be Friday 18:00 (day 13)
        assert nsr.weekday() == 4
        assert nsr.hour == 18

    def test_extra_attributes(self):
        r = ImplicitWeeklyReset(schedule=[(2, time(17, 0)), (4, time(18, 0))])
        attrs = r.extra_attributes(None)
        assert attrs["reset_type"] == "implicit_weekly"
        assert attrs["schedule_entries"] == 2


# ── ImplicitEventReset ───────────────────────────────────────────────


class TestImplicitEventReset:
    def test_type(self):
        r = ImplicitEventReset()
        assert r.reset_type == ResetType.IMPLICIT_EVENT

    def test_always_resets(self):
        r = ImplicitEventReset()
        assert r.should_reset(dt_util.utcnow()) is True
        assert r.should_reset(dt_util.utcnow() - timedelta(days=100)) is True


# ── create_reset factory ─────────────────────────────────────────────


class TestCreateResetFactory:
    def test_explicit_delay(self):
        r = create_reset(
            {"type": "delay", "minutes": 30},
            TriggerType.DAILY,
            {"type": "daily", "time": "08:00"},
        )
        assert isinstance(r, DelayReset)

    def test_explicit_daily_reset(self):
        r = create_reset(
            {"type": "daily_reset", "time": "05:00"},
            TriggerType.DAILY,
            {"type": "daily", "time": "08:00"},
        )
        assert isinstance(r, DailyReset)

    def test_default_for_daily_trigger(self):
        r = create_reset(
            None,
            TriggerType.DAILY,
            {"type": "daily", "time": "08:00"},
        )
        assert isinstance(r, ImplicitDailyReset)

    def test_default_for_weekly_trigger(self):
        r = create_reset(
            None,
            TriggerType.WEEKLY,
            {
                "type": "weekly",
                "schedule": [{"day": "wed", "time": "17:00"}],
            },
        )
        assert isinstance(r, ImplicitWeeklyReset)

    def test_default_for_power_cycle_trigger(self):
        r = create_reset(
            None,
            TriggerType.POWER_CYCLE,
            {"type": "power_cycle"},
        )
        assert isinstance(r, ImplicitEventReset)

    def test_default_for_state_change_trigger(self):
        r = create_reset(
            None,
            TriggerType.STATE_CHANGE,
            {"type": "state_change", "entity_id": "input_boolean.x", "from": "off", "to": "on"},
        )
        assert isinstance(r, ImplicitEventReset)

    def test_default_for_duration_trigger(self):
        r = create_reset(
            None,
            TriggerType.DURATION,
            {"type": "duration", "entity_id": "binary_sensor.x", "duration_hours": 48},
        )
        assert isinstance(r, ImplicitEventReset)
