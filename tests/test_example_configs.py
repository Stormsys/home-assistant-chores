"""Full lifecycle integration tests for all 9 example configurations.

Each test creates a Chore from the exact example config and simulates the
complete lifecycle: INACTIVE → trigger → DUE → completion → COMPLETED → reset → INACTIVE.
These tests provide the most meaningful signal that the integration is working.
"""
from __future__ import annotations

from datetime import timedelta

from freezegun import freeze_time

from conftest import (
    MockHass,
    daily_gate_contact_config,
    daily_gate_manual_config,
    daily_manual_config,
    daily_presence_afternoon_config,
    daily_presence_config,
    daily_sensor_threshold_config,
    duration_contact_cycle_config,
    power_cycle_config,
    setup_listeners_capturing,
    state_change_presence_config,
    weekly_gate_manual_config,
)

from custom_components.chores.chore_core import Chore
from custom_components.chores.const import ChoreState, SubState

from homeassistant.util import dt as dt_util


class TestUnloadWashingLifecycle:
    """power_cycle trigger + contact completion + implicit_event reset."""

    def test_full_lifecycle(self):
        hass = MockHass()
        chore = Chore(power_cycle_config())
        assert chore.state == ChoreState.INACTIVE

        # 1. Power goes above threshold → trigger ACTIVE → chore PENDING
        hass.states.set("sensor.washing_machine_plug_power", "50.0")
        hass.states.set("sensor.washing_machine_plug_current", "0.5")
        chore.trigger.detector._evaluate_power(hass)
        chore.evaluate(hass)
        assert chore.trigger.state == SubState.ACTIVE
        assert chore.state == ChoreState.PENDING

        # 2. Power drops below threshold, cooldown elapses → trigger DONE → chore DUE
        hass.states.set("sensor.washing_machine_plug_power", "1.0")
        hass.states.set("sensor.washing_machine_plug_current", "0.01")
        chore.trigger.detector._evaluate_power(hass)
        # Simulate cooldown elapsed
        chore.trigger.detector._power_dropped_at = dt_util.utcnow() - timedelta(minutes=6)
        chore.evaluate(hass)
        assert chore.trigger.state == SubState.DONE
        assert chore.state == ChoreState.DUE
        assert chore.due_since is not None
        assert chore.completion.enabled is True

        # 3. Door contact opens → completion DONE → chore COMPLETED
        chore.completion.set_state(SubState.DONE)
        chore.evaluate(hass)
        assert chore.state == ChoreState.COMPLETED
        assert chore.last_completed is not None

        # 4. ImplicitEventReset → immediately INACTIVE
        chore.evaluate(hass)
        assert chore.state == ChoreState.INACTIVE
        assert chore.due_since is None


class TestTakeVitaminsLifecycle:
    """daily trigger + gate + contact completion + implicit_daily reset."""

    @freeze_time("2025-06-15 06:01:00")
    def test_full_lifecycle(self):
        hass = MockHass()
        chore = Chore(daily_gate_contact_config())
        assert chore.state == ChoreState.INACTIVE

        # 1. Trigger time reached, gate NOT met → PENDING
        hass.states.set("binary_sensor.bedroom_door_contact", "off")
        chore.evaluate(hass)
        assert chore.trigger.state == SubState.ACTIVE
        assert chore.state == ChoreState.PENDING

        # 2. Gate entity changes to "on" → trigger DONE → chore DUE
        chore.trigger.set_state(SubState.DONE)
        chore.evaluate(hass)
        assert chore.state == ChoreState.DUE
        assert chore.completion.enabled is True

        # 3. Coffee cupboard door opens → COMPLETED
        chore.completion.set_state(SubState.DONE)
        chore.evaluate(hass)
        assert chore.state == ChoreState.COMPLETED

        # 4. ImplicitDailyReset — should NOT reset yet (same day)
        chore.evaluate(hass)
        assert chore.state == ChoreState.COMPLETED

    @freeze_time("2025-06-15 06:01:00")
    def test_gate_already_met(self):
        hass = MockHass()
        chore = Chore(daily_gate_contact_config())
        hass.states.set("binary_sensor.bedroom_door_contact", "on")
        chore.evaluate(hass)
        # Gate already met → should go directly to DUE
        assert chore.trigger.state == SubState.DONE
        assert chore.state == ChoreState.DUE


