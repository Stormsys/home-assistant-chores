"""Tests for listener lifecycle — setup, fire, teardown.

Verifies that triggers and completions correctly register listeners via
async_setup_listeners(), that those listeners fire and drive state changes,
and that async_remove_listeners() properly cleans up.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from conftest import MockHass, make_state_change_event, setup_listeners_capturing

from custom_components.chores.const import SubState
from custom_components.chores.triggers import (
    DailyTrigger,
    DurationTrigger,
    PowerCycleTrigger,
    StateChangeTrigger,
)
from custom_components.chores.completions import (
    ContactCompletion,
    ContactCycleCompletion,
    PresenceCycleCompletion,
    SensorStateCompletion,
)


# ── Trigger listener lifecycle ────────────────────────────────────────


class TestPowerCycleListenerLifecycle:
    def test_setup_registers_listener(self):
        config = {
            "type": "power_cycle",
            "power_sensor": "sensor.plug_power",
            "cooldown_minutes": 1,
        }
        trigger = PowerCycleTrigger(config)
        hass = MockHass()
        state_cbs, time_cbs, _ = setup_listeners_capturing(hass, trigger)
        assert len(state_cbs) == 1

    def test_remove_listeners_clears_list_and_calls_unsubs(self):
        config = {
            "type": "power_cycle",
            "power_sensor": "sensor.plug_power",
            "cooldown_minutes": 1,
        }
        trigger = PowerCycleTrigger(config)
        hass = MockHass()
        setup_listeners_capturing(hass, trigger)
        assert len(trigger._listeners) == 1
        unsub = trigger._listeners[0]
        trigger.async_remove_listeners()
        assert len(trigger._listeners) == 0
        unsub.assert_called_once()

    def test_setup_no_sensors_no_listeners(self):
        config = {"type": "power_cycle", "cooldown_minutes": 1}
        trigger = PowerCycleTrigger(config)
        hass = MockHass()
        state_cbs, time_cbs, _ = setup_listeners_capturing(hass, trigger)
        assert len(state_cbs) == 0
        assert len(time_cbs) == 0

    def test_setup_both_sensors_one_listener(self):
        config = {
            "type": "power_cycle",
            "power_sensor": "sensor.power",
            "current_sensor": "sensor.current",
            "cooldown_minutes": 1,
        }
        trigger = PowerCycleTrigger(config)
        hass = MockHass()
        state_cbs, _, _ = setup_listeners_capturing(hass, trigger)
        # Both tracked via a single async_track_state_change_event call
        assert len(state_cbs) == 1


class TestStateChangeListenerLifecycle:
    def test_registers_one_state_listener(self):
        config = {
            "type": "state_change",
            "entity_id": "input_boolean.test",
            "from": "off",
            "to": "on",
        }
        trigger = StateChangeTrigger(config)
        hass = MockHass()
        state_cbs, _, _ = setup_listeners_capturing(hass, trigger)
        assert len(state_cbs) == 1

    def test_remove_listeners(self):
        config = {
            "type": "state_change",
            "entity_id": "input_boolean.test",
            "from": "off",
            "to": "on",
        }
        trigger = StateChangeTrigger(config)
        hass = MockHass()
        setup_listeners_capturing(hass, trigger)
        trigger.async_remove_listeners()
        assert len(trigger._listeners) == 0

    def test_listener_fires_on_from_to_transition(self):
        config = {
            "type": "state_change",
            "entity_id": "input_boolean.test",
            "from": "off",
            "to": "on",
        }
        trigger = StateChangeTrigger(config)
        hass = MockHass()
        state_cbs, _, on_change = setup_listeners_capturing(hass, trigger)
        cb = state_cbs[0]

        event = make_state_change_event("input_boolean.test", "on", "off")
        cb(event)
        assert trigger.state == SubState.DONE
        on_change.assert_called_once()


class TestDailyTriggerListenerLifecycle:
    def test_no_gate_registers_one_time_listener(self):
        config = {"type": "daily", "time": "08:00"}
        trigger = DailyTrigger(config)
        hass = MockHass()
        state_cbs, time_cbs, _ = setup_listeners_capturing(hass, trigger)
        assert len(time_cbs) == 1
        assert len(state_cbs) == 0

    def test_with_gate_registers_time_plus_state_listener(self):
        config = {
            "type": "daily",
            "time": "08:00",
            "gate": {"entity_id": "binary_sensor.door", "state": "on"},
        }
        trigger = DailyTrigger(config)
        hass = MockHass()
        state_cbs, time_cbs, _ = setup_listeners_capturing(hass, trigger)
        assert len(time_cbs) == 1  # time listener
        assert len(state_cbs) == 1  # gate listener

    def test_remove_listeners_calls_all_unsubs(self):
        config = {
            "type": "daily",
            "time": "08:00",
            "gate": {"entity_id": "binary_sensor.door", "state": "on"},
        }
        trigger = DailyTrigger(config)
        hass = MockHass()
        setup_listeners_capturing(hass, trigger)
        unsubs = list(trigger._listeners)
        assert len(unsubs) == 2
        trigger.async_remove_listeners()
        for unsub in unsubs:
            unsub.assert_called_once()

    def test_time_listener_fires_done_no_gate(self):
        from datetime import datetime
        config = {"type": "daily", "time": "08:00"}
        trigger = DailyTrigger(config)
        hass = MockHass()
        _, time_cbs, on_change = setup_listeners_capturing(hass, trigger)
        time_cb = time_cbs[0]

        # Simulate time firing
        time_cb(datetime(2025, 1, 15, 8, 0, 0))
        assert trigger.state == SubState.DONE
        on_change.assert_called_once()

    def test_time_listener_with_gate_goes_active(self):
        from datetime import datetime
        config = {
            "type": "daily",
            "time": "08:00",
            "gate": {"entity_id": "binary_sensor.door", "state": "on"},
        }
        trigger = DailyTrigger(config)
        hass = MockHass()
        hass.states.set("binary_sensor.door", "off")  # gate not met
        _, time_cbs, on_change = setup_listeners_capturing(hass, trigger)
        time_cb = time_cbs[0]

        time_cb(datetime(2025, 1, 15, 8, 0, 0))
        assert trigger.state == SubState.ACTIVE  # pending, gate not met
        on_change.assert_called_once()

    def test_gate_listener_fires_done(self):
        from datetime import datetime
        config = {
            "type": "daily",
            "time": "08:00",
            "gate": {"entity_id": "binary_sensor.door", "state": "on"},
        }
        trigger = DailyTrigger(config)
        hass = MockHass()
        hass.states.set("binary_sensor.door", "off")
        state_cbs, time_cbs, on_change = setup_listeners_capturing(hass, trigger)
        time_cb = time_cbs[0]
        gate_cb = state_cbs[0]

        # Time fires → ACTIVE
        time_cb(datetime(2025, 1, 15, 8, 0, 0))
        assert trigger.state == SubState.ACTIVE

        # Gate met → DONE
        event = make_state_change_event("binary_sensor.door", "on", "off")
        gate_cb(event)
        assert trigger.state == SubState.DONE
        assert on_change.call_count == 2

    def test_gate_listener_ignores_startup_events(self):
        from datetime import datetime
        config = {
            "type": "daily",
            "time": "08:00",
            "gate": {"entity_id": "binary_sensor.door", "state": "on"},
        }
        trigger = DailyTrigger(config)
        hass = MockHass()
        state_cbs, time_cbs, on_change = setup_listeners_capturing(hass, trigger)
        time_cb = time_cbs[0]
        gate_cb = state_cbs[0]

        # Time fires → ACTIVE
        time_cb(datetime(2025, 1, 15, 8, 0, 0))

        # Gate event with old_state=None (startup) → should be ignored
        event = make_state_change_event("binary_sensor.door", "on", None)
        gate_cb(event)
        assert trigger.state == SubState.ACTIVE  # still active, not done


class TestDurationTriggerListenerLifecycle:
    def test_no_gate_registers_one_listener(self):
        config = {
            "type": "duration",
            "entity_id": "binary_sensor.contact",
            "state": "on",
            "duration_hours": 1,
        }
        trigger = DurationTrigger(config)
        hass = MockHass()
        state_cbs, _, _ = setup_listeners_capturing(hass, trigger)
        assert len(state_cbs) == 1

    def test_with_gate_registers_two_listeners(self):
        config = {
            "type": "duration",
            "entity_id": "binary_sensor.contact",
            "state": "on",
            "duration_hours": 1,
            "gate": {"entity_id": "binary_sensor.gate", "state": "on"},
        }
        trigger = DurationTrigger(config)
        hass = MockHass()
        state_cbs, _, _ = setup_listeners_capturing(hass, trigger)
        assert len(state_cbs) == 2  # entity + gate


# ── Completion listener lifecycle ─────────────────────────────────────


class TestContactCompletionListenerLifecycle:
    def test_registers_one_listener(self):
        comp = ContactCompletion({"type": "contact", "entity_id": "binary_sensor.door"})
        hass = MockHass()
        state_cbs, _, _ = setup_listeners_capturing(hass, comp)
        assert len(state_cbs) == 1

    def test_remove_listeners(self):
        comp = ContactCompletion({"type": "contact", "entity_id": "binary_sensor.door"})
        hass = MockHass()
        setup_listeners_capturing(hass, comp)
        assert len(comp._listeners) == 1
        unsub = comp._listeners[0]
        comp.async_remove_listeners()
        assert len(comp._listeners) == 0
        unsub.assert_called_once()

    def test_listener_fires_done_on_contact_open(self):
        comp = ContactCompletion({"type": "contact", "entity_id": "binary_sensor.door"})
        comp.enable()
        hass = MockHass()
        state_cbs, _, on_change = setup_listeners_capturing(hass, comp)
        cb = state_cbs[0]

        event = make_state_change_event("binary_sensor.door", "on", "off")
        cb(event)
        assert comp.state == SubState.DONE
        on_change.assert_called_once()


class TestContactCycleListenerLifecycle:
    def test_registers_one_listener(self):
        comp = ContactCycleCompletion({
            "type": "contact_cycle",
            "entity_id": "binary_sensor.door",
        })
        hass = MockHass()
        state_cbs, _, _ = setup_listeners_capturing(hass, comp)
        assert len(state_cbs) == 1


class TestPresenceCycleListenerLifecycle:
    def test_registers_one_listener(self):
        comp = PresenceCycleCompletion({
            "type": "presence_cycle",
            "entity_id": "person.alice",
        })
        hass = MockHass()
        state_cbs, _, _ = setup_listeners_capturing(hass, comp)
        assert len(state_cbs) == 1


class TestSensorStateCompletionListenerLifecycle:
    def test_registers_one_listener(self):
        comp = SensorStateCompletion({
            "type": "sensor_state",
            "entity_id": "sensor.test",
            "state": "on",
        })
        hass = MockHass()
        state_cbs, _, _ = setup_listeners_capturing(hass, comp)
        assert len(state_cbs) == 1


# ── Coordinator listener orchestration ────────────────────────────────


class TestCoordinatorListenerOrchestration:
    def test_setup_listeners_calls_all_chores(self):
        from custom_components.chores.coordinator import ChoresCoordinator
        from custom_components.chores.chore_core import Chore
        from conftest import daily_manual_config, power_cycle_config

        hass = MockHass()
        store = MagicMock()
        store.get_chore_state = MagicMock(return_value=None)
        entry = MagicMock()
        entry.entry_id = "test"

        coord = ChoresCoordinator(hass, entry, store)
        c1 = Chore(daily_manual_config())
        c2 = Chore(power_cycle_config())
        coord.register_chore(c1)
        coord.register_chore(c2)

        c1.async_setup_listeners = MagicMock()
        c2.async_setup_listeners = MagicMock()

        coord.setup_listeners()
        c1.async_setup_listeners.assert_called_once()
        c2.async_setup_listeners.assert_called_once()

    def test_remove_listeners_calls_all_chores(self):
        from custom_components.chores.coordinator import ChoresCoordinator
        from custom_components.chores.chore_core import Chore
        from conftest import daily_manual_config, power_cycle_config

        hass = MockHass()
        store = MagicMock()
        store.get_chore_state = MagicMock(return_value=None)
        entry = MagicMock()
        entry.entry_id = "test"

        coord = ChoresCoordinator(hass, entry, store)
        c1 = Chore(daily_manual_config())
        c2 = Chore(power_cycle_config())
        coord.register_chore(c1)
        coord.register_chore(c2)

        c1.async_remove_listeners = MagicMock()
        c2.async_remove_listeners = MagicMock()

        coord.remove_listeners()
        c1.async_remove_listeners.assert_called_once()
        c2.async_remove_listeners.assert_called_once()
