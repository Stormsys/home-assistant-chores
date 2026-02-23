"""Tests for YAML schema validation in __init__.py."""
from __future__ import annotations

import pytest
import voluptuous as vol

from conftest import (
    daily_gate_contact_config,
    daily_gate_manual_config,
    daily_manual_config,
    daily_presence_afternoon_config,
    daily_presence_config,
    daily_sensor_threshold_config,
    duration_contact_cycle_config,
    power_cycle_config,
    state_change_presence_config,
    weekly_gate_manual_config,
)

from custom_components.chores import (
    CHORE_SCHEMA,
    COMPLETION_SCHEMA,
    CONFIG_SCHEMA,
    RESET_SCHEMA,
    TRIGGER_SCHEMA,
)


# ── Each example config validates against CHORE_SCHEMA ───────────────


class TestExampleConfigsValidate:
    """Every example config from example_configuration.yaml must validate."""

    @pytest.mark.parametrize("config_fn", [
        power_cycle_config,
        daily_gate_contact_config,
        daily_manual_config,
        daily_gate_manual_config,
        daily_presence_config,
        daily_presence_afternoon_config,
        weekly_gate_manual_config,
        duration_contact_cycle_config,
        state_change_presence_config,
        daily_sensor_threshold_config,
    ])
    def test_validates(self, config_fn):
        config = config_fn()
        result = CHORE_SCHEMA(config)
        assert result["id"] == config["id"]
        assert result["name"] == config["name"]


# ── CONFIG_SCHEMA (integration-level) ────────────────────────────────


class TestConfigSchema:
    def test_full_config_validates(self):
        config = {
            "chores": {
                "logbook": True,
                "chores": [daily_manual_config()],
            }
        }
        result = CONFIG_SCHEMA(config)
        assert "chores" in result
        assert len(result["chores"]["chores"]) == 1

    def test_empty_chores_list(self):
        config = {"chores": {"chores": []}}
        result = CONFIG_SCHEMA(config)
        assert result["chores"]["chores"] == []

    def test_logbook_default_true(self):
        config = {"chores": {"chores": []}}
        result = CONFIG_SCHEMA(config)
        assert result["chores"]["logbook"] is True

    def test_logbook_false(self):
        config = {"chores": {"logbook": False, "chores": []}}
        result = CONFIG_SCHEMA(config)
        assert result["chores"]["logbook"] is False


# ── TRIGGER_SCHEMA ───────────────────────────────────────────────────


