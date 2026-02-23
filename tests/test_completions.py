"""Tests for completions.py — all 5 completion types + factory."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from conftest import MockHass, make_state_change_event

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