class TestFeedFayMorningLifecycle:
    """daily trigger + manual completion + implicit_daily reset."""

    @freeze_time("2025-06-15 08:01:00")
    def test_full_lifecycle(self):
        hass = MockHass()
        chore = Chore(daily_manual_config())
        assert chore.state == ChoreState.INACTIVE

        # 1. Trigger time reached (no gate) → DONE immediately → chore DUE
        chore.evaluate(hass)
        assert chore.state == ChoreState.DUE

        # 2. Manual completion via force_complete
        old = chore.force_complete()
        assert chore.state == ChoreState.COMPLETED
        assert old == ChoreState.DUE

        # 3. ImplicitDailyReset — stays COMPLETED until next trigger time
        chore.evaluate(hass)
        assert chore.state == ChoreState.COMPLETED


class TestFeedFayEveningLifecycle:
    """daily trigger + gate + manual completion + implicit_daily reset."""

    @freeze_time("2025-06-15 18:01:00")
    def test_full_lifecycle(self):
        hass = MockHass()
        chore = Chore(daily_gate_manual_config())
        assert chore.state == ChoreState.INACTIVE

        # 1. Trigger time, gate NOT met → PENDING
        hass.states.set("binary_sensor.some_activity_sensor", "off")
        chore.evaluate(hass)
        assert chore.state == ChoreState.PENDING

        # 2. Gate met → DUE
        chore.trigger.set_state(SubState.DONE)
        chore.evaluate(hass)
        assert chore.state == ChoreState.DUE

        # 3. Force complete → COMPLETED
        chore.force_complete()
        assert chore.state == ChoreState.COMPLETED


class TestWalkFayMorningLifecycle:
    """daily trigger + presence_cycle (binary_sensor) + implicit_daily reset."""

    @freeze_time("2025-06-15 06:01:00")
    def test_full_lifecycle(self):
        hass = MockHass()
        chore = Chore(daily_presence_config())
        assert chore.state == ChoreState.INACTIVE

        # 1. Trigger time → DUE
        chore.evaluate(hass)
        assert chore.state == ChoreState.DUE

        # 2. Person leaves (binary_sensor off) → STARTED
        chore.completion.set_state(SubState.ACTIVE)
        chore.evaluate(hass)
        assert chore.state == ChoreState.STARTED

        # 3. Person returns (binary_sensor on) → COMPLETED
        chore.completion.set_state(SubState.DONE)
        chore.evaluate(hass)
        assert chore.state == ChoreState.COMPLETED

        # 4. Stays COMPLETED (implicit daily reset waits for next trigger time)
        chore.evaluate(hass)
        assert chore.state == ChoreState.COMPLETED

    @freeze_time("2025-06-15 06:01:00")
    def test_presence_cycle_uses_binary_sensor_states(self):
        """Binary sensor entity should use off/on states."""
        chore = Chore(daily_presence_config())
        assert chore.completion.detector._away_state == "off"
        assert chore.completion.detector._home_state == "on"


class TestWalkFayAfternoonLifecycle:
    """Same pattern as morning walk."""

    @freeze_time("2025-06-15 17:31:00")
    def test_full_lifecycle(self):
        hass = MockHass()
        chore = Chore(daily_presence_afternoon_config())
        assert chore.state == ChoreState.INACTIVE

        chore.evaluate(hass)
        assert chore.state == ChoreState.DUE

        chore.completion.set_state(SubState.ACTIVE)
        chore.evaluate(hass)
        assert chore.state == ChoreState.STARTED

        chore.completion.set_state(SubState.DONE)
        chore.evaluate(hass)
        assert chore.state == ChoreState.COMPLETED