class TestTriggerSchema:
    def test_power_cycle(self):
        config = {"type": "power_cycle", "power_sensor": "sensor.plug_power"}
        result = TRIGGER_SCHEMA(config)
        assert result["type"] == "power_cycle"
        assert result["power_threshold"] == 10.0  # default
        assert result["cooldown_minutes"] == 5  # default

    def test_state_change(self):
        config = {
            "type": "state_change",
            "entity_id": "input_boolean.x",
            "from": "off",
            "to": "on",
        }
        result = TRIGGER_SCHEMA(config)
        assert result["from"] == "off"
        assert result["to"] == "on"

    def test_daily(self):
        config = {"type": "daily", "time": "08:00"}
        result = TRIGGER_SCHEMA(config)
        assert result["time"] == "08:00"

    def test_daily_with_gate(self):
        config = {
            "type": "daily",
            "time": "06:00",
            "gate": {
                "entity_id": "binary_sensor.door",
                "state": "on",
            },
        }
        result = TRIGGER_SCHEMA(config)
        assert result["gate"]["entity_id"] == "binary_sensor.door"

    def test_weekly(self):
        config = {
            "type": "weekly",
            "schedule": [{"day": "wed", "time": "17:00"}],
        }
        result = TRIGGER_SCHEMA(config)
        assert len(result["schedule"]) == 1

    def test_duration(self):
        config = {
            "type": "duration",
            "entity_id": "binary_sensor.rack",
            "duration_hours": 48,
        }
        result = TRIGGER_SCHEMA(config)
        assert result["duration_hours"] == 48.0
        assert result["state"] == "on"  # default

    def test_duration_zero_rejected(self):
        config = {
            "type": "duration",
            "entity_id": "binary_sensor.rack",
            "duration_hours": 0,
        }
        with pytest.raises(vol.Invalid):
            TRIGGER_SCHEMA(config)

    def test_power_cycle_with_gate(self):
        config = {
            "type": "power_cycle",
            "power_sensor": "sensor.plug_power",
            "gate": {"entity_id": "binary_sensor.door", "state": "on"},
        }
        result = TRIGGER_SCHEMA(config)
        assert result["gate"]["entity_id"] == "binary_sensor.door"

    def test_state_change_with_gate(self):
        config = {
            "type": "state_change",
            "entity_id": "input_boolean.x",
            "from": "off",
            "to": "on",
            "gate": {"entity_id": "binary_sensor.door", "state": "on"},
        }
        result = TRIGGER_SCHEMA(config)
        assert result["gate"]["state"] == "on"

    # ── Cross-stage trigger types ────────────────────────────────────

    def test_sensor_state_as_trigger(self):
        config = {
            "type": "sensor_state",
            "entity_id": "sensor.x",
        }
        result = TRIGGER_SCHEMA(config)
        assert result["state"] == "on"  # default

    def test_contact_as_trigger(self):
        config = {
            "type": "contact",
            "entity_id": "binary_sensor.door",
        }
        result = TRIGGER_SCHEMA(config)
        assert result["entity_id"] == "binary_sensor.door"

    def test_contact_cycle_as_trigger(self):
        config = {
            "type": "contact_cycle",
            "entity_id": "binary_sensor.door",
        }
        result = TRIGGER_SCHEMA(config)
        assert result["debounce_seconds"] == 2  # default

    def test_presence_cycle_as_trigger(self):
        config = {
            "type": "presence_cycle",
            "entity_id": "person.alice",
        }
        result = TRIGGER_SCHEMA(config)
        assert result["entity_id"] == "person.alice"

    def test_sensor_threshold_as_trigger(self):
        config = {
            "type": "sensor_threshold",
            "entity_id": "sensor.temperature",
            "threshold": 30,
        }
        result = TRIGGER_SCHEMA(config)
        assert result["threshold"] == 30.0
        assert result["operator"] == "above"  # default

    def test_cross_stage_trigger_with_gate(self):
        config = {
            "type": "sensor_state",
            "entity_id": "sensor.x",
            "gate": {"entity_id": "binary_sensor.gate", "state": "on"},
        }
        result = TRIGGER_SCHEMA(config)
        assert result["gate"]["entity_id"] == "binary_sensor.gate"

    def test_invalid_type_rejected(self):
        config = {"type": "nonexistent"}
        with pytest.raises(vol.Invalid):
            TRIGGER_SCHEMA(config)


# ── COMPLETION_SCHEMA ────────────────────────────────────────────────


