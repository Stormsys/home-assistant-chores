"""Tests for completions.py — all 5 completion types + factory."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from conftest import MockHass, make_state_change_event, setup_listeners_capturing

from custom_components.chores.const import CompletionType, SubState
from custom_components.chores.completions import (
    ContactCompletion,
    ContactCycleCompletion,
    ManualCompletion,
    PresenceCycleCompletion,
    SensorStateCompletion,
    create_completion,
)


# ── BaseCompletion common behavior (tested via ManualCompletion) ─────


class TestBaseCompletionBehavior:
    def test_initial_state(self):
        c = ManualCompletion({"type": "manual"})
        assert c.state == SubState.IDLE
        assert c.steps_done == 0
        assert c.enabled is False

    def test_enable_disable(self):
        c = ManualCompletion({"type": "manual"})
        c.enable()
        assert c.enabled is True
        c.disable()
        assert c.enabled is False

    def test_reset(self):
        c = ManualCompletion({"type": "manual"})
        c.enable()
        c.set_state(SubState.DONE)
        c.reset()
        assert c.state == SubState.IDLE
        assert c.steps_done == 0
        assert c.enabled is False

    def test_set_state_active_sets_steps(self):
        c = ManualCompletion({"type": "manual"})
        c.set_state(SubState.ACTIVE)
        assert c.steps_done == 1

    def test_set_state_done_sets_steps_total(self):
        c = ManualCompletion({"type": "manual"})
        assert c.steps_total == 1
        c.set_state(SubState.DONE)
        assert c.steps_done == 1

    def test_set_state_returns_false_if_unchanged(self):
        c = ManualCompletion({"type": "manual"})
        assert c.set_state(SubState.IDLE) is False

    def test_set_state_returns_true_if_changed(self):
        c = ManualCompletion({"type": "manual"})
        assert c.set_state(SubState.DONE) is True

    def test_snapshot_restore(self):
        c = ManualCompletion({"type": "manual"})
        c.enable()
        c.set_state(SubState.DONE)
        snap = c.snapshot_state()
        assert snap["state"] == "done"
        assert snap["enabled"] is True
        assert snap["steps_done"] == 1
        c2 = ManualCompletion({"type": "manual"})
        c2.restore_state(snap)
        assert c2.state == SubState.DONE
        assert c2.enabled is True
        assert c2.steps_done == 1


# ── ManualCompletion ─────────────────────────────────────────────────


class TestManualCompletion:
    def test_type(self):
        c = ManualCompletion({"type": "manual"})
        assert c.completion_type == CompletionType.MANUAL

    def test_steps_total(self):
        c = ManualCompletion({"type": "manual"})
        assert c.steps_total == 1

    def test_extra_attributes(self):
        hass = MockHass()
        c = ManualCompletion({"type": "manual"})
        attrs = c.extra_attributes(hass)
        assert attrs["completion_type"] == "manual"
        assert attrs["steps_total"] == 1
        assert attrs["steps_done"] == 0


# ── SensorStateCompletion ────────────────────────────────────────────


class TestSensorStateCompletion:
    def _make(self, target_state="on"):
        return SensorStateCompletion({
            "type": "sensor_state",
            "entity_id": "sensor.some_sensor",
            "state": target_state,
        })

    def test_type(self):
        c = self._make()
        assert c.completion_type == CompletionType.SENSOR_STATE

    def test_steps_total(self):
        c = self._make()
        assert c.steps_total == 1

    def test_extra_attributes(self):
        hass = MockHass()
        hass.states.set("sensor.some_sensor", "off")
        c = self._make()
        attrs = c.extra_attributes(hass)
        assert attrs["completion_type"] == "sensor_state"
        assert attrs["watched_entity"] == "sensor.some_sensor"
        assert attrs["target_state"] == "on"
        assert attrs["watched_entity_state"] == "off"


# ── ContactCompletion ────────────────────────────────────────────────


class TestContactCompletion:
    def _make(self):
        return ContactCompletion({
            "type": "contact",
            "entity_id": "binary_sensor.door_contact",
        })

    def test_type(self):
        c = self._make()
        assert c.completion_type == CompletionType.CONTACT

    def test_steps_total(self):
        c = self._make()
        assert c.steps_total == 1

    def test_extra_attributes(self):
        hass = MockHass()
        hass.states.set("binary_sensor.door_contact", "off")
        c = self._make()
        attrs = c.extra_attributes(hass)
        assert attrs["completion_type"] == "contact"
        assert attrs["watched_entity"] == "binary_sensor.door_contact"


# ── ContactCycleCompletion ───────────────────────────────────────────


class TestContactCycleCompletion:
    def _make(self):
        return ContactCycleCompletion({
            "type": "contact_cycle",
            "entity_id": "binary_sensor.door_contact",
        })

    def test_type(self):
        c = self._make()
        assert c.completion_type == CompletionType.CONTACT_CYCLE

    def test_steps_total(self):
        c = self._make()
        assert c.steps_total == 2

    def test_step1_step2_lifecycle(self):
        """Test the two-step lifecycle: IDLE → ACTIVE → DONE."""
        c = self._make()
        c.enable()
        # Step 1: contact opens → ACTIVE
        c.set_state(SubState.ACTIVE)
        assert c.state == SubState.ACTIVE
        assert c.steps_done == 1
        # Step 2: contact closes → DONE
        c.set_state(SubState.DONE)
        assert c.state == SubState.DONE
        assert c.steps_done == 2

    def test_extra_attributes(self):
        hass = MockHass()
        hass.states.set("binary_sensor.door_contact", "off")
        c = self._make()
        attrs = c.extra_attributes(hass)
        assert attrs["completion_type"] == "contact_cycle"
        assert attrs["steps_total"] == 2


# ── PresenceCycleCompletion ──────────────────────────────────────────


class TestPresenceCycleCompletion:
    def test_type(self):
        c = PresenceCycleCompletion({
            "type": "presence_cycle",
            "entity_id": "person.alice",
        })
        assert c.completion_type == CompletionType.PRESENCE_CYCLE

    def test_steps_total(self):
        c = PresenceCycleCompletion({
            "type": "presence_cycle",
            "entity_id": "person.alice",
        })
        assert c.steps_total == 2

    def test_person_entity_uses_not_home_home(self):
        c = PresenceCycleCompletion({
            "type": "presence_cycle",
            "entity_id": "person.alice",
        })
        assert c._away_state == "not_home"
        assert c._home_state == "home"

    def test_device_tracker_uses_not_home_home(self):
        c = PresenceCycleCompletion({
            "type": "presence_cycle",
            "entity_id": "device_tracker.phone",
        })
        assert c._away_state == "not_home"
        assert c._home_state == "home"

    def test_binary_sensor_uses_off_on(self):
        c = PresenceCycleCompletion({
            "type": "presence_cycle",
            "entity_id": "binary_sensor.potty_holder",
        })
        assert c._away_state == "off"
        assert c._home_state == "on"

    def test_step1_step2_lifecycle(self):
        """Leave → return cycle."""
        c = PresenceCycleCompletion({
            "type": "presence_cycle",
            "entity_id": "person.alice",
        })
        c.enable()
        # Step 1: leaves
        c.set_state(SubState.ACTIVE)
        assert c.state == SubState.ACTIVE
        assert c.steps_done == 1
        # Step 2: returns
        c.set_state(SubState.DONE)
        assert c.state == SubState.DONE
        assert c.steps_done == 2

    def test_extra_attributes(self):
        hass = MockHass()
        hass.states.set("person.alice", "home")
        c = PresenceCycleCompletion({
            "type": "presence_cycle",
            "entity_id": "person.alice",
        })
        attrs = c.extra_attributes(hass)
        assert attrs["completion_type"] == "presence_cycle"
        assert attrs["away_state"] == "not_home"
        assert attrs["home_state"] == "home"
        assert attrs["steps_total"] == 2


# ── create_completion factory ────────────────────────────────────────


class TestCreateCompletionFactory:
    def test_manual(self):
        c = create_completion({"type": "manual"})
        assert isinstance(c, ManualCompletion)

    def test_sensor_state(self):
        c = create_completion({"type": "sensor_state", "entity_id": "sensor.x"})
        assert isinstance(c, SensorStateCompletion)

    def test_contact(self):
        c = create_completion({"type": "contact", "entity_id": "binary_sensor.x"})
        assert isinstance(c, ContactCompletion)

    def test_contact_cycle(self):
        c = create_completion({"type": "contact_cycle", "entity_id": "binary_sensor.x"})
        assert isinstance(c, ContactCycleCompletion)

    def test_presence_cycle(self):
        c = create_completion({"type": "presence_cycle", "entity_id": "person.x"})
        assert isinstance(c, PresenceCycleCompletion)

    def test_default_is_manual(self):
        c = create_completion({})
        assert isinstance(c, ManualCompletion)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown completion type"):
            create_completion({"type": "nonexistent"})


# ── ContactCycleCompletion debounce tests ─────────────────────────────


class TestContactCycleDebounce:
    """Tests for the debounce timer in ContactCycleCompletion."""

    def _make(self, debounce_seconds=2):
        return ContactCycleCompletion({
            "type": "contact_cycle",
            "entity_id": "binary_sensor.door",
            "debounce_seconds": debounce_seconds,
        })

    def test_debounce_timer_started_on_open(self):
        """Opening sets up a pending callback, not immediate ACTIVE."""
        comp = self._make()
        comp.enable()
        hass = MockHass()
        state_cbs, _, on_change = setup_listeners_capturing(hass, comp)
        assert len(state_cbs) == 1
        listener_cb = state_cbs[0]

        def _fake_call_later(hass_arg, delay, cb):
            cancel = MagicMock()
            cancel._deferred_cb = cb
            return cancel

        event = make_state_change_event("binary_sensor.door", "on", "off")
        with patch("custom_components.chores.completions.async_call_later", _fake_call_later):
            listener_cb(event)
        assert comp._pending_active_cancel is not None
        # Should still be IDLE — debounce hasn't fired yet
        assert comp.state == SubState.IDLE

    def test_debounce_fires_transitions_to_active(self):
        """When debounce timer fires, completion goes ACTIVE."""
        comp = self._make()
        comp.enable()
        hass = MockHass()
        state_cbs, _, on_change = setup_listeners_capturing(hass, comp)
        listener_cb = state_cbs[0]

        def _fake_call_later(hass_arg, delay, cb):
            cancel = MagicMock()
            cancel._deferred_cb = cb
            return cancel

        event = make_state_change_event("binary_sensor.door", "on", "off")
        with patch("custom_components.chores.completions.async_call_later", _fake_call_later):
            listener_cb(event)
        # Manually fire the deferred callback (simulating timer expiry)
        deferred = comp._pending_active_cancel._deferred_cb
        deferred(None)  # _confirm_active(now)
        assert comp.state == SubState.ACTIVE
        on_change.assert_called()

    def test_bounce_back_cancels_debounce(self):
        """Closing before debounce fires cancels the pending ACTIVE."""
        comp = self._make()
        comp.enable()
        hass = MockHass()
        state_cbs, _, on_change = setup_listeners_capturing(hass, comp)
        listener_cb = state_cbs[0]

        def _fake_call_later(hass_arg, delay, cb):
            cancel = MagicMock()
            cancel._deferred_cb = cb
            return cancel

        # Simulate open
        event_open = make_state_change_event("binary_sensor.door", "on", "off")
        with patch("custom_components.chores.completions.async_call_later", _fake_call_later):
            listener_cb(event_open)
        pending = comp._pending_active_cancel
        assert pending is not None

        # Simulate close before debounce fires
        event_close = make_state_change_event("binary_sensor.door", "off", "on")
        listener_cb(event_close)
        assert comp._pending_active_cancel is None
        assert comp.state == SubState.IDLE
        pending.assert_called_once()  # The cancel callable was invoked

    def test_reset_cancels_pending_debounce(self):
        """Resetting the completion cancels any pending debounce timer."""
        comp = self._make()
        comp.enable()
        cancel_mock = MagicMock()
        comp._pending_active_cancel = cancel_mock
        comp.reset()
        cancel_mock.assert_called_once()
        assert comp._pending_active_cancel is None

    def test_step2_close_from_active(self):
        """Closing while ACTIVE completes the cycle (step 2)."""
        comp = self._make()
        comp.enable()
        hass = MockHass()
        state_cbs, _, on_change = setup_listeners_capturing(hass, comp)
        listener_cb = state_cbs[0]

        comp.set_state(SubState.ACTIVE)
        event_close = make_state_change_event("binary_sensor.door", "off", "on")
        listener_cb(event_close)
        assert comp.state == SubState.DONE
        on_change.assert_called()

    def test_ignores_startup_events(self):
        """Events with old_state=None (startup) are ignored."""
        comp = self._make()
        comp.enable()
        hass = MockHass()
        state_cbs, _, on_change = setup_listeners_capturing(hass, comp)
        listener_cb = state_cbs[0]

        event = make_state_change_event("binary_sensor.door", "on", None)
        listener_cb(event)
        assert comp.state == SubState.IDLE
        assert comp._pending_active_cancel is None

    def test_ignores_unavailable_old_state(self):
        """Events where old_state is unavailable are ignored."""
        comp = self._make()
        comp.enable()
        hass = MockHass()
        state_cbs, _, on_change = setup_listeners_capturing(hass, comp)
        listener_cb = state_cbs[0]

        event = make_state_change_event("binary_sensor.door", "on", "unavailable")
        listener_cb(event)
        assert comp.state == SubState.IDLE

    def test_ignores_unknown_old_state(self):
        comp = self._make()
        comp.enable()
        hass = MockHass()
        state_cbs, _, _ = setup_listeners_capturing(hass, comp)
        listener_cb = state_cbs[0]

        event = make_state_change_event("binary_sensor.door", "on", "unknown")
        listener_cb(event)
        assert comp.state == SubState.IDLE

    def test_disabled_listener_is_noop(self):
        """When disabled, listener fires but does nothing."""
        comp = self._make()
        # NOT enabled
        hass = MockHass()
        state_cbs, _, on_change = setup_listeners_capturing(hass, comp)
        listener_cb = state_cbs[0]

        event = make_state_change_event("binary_sensor.door", "on", "off")
        listener_cb(event)
        assert comp.state == SubState.IDLE
        on_change.assert_not_called()


# ── PresenceCycleCompletion startup filtering ─────────────────────────


class TestPresenceCycleStartupFiltering:
    def test_ignores_startup_events(self):
        comp = PresenceCycleCompletion({
            "type": "presence_cycle",
            "entity_id": "person.alice",
        })
        comp.enable()
        hass = MockHass()
        state_cbs, _, _ = setup_listeners_capturing(hass, comp)
        listener_cb = state_cbs[0]

        event = make_state_change_event("person.alice", "not_home", None)
        listener_cb(event)
        assert comp.state == SubState.IDLE

    def test_ignores_unavailable_old_state(self):
        comp = PresenceCycleCompletion({
            "type": "presence_cycle",
            "entity_id": "person.alice",
        })
        comp.enable()
        hass = MockHass()
        state_cbs, _, _ = setup_listeners_capturing(hass, comp)
        listener_cb = state_cbs[0]

        event = make_state_change_event("person.alice", "not_home", "unavailable")
        listener_cb(event)
        assert comp.state == SubState.IDLE

    def test_disabled_listener_is_noop(self):
        comp = PresenceCycleCompletion({
            "type": "presence_cycle",
            "entity_id": "person.alice",
        })
        # NOT enabled
        hass = MockHass()
        state_cbs, _, on_change = setup_listeners_capturing(hass, comp)
        listener_cb = state_cbs[0]

        event = make_state_change_event("person.alice", "not_home", "home")
        listener_cb(event)
        assert comp.state == SubState.IDLE
        on_change.assert_not_called()

    def test_full_leave_return_via_listener(self):
        """Full cycle driven via the actual listener callback."""
        comp = PresenceCycleCompletion({
            "type": "presence_cycle",
            "entity_id": "person.alice",
        })
        comp.enable()
        hass = MockHass()
        state_cbs, _, on_change = setup_listeners_capturing(hass, comp)
        listener_cb = state_cbs[0]

        # Step 1: leave
        event_leave = make_state_change_event("person.alice", "not_home", "home")
        listener_cb(event_leave)
        assert comp.state == SubState.ACTIVE
        assert on_change.call_count == 1

        # Step 2: return
        event_return = make_state_change_event("person.alice", "home", "not_home")
        listener_cb(event_return)
        assert comp.state == SubState.DONE
        assert on_change.call_count == 2


# ── SensorStateCompletion disabled/new_state=None tests ──────────────


class TestSensorStateCompletionEdgeCases:
    def test_disabled_listener_is_noop(self):
        comp = SensorStateCompletion({
            "type": "sensor_state",
            "entity_id": "sensor.test",
            "state": "on",
        })
        # NOT enabled
        hass = MockHass()
        state_cbs, _, on_change = setup_listeners_capturing(hass, comp)
        listener_cb = state_cbs[0]

        event = make_state_change_event("sensor.test", "on", "off")
        listener_cb(event)
        assert comp.state == SubState.IDLE
        on_change.assert_not_called()

    def test_new_state_none_is_noop(self):
        comp = SensorStateCompletion({
            "type": "sensor_state",
            "entity_id": "sensor.test",
            "state": "on",
        })
        comp.enable()
        hass = MockHass()
        state_cbs, _, _ = setup_listeners_capturing(hass, comp)
        listener_cb = state_cbs[0]

        event = MagicMock()
        event.data = {"entity_id": "sensor.test", "new_state": None, "old_state": MagicMock()}
        listener_cb(event)
        assert comp.state == SubState.IDLE

    def test_extra_attributes_entity_not_found(self):
        """Entity not in hass.states → watched_entity_state=None."""
        comp = SensorStateCompletion({
            "type": "sensor_state",
            "entity_id": "sensor.nonexistent",
            "state": "on",
        })
        hass = MockHass()
        attrs = comp.extra_attributes(hass)
        assert attrs["watched_entity_state"] is None

    def test_already_done_ignores_duplicate(self):
        """If already DONE, another matching event doesn't re-trigger."""
        comp = SensorStateCompletion({
            "type": "sensor_state",
            "entity_id": "sensor.test",
            "state": "on",
        })
        comp.enable()
        comp.set_state(SubState.DONE)
        hass = MockHass()
        state_cbs, _, on_change = setup_listeners_capturing(hass, comp)
        listener_cb = state_cbs[0]

        event = make_state_change_event("sensor.test", "on", "off")
        listener_cb(event)
        assert comp.state == SubState.DONE
        on_change.assert_not_called()