class TestWeeklyCleanLifecycle:
    """weekly trigger + gate + manual completion + implicit_weekly reset."""

    @freeze_time("2025-06-11 17:01:00")  # Wednesday
    def test_full_lifecycle(self):
        hass = MockHass()
        chore = Chore(weekly_gate_manual_config())
        assert chore.state == ChoreState.INACTIVE

        # 1. Wednesday 17:01, gate NOT met → PENDING
        hass.states.set("binary_sensor.bedroom_door_contact", "off")
        chore.evaluate(hass)
        assert chore.state == ChoreState.PENDING

        # 2. Gate met → DUE
        chore.trigger.set_state(SubState.DONE)
        chore.evaluate(hass)
        assert chore.state == ChoreState.DUE

        # 3. Force complete → COMPLETED
        chore.force_complete()
        assert chore.state == ChoreState.COMPLETED

        # 4. Stays COMPLETED (weekly reset waits for next schedule entry)
        chore.evaluate(hass)
        assert chore.state == ChoreState.COMPLETED

    @freeze_time("2025-06-11 17:01:00")  # Wednesday
    def test_gate_already_met(self):
        hass = MockHass()
        chore = Chore(weekly_gate_manual_config())
        hass.states.set("binary_sensor.bedroom_door_contact", "on")
        chore.evaluate(hass)
        assert chore.state == ChoreState.DUE

    @freeze_time("2025-06-10 17:01:00")  # Tuesday — not a scheduled day
    def test_wrong_day_stays_inactive(self):
        hass = MockHass()
        chore = Chore(weekly_gate_manual_config())
        hass.states.set("binary_sensor.bedroom_door_contact", "on")
        chore.evaluate(hass)
        assert chore.state == ChoreState.INACTIVE


class TestCollectClothesRackLifecycle:
    """duration trigger + contact_cycle completion + implicit_event reset."""

    def test_full_lifecycle(self):
        hass = MockHass()
        chore = Chore(duration_contact_cycle_config())
        assert chore.state == ChoreState.INACTIVE

        # 1. Entity enters target state → trigger ACTIVE → chore PENDING
        hass.states.set("binary_sensor.clothes_rack_contact", "on")
        chore.evaluate(hass)
        assert chore.trigger.state == SubState.ACTIVE
        assert chore.state == ChoreState.PENDING

        # 2. Duration elapses (48h) → trigger DONE → chore DUE
        chore.trigger.detector._state_since = dt_util.utcnow() - timedelta(hours=49)
        chore.evaluate(hass)
        assert chore.trigger.state == SubState.DONE
        assert chore.state == ChoreState.DUE

        # 3. Contact cycle step 1: opens → STARTED
        chore.completion.set_state(SubState.ACTIVE)
        chore.evaluate(hass)
        assert chore.state == ChoreState.STARTED

        # 4. Contact cycle step 2: closes → COMPLETED
        chore.completion.set_state(SubState.DONE)
        chore.evaluate(hass)
        assert chore.state == ChoreState.COMPLETED

        # 5. ImplicitEventReset → immediately INACTIVE
        chore.evaluate(hass)
        assert chore.state == ChoreState.INACTIVE

    def test_duration_not_elapsed_stays_pending(self):
        hass = MockHass()
        chore = Chore(duration_contact_cycle_config())
        hass.states.set("binary_sensor.clothes_rack_contact", "on")
        chore.evaluate(hass)
        # Only 10 hours elapsed
        chore.trigger.detector._state_since = dt_util.utcnow() - timedelta(hours=10)
        chore.evaluate(hass)
        assert chore.trigger.state == SubState.ACTIVE
        assert chore.state == ChoreState.PENDING


class TestTakeBinsOutLifecycle:
    """state_change trigger + presence_cycle (person) + implicit_event reset."""

    def test_full_lifecycle(self):
        hass = MockHass()
        chore = Chore(state_change_presence_config())
        assert chore.state == ChoreState.INACTIVE

        # 1. input_boolean transitions off→on → trigger DONE → chore DUE
        chore.trigger.set_state(SubState.DONE)
        chore.evaluate(hass)
        assert chore.state == ChoreState.DUE

        # 2. Person leaves (not_home) → completion ACTIVE → chore STARTED
        chore.completion.set_state(SubState.ACTIVE)
        chore.evaluate(hass)
        assert chore.state == ChoreState.STARTED

        # 3. Person returns (home) → completion DONE → chore COMPLETED
        chore.completion.set_state(SubState.DONE)
        chore.evaluate(hass)
        assert chore.state == ChoreState.COMPLETED

        # 4. ImplicitEventReset → immediately INACTIVE
        chore.evaluate(hass)
        assert chore.state == ChoreState.INACTIVE

    def test_presence_cycle_uses_person_states(self):
        """person.* entity should use not_home/home states."""
        chore = Chore(state_change_presence_config())
        assert chore.completion.detector._away_state == "not_home"
        assert chore.completion.detector._home_state == "home"