class TestCompletionSchema:
    def test_manual(self):
        result = COMPLETION_SCHEMA({"type": "manual"})
        assert result["type"] == "manual"

    def test_sensor_state(self):
        result = COMPLETION_SCHEMA({
            "type": "sensor_state",
            "entity_id": "sensor.x",
        })
        assert result["state"] == "on"  # default

    def test_contact(self):
        result = COMPLETION_SCHEMA({
            "type": "contact",
            "entity_id": "binary_sensor.door",
        })
        assert result["entity_id"] == "binary_sensor.door"

    def test_contact_cycle(self):
        result = COMPLETION_SCHEMA({
            "type": "contact_cycle",
            "entity_id": "binary_sensor.door",
        })
        assert result["debounce_seconds"] == 2  # default

    def test_presence_cycle(self):
        result = COMPLETION_SCHEMA({
            "type": "presence_cycle",
            "entity_id": "person.alice",
        })
        assert result["entity_id"] == "person.alice"

    def test_sensor_threshold(self):
        result = COMPLETION_SCHEMA({
            "type": "sensor_threshold",
            "entity_id": "sensor.temperature",
            "threshold": 30,
        })
        assert result["threshold"] == 30.0
        assert result["operator"] == "above"  # default

    def test_sensor_threshold_below(self):
        result = COMPLETION_SCHEMA({
            "type": "sensor_threshold",
            "entity_id": "sensor.temperature",
            "threshold": 5.0,
            "operator": "below",
        })
        assert result["operator"] == "below"

    def test_sensor_threshold_invalid_operator_rejected(self):
        config = {
            "type": "sensor_threshold",
            "entity_id": "sensor.temperature",
            "threshold": 30,
            "operator": "invalid",
        }
        with pytest.raises(vol.Invalid):
            COMPLETION_SCHEMA(config)

    # ── Gate support on completions ──────────────────────────────────

    def test_sensor_state_with_gate(self):
        result = COMPLETION_SCHEMA({
            "type": "sensor_state",
            "entity_id": "sensor.x",
            "gate": {"entity_id": "binary_sensor.gate", "state": "on"},
        })
        assert result["gate"]["entity_id"] == "binary_sensor.gate"

    def test_contact_with_gate(self):
        result = COMPLETION_SCHEMA({
            "type": "contact",
            "entity_id": "binary_sensor.door",
            "gate": {"entity_id": "binary_sensor.gate", "state": "on"},
        })
        assert result["gate"]["state"] == "on"

    def test_contact_cycle_with_gate(self):
        result = COMPLETION_SCHEMA({
            "type": "contact_cycle",
            "entity_id": "binary_sensor.door",
            "gate": {"entity_id": "binary_sensor.gate", "state": "on"},
        })
        assert result["gate"]["entity_id"] == "binary_sensor.gate"

    # ── Cross-stage completion types ─────────────────────────────────

    def test_power_cycle_as_completion(self):
        result = COMPLETION_SCHEMA({
            "type": "power_cycle",
            "power_sensor": "sensor.plug_power",
        })
        assert result["type"] == "power_cycle"
        assert result["power_threshold"] == 10.0  # default
        assert result["cooldown_minutes"] == 5  # default

    def test_state_change_as_completion(self):
        result = COMPLETION_SCHEMA({
            "type": "state_change",
            "entity_id": "input_boolean.x",
            "from": "off",
            "to": "on",
        })
        assert result["from"] == "off"
        assert result["to"] == "on"

    def test_duration_as_completion(self):
        result = COMPLETION_SCHEMA({
            "type": "duration",
            "entity_id": "binary_sensor.rack",
            "duration_hours": 2,
        })
        assert result["duration_hours"] == 2.0
        assert result["state"] == "on"  # default

    def test_cross_stage_completion_with_gate(self):
        result = COMPLETION_SCHEMA({
            "type": "power_cycle",
            "power_sensor": "sensor.plug_power",
            "gate": {"entity_id": "binary_sensor.gate", "state": "on"},
        })
        assert result["gate"]["entity_id"] == "binary_sensor.gate"


# ── RESET_SCHEMA ─────────────────────────────────────────────────────


class TestResetSchema:
    def test_delay(self):
        result = RESET_SCHEMA({"type": "delay", "minutes": 30})
        assert result["minutes"] == 30

    def test_delay_default_minutes(self):
        result = RESET_SCHEMA({"type": "delay"})
        assert result["minutes"] == 0

    def test_daily_reset(self):
        result = RESET_SCHEMA({"type": "daily_reset", "time": "05:00"})
        assert result["type"] == "daily_reset"


# ── CHORE_SCHEMA defaults ───────────────────────────────────────────


class TestChoreSchemaDefaults:
    def test_completion_defaults_to_manual(self):
        config = {
            "id": "test",
            "name": "Test",
            "trigger": {"type": "daily", "time": "08:00"},
        }
        result = CHORE_SCHEMA(config)
        assert result["completion"]["type"] == "manual"

    def test_icon_default(self):
        config = {
            "id": "test",
            "name": "Test",
            "trigger": {"type": "daily", "time": "08:00"},
        }
        result = CHORE_SCHEMA(config)
        assert result["icon"] == "mdi:checkbox-marked-circle-outline"

    def test_state_labels_default_empty(self):
        config = {
            "id": "test",
            "name": "Test",
            "trigger": {"type": "daily", "time": "08:00"},
        }
        result = CHORE_SCHEMA(config)
        assert result["state_labels"] == {}

    def test_missing_required_id_rejected(self):
        config = {
            "name": "Test",
            "trigger": {"type": "daily", "time": "08:00"},
        }
        with pytest.raises(vol.Invalid):
            CHORE_SCHEMA(config)

    def test_missing_required_trigger_rejected(self):
        config = {"id": "test", "name": "Test"}
        with pytest.raises(vol.Invalid):
            CHORE_SCHEMA(config)