class TestOpenWindowHumidityLifecycle:
    """daily trigger + sensor_threshold completion + implicit_daily reset."""

    @freeze_time("2025-06-15 08:01:00")
    def test_full_lifecycle(self):
        hass = MockHass()
        chore = Chore(daily_sensor_threshold_config())
        assert chore.state == ChoreState.INACTIVE

        # 1. Trigger time reached → DUE
        chore.evaluate(hass)
        assert chore.state == ChoreState.DUE

        # 2. Humidity drops below 60 → completion DONE → COMPLETED
        chore.completion.set_state(SubState.DONE)
        chore.evaluate(hass)
        assert chore.state == ChoreState.COMPLETED

        # 3. ImplicitDailyReset — stays COMPLETED (same day)
        chore.evaluate(hass)
        assert chore.state == ChoreState.COMPLETED

    @freeze_time("2025-06-15 08:01:00")
    def test_humidity_not_met_stays_due(self):
        hass = MockHass()
        chore = Chore(daily_sensor_threshold_config())
        chore.evaluate(hass)
        assert chore.state == ChoreState.DUE
        # Humidity still above 60 — stays DUE
        chore.evaluate(hass)
        assert chore.state == ChoreState.DUE

    @freeze_time("2025-06-15 08:01:00")
    def test_preexisting_value_completes_on_enable(self):
        """Sensor already below threshold when chore becomes due."""
        hass = MockHass()
        chore = Chore(daily_sensor_threshold_config())
        # Set up listeners (patched) so the completion has access to hass
        setup_listeners_capturing(hass, chore.completion)
        hass.states.set("sensor.bathroom_humidity", "50.0")
        # Trigger fires → DUE → enable() checks and completes
        chore.evaluate(hass)
        assert chore.state == ChoreState.DUE
        # The enable() should have set completion to DONE
        assert chore.completion.state == SubState.DONE
        # Next evaluate picks it up
        chore.evaluate(hass)
        assert chore.state == ChoreState.COMPLETED


# ── Cross-cutting lifecycle tests ────────────────────────────────────


class TestPersistenceRoundTrip:
    """Test snapshot/restore mid-lifecycle across chore configs."""

    @freeze_time("2025-06-15 08:01:00")
    def test_snapshot_restore_preserves_due_state(self):
        hass = MockHass()
        chore = Chore(daily_manual_config())
        chore.evaluate(hass)  # → DUE
        assert chore.state == ChoreState.DUE

        snap = chore.snapshot_state()
        chore2 = Chore(daily_manual_config())
        chore2.restore_state(snap)
        assert chore2.state == ChoreState.DUE
        assert chore2.due_since is not None

    def test_snapshot_restore_preserves_trigger_state(self):
        hass = MockHass()
        chore = Chore(duration_contact_cycle_config())
        hass.states.set("binary_sensor.clothes_rack_contact", "on")
        chore.evaluate(hass)

        snap = chore.snapshot_state()
        chore2 = Chore(duration_contact_cycle_config())
        chore2.restore_state(snap)
        assert chore2.trigger.state == SubState.ACTIVE
        assert chore2.trigger.detector._state_since is not None


class TestForceActionsInterruptLifecycle:
    @freeze_time("2025-06-15 08:01:00")
    def test_force_inactive_from_due(self):
        hass = MockHass()
        chore = Chore(daily_manual_config())
        chore.evaluate(hass)  # → DUE
        chore.force_inactive()
        assert chore.state == ChoreState.INACTIVE
        assert chore.trigger.state == SubState.IDLE

    def test_force_due_from_inactive(self):
        chore = Chore(daily_manual_config())
        chore.force_due()
        assert chore.state == ChoreState.DUE
        assert chore.trigger.state == SubState.DONE
        assert chore.completion.enabled is True


class TestCompletionEnableDisable:
    @freeze_time("2025-06-15 08:01:00")
    def test_completion_only_enabled_when_due(self):
        hass = MockHass()
        chore = Chore(daily_manual_config())
        assert chore.completion.enabled is False
        chore.evaluate(hass)  # → DUE
        assert chore.completion.enabled is True
        chore.force_complete()  # → COMPLETED
        assert chore.completion.enabled is False
