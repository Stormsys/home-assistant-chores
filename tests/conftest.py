"""Shared fixtures for the Chores integration test suite.

Stubs out heavy HA dependencies (config_entries, update_coordinator, entity
platforms) that cannot be installed in lightweight CI environments, then
provides helper fixtures for building chore configurations matching all 9
example configs and a mock HomeAssistant object for testing.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, time, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Stub heavy HA modules before any custom_components imports ───────
# The core modules we need (homeassistant.core, .util.dt, .helpers.event,
# .helpers.config_validation, .helpers.storage) are importable.  The deeper
# modules (config_entries, update_coordinator, entity platforms, device/entity
# registries) pull in websocket_api -> auth -> jwt -> cryptography which
# cannot be built here.  We stub them with minimal stand-ins.

_STUB_MODULES: dict[str, Any] = {}


def _ensure_stub(name: str, attrs: dict[str, Any] | None = None) -> types.ModuleType:
    """Create a stub module and register it in sys.modules."""
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    if attrs:
        for k, v in attrs.items():
            setattr(mod, k, v)
    sys.modules[name] = mod
    _STUB_MODULES[name] = mod
    return mod


# atomicwrites (needed for homeassistant.util.file)
_ensure_stub("atomicwrites", {"AtomicWriter": type("AtomicWriter", (), {})})

# aiozoneinfo (needed by homeassistant.util.dt in newer HA versions)
_ensure_stub("aiozoneinfo", {
    "async_get_time_zone": lambda tz_name: None,
})

# homeassistant.helpers.template — imported by helpers.event; pulls in jinja2,
# lru-dict, and other heavy deps we don't need.  Stub before importing event.
# Template may be a package (newer HA) or a single module (older HA), so we
# stub both the package and its submodules.
_template_attrs = {
    "RenderInfo": type("RenderInfo", (), {}),
    "Template": type("Template", (), {}),
    "result_as_boolean": lambda *a: False,
}
_tmpl = _ensure_stub("homeassistant.helpers.template", _template_attrs)
_tmpl.__path__ = []  # make it a package so submodule imports don't fail
_ensure_stub("homeassistant.helpers.template.render_info", {
    "RenderInfo": _template_attrs["RenderInfo"],
})


# ── Now the real HA imports that DO work ────────────────────────────
from homeassistant.core import HomeAssistant, callback, Event  # noqa: E402
from homeassistant.util import dt as dt_util  # noqa: E402
from homeassistant.helpers.event import (  # noqa: E402
    async_track_state_change_event,
    async_track_time_change,
)

# ── Stub the heavy modules ──────────────────────────────────────────

# ConfigEntry stub
class _StubConfigEntry:
    def __init__(self, **kwargs):
        self.entry_id = kwargs.get("entry_id", "test_entry_id")
        self.domain = kwargs.get("domain", "chores")
        self.title = kwargs.get("title", "Chores")
        self.data = kwargs.get("data", {})
        self.options = kwargs.get("options", {})
        self.unique_id = kwargs.get("unique_id", "chores")
        self.version = kwargs.get("version", 2)


_config_entries_mod = _ensure_stub("homeassistant.config_entries", {
    "ConfigEntry": _StubConfigEntry,
})

# async_interrupt
_ensure_stub("async_interrupt", {"interrupt": lambda: None})

# persistent_notification (pulled in by config_entries)
_ensure_stub("homeassistant.components.persistent_notification")

# update_coordinator stub
class _StubDataUpdateCoordinator:
    def __init__(self, hass, logger, *, name="", update_interval=None):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = {}

    def __class_getitem__(cls, item):
        return cls

    def async_set_updated_data(self, data):
        self.data = data

    async def async_config_entry_first_refresh(self):
        pass


_ensure_stub("homeassistant.helpers.update_coordinator", {
    "DataUpdateCoordinator": _StubDataUpdateCoordinator,
    "CoordinatorEntity": type("CoordinatorEntity", (), {
        "__init__": lambda self, coordinator: None,
        "__class_getitem__": classmethod(lambda cls, item: cls),
    }),
})

# Entity platform stubs
class _StubEntity:
    _attr_has_entity_name = False
    _attr_unique_id = ""
    _attr_name = ""
    _attr_device_info = None
    _attr_options = []
    _attr_device_class = None
    _attr_entity_category = None

    def async_write_ha_state(self):
        pass

class _StubSensorEntity(_StubEntity):
    pass

class _StubSensorEntityDescription:
    pass

class _StubSensorDeviceClass:
    ENUM = "enum"
    TIMESTAMP = "timestamp"

_ensure_stub("homeassistant.components.sensor", {
    "SensorEntity": _StubSensorEntity,
    "SensorEntityDescription": _StubSensorEntityDescription,
    "SensorDeviceClass": _StubSensorDeviceClass,
})

class _StubBinarySensorEntity(_StubEntity):
    pass

class _StubBinarySensorDeviceClass:
    PROBLEM = "problem"

_ensure_stub("homeassistant.components.binary_sensor", {
    "BinarySensorEntity": _StubBinarySensorEntity,
    "BinarySensorDeviceClass": _StubBinarySensorDeviceClass,
})

class _StubButtonEntity(_StubEntity):
    pass

_ensure_stub("homeassistant.components.button", {
    "ButtonEntity": _StubButtonEntity,
})

# Device/entity registry stubs
class _StubDeviceInfo(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        for k, v in kwargs.items():
            setattr(self, k, v)

_ensure_stub("homeassistant.helpers.device_registry", {
    "DeviceInfo": _StubDeviceInfo,
    "async_get": lambda hass: MagicMock(),
    "async_entries_for_config_entry": lambda reg, entry_id: [],
})

_ensure_stub("homeassistant.helpers.entity_registry", {
    "async_get": lambda hass: MagicMock(),
})

class _StubEntityCategory:
    DIAGNOSTIC = "diagnostic"

_ensure_stub("homeassistant.helpers.entity", {
    "EntityCategory": _StubEntityCategory,
})

_ensure_stub("homeassistant.helpers.entity_platform", {
    "AddEntitiesCallback": Any,
    "async_get_current_platform": lambda: MagicMock(),
})

class _StubPlatform:
    BINARY_SENSOR = "binary_sensor"
    SENSOR = "sensor"
    BUTTON = "button"

_ensure_stub("homeassistant.const", {
    "Platform": _StubPlatform,
})

_ensure_stub("homeassistant.helpers.service", {
    "async_register_admin_service": lambda *a, **kw: None,
})


# ── Now import our integration modules ──────────────────────────────
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from custom_components.chores.const import (  # noqa: E402
    ChoreState,
    CompletionType,
    DetectorType,
    ResetType,
    SubState,
    TriggerType,
)
from custom_components.chores.chore_core import Chore  # noqa: E402
from custom_components.chores.triggers import (  # noqa: E402
    TriggerStage,
    BaseTrigger,
    create_trigger,
)
from custom_components.chores.completions import (  # noqa: E402
    CompletionStage,
    BaseCompletion,
    create_completion,
)
from custom_components.chores.detectors import (  # noqa: E402
    BaseDetector,
    ContactCycleDetector,
    ContactDetector,
    DailyDetector,
    DurationDetector,
    ManualDetector,
    PowerCycleDetector,
    PresenceCycleDetector,
    SensorStateDetector,
    SensorThresholdDetector,
    StateChangeDetector,
    WeeklyDetector,
    create_detector,
)
from custom_components.chores.gate import Gate  # noqa: E402
from custom_components.chores.resets import (  # noqa: E402
    BaseReset,
    DailyReset,
    DelayReset,
    ImplicitDailyReset,
    ImplicitEventReset,
    ImplicitWeeklyReset,
    create_reset,
)


# ── Mock HomeAssistant fixture ──────────────────────────────────────


class MockStates:
    """Minimal mock for hass.states."""

    def __init__(self):
        self._states: dict[str, MagicMock] = {}

    def get(self, entity_id: str) -> MagicMock | None:
        return self._states.get(entity_id)

    def set(self, entity_id: str, state_value: str, attributes: dict | None = None):
        """Set a mock state for an entity."""
        mock_state = MagicMock()
        mock_state.state = state_value
        mock_state.attributes = attributes or {}
        self._states[entity_id] = mock_state

    def async_set(self, entity_id: str, state_value: str, attributes: dict | None = None):
        self.set(entity_id, state_value, attributes)

    def remove(self, entity_id: str):
        self._states.pop(entity_id, None)


class MockBus:
    """Minimal mock for hass.bus — captures fired events."""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def async_fire(self, event_type: str, event_data: dict | None = None):
        self.events.append((event_type, event_data or {}))

    def clear(self):
        self.events.clear()


class MockHass:
    """Lightweight mock HomeAssistant object for testing."""

    def __init__(self):
        self.states = MockStates()
        self.bus = MockBus()
        self.data: dict[str, Any] = {}
        self.services = MagicMock()
        # Populated by captured_listener_setup() context manager
        self._last_state_listener: Any = None
        self._last_time_listener: Any = None


@pytest.fixture
def hass():
    """Return a mock HomeAssistant instance."""
    return MockHass()


def setup_listeners_capturing(hass, component, on_change=None):
    """Set up listeners on a trigger/completion/detector while capturing the callbacks.

    Patches async_track_state_change_event, async_track_time_change, and
    async_call_later across all detector modules and gate.py so the inner
    listener callbacks are stored on hass for direct invocation.
    Returns (state_listeners, time_listeners, on_change) lists of captured callbacks.
    """
    if on_change is None:
        on_change = MagicMock()

    state_listeners: list[Any] = []
    time_listeners: list[Any] = []

    def _fake_track_state(hass_arg, entities, cb):
        state_listeners.append(cb)
        hass._last_state_listener = cb
        unsub = MagicMock()
        return unsub

    def _fake_track_time(hass_arg, cb, **kwargs):
        time_listeners.append(cb)
        hass._last_time_listener = cb
        unsub = MagicMock()
        return unsub

    def _fake_call_later(hass_arg, delay, cb):
        """For debounce: return a cancel callable that records it was cancelled."""
        cancel = MagicMock()
        # Store the callback so tests can invoke it manually
        cancel._deferred_cb = cb
        return cancel

    # Patch all detector modules and gate that import event helpers
    _det = "custom_components.chores.detectors"
    _state_modules = [
        f"{_det}.power_cycle",
        f"{_det}.state_change",
        f"{_det}.duration",
        f"{_det}.sensor_state",
        f"{_det}.contact",
        f"{_det}.contact_cycle",
        f"{_det}.presence_cycle",
        f"{_det}.sensor_threshold",
        "custom_components.chores.gate",
    ]
    _time_modules = [f"{_det}.daily", f"{_det}.weekly"]
    _call_later_modules = [f"{_det}.contact_cycle"]

    patches = []
    for mod in _state_modules:
        patches.append(patch(f"{mod}.async_track_state_change_event", _fake_track_state))
    for mod in _time_modules:
        patches.append(patch(f"{mod}.async_track_time_change", _fake_track_time))
    for mod in _call_later_modules:
        patches.append(patch(f"{mod}.async_call_later", _fake_call_later))

    for p in patches:
        p.start()
    try:
        component.async_setup_listeners(hass, on_change)
    finally:
        for p in patches:
            p.stop()

    return state_listeners, time_listeners, on_change


# ── Helper to create HA state-change Events ─────────────────────────


def make_state_change_event(
    entity_id: str,
    new_state_value: str,
    old_state_value: str | None = None,
) -> Event:
    """Create a mock state change event matching HA's format."""
    new_state = MagicMock()
    new_state.state = new_state_value
    new_state.entity_id = entity_id

    if old_state_value is not None:
        old_state = MagicMock()
        old_state.state = old_state_value
        old_state.entity_id = entity_id
    else:
        old_state = None

    event = MagicMock(spec=Event)
    event.data = {
        "entity_id": entity_id,
        "new_state": new_state,
        "old_state": old_state,
    }
    return event


# ── Config builders for all 9 example configurations ────────────────


def power_cycle_config() -> dict[str, Any]:
    """Unload Washing Machine — power_cycle + contact + implicit_event."""
    return {
        "id": "unload_washing",
        "name": "Unload Washing Machine",
        "icon": "mdi:washing-machine",
        "trigger": {
            "type": "power_cycle",
            "power_sensor": "sensor.washing_machine_plug_power",
            "current_sensor": "sensor.washing_machine_plug_current",
            "power_threshold": 10,
            "current_threshold": 0.04,
            "cooldown_minutes": 5,
            "sensor": {
                "name": "Washing Machine",
                "icon_idle": "mdi:washing-machine-off",
                "icon_active": "mdi:washing-machine",
                "icon_done": "mdi:washing-machine-alert",
            },
        },
        "completion": {
            "type": "contact",
            "entity_id": "binary_sensor.washing_machine_door_contact",
        },
    }


def daily_gate_contact_config() -> dict[str, Any]:
    """Take Vitamins — daily + gate + contact + implicit_daily."""
    return {
        "id": "take_vitamins",
        "name": "Take Vitamins",
        "description": "Take daily multivitamin and omega-3 capsule",
        "context": "Important for long-term health",
        "icon": "mdi:pill",
        "trigger": {
            "type": "daily",
            "time": "06:00",
            "gate": {
                "entity_id": "binary_sensor.bedroom_door_contact",
                "state": "on",
            },
            "sensor": {
                "name": "Morning Vitamins Schedule",
            },
        },
        "completion": {
            "type": "contact",
            "entity_id": "binary_sensor.coffee_cupboard_door_contact",
        },
    }


def daily_manual_config() -> dict[str, Any]:
    """Feed Fay Morning — daily + manual + implicit_daily."""
    return {
        "id": "feed_fay_morning",
        "name": "Feed Fay Morning",
        "icon": "mdi:dog-bowl",
        "trigger": {
            "type": "daily",
            "time": "08:00",
        },
        "completion": {
            "type": "manual",
        },
    }


def daily_gate_manual_config() -> dict[str, Any]:
    """Feed Fay Evening — daily + gate + manual + implicit_daily."""
    return {
        "id": "feed_fay_evening",
        "name": "Feed Fay Evening",
        "icon": "mdi:dog-bowl",
        "trigger": {
            "type": "daily",
            "time": "18:00",
            "gate": {
                "entity_id": "binary_sensor.some_activity_sensor",
                "state": "on",
            },
        },
        "completion": {
            "type": "manual",
        },
    }


def daily_presence_config() -> dict[str, Any]:
    """Walk Fay Morning — daily + presence_cycle (binary_sensor) + implicit_daily."""
    return {
        "id": "walk_fay_morning",
        "name": "Walk Fay Morning",
        "icon": "mdi:dog-side",
        "trigger": {
            "type": "daily",
            "time": "06:00",
            "sensor": {
                "name": "Morning Walk Schedule",
            },
        },
        "completion": {
            "type": "presence_cycle",
            "entity_id": "binary_sensor.potty_holder_fay",
        },
    }


def daily_presence_afternoon_config() -> dict[str, Any]:
    """Walk Fay Afternoon — daily + presence_cycle + implicit_daily."""
    return {
        "id": "walk_fay_afternoon",
        "name": "Walk Fay Afternoon",
        "icon": "mdi:dog-side",
        "trigger": {
            "type": "daily",
            "time": "17:30",
        },
        "completion": {
            "type": "presence_cycle",
            "entity_id": "binary_sensor.potty_holder_fay",
        },
    }


def weekly_gate_manual_config() -> dict[str, Any]:
    """Weekly Clean — weekly + gate + manual + implicit_weekly."""
    return {
        "id": "weekly_clean",
        "name": "Weekly Clean",
        "description": "Vacuum all rooms and mop the kitchen floor",
        "context": "Focus on high-traffic areas",
        "icon": "mdi:broom",
        "trigger": {
            "type": "weekly",
            "schedule": [
                {"day": "wed", "time": "17:00"},
                {"day": "fri", "time": "18:00"},
            ],
            "gate": {
                "entity_id": "binary_sensor.bedroom_door_contact",
                "state": "on",
            },
        },
        "completion": {
            "type": "manual",
        },
    }


def duration_contact_cycle_config() -> dict[str, Any]:
    """Collect Clothes Rack — duration + contact_cycle + implicit_event."""
    return {
        "id": "collect_clothes_rack",
        "name": "Collect Clothes Rack",
        "icon": "mdi:hanger",
        "trigger": {
            "type": "duration",
            "entity_id": "binary_sensor.clothes_rack_contact",
            "state": "on",
            "duration_hours": 48,
            "sensor": {
                "name": "Rack Timer",
            },
        },
        "completion": {
            "type": "contact_cycle",
            "entity_id": "binary_sensor.clothes_rack_contact",
        },
    }


def state_change_presence_config() -> dict[str, Any]:
    """Take Bins Out — state_change + presence_cycle (person) + implicit_event."""
    return {
        "id": "take_bins_out",
        "name": "Take Bins Out",
        "icon": "mdi:delete",
        "trigger": {
            "type": "state_change",
            "entity_id": "input_boolean.bin_day",
            "from": "off",
            "to": "on",
        },
        "completion": {
            "type": "presence_cycle",
            "entity_id": "person.diogo",
        },
    }


def daily_sensor_threshold_config() -> dict[str, Any]:
    """Open Window — daily trigger + sensor_threshold completion + implicit_daily reset."""
    return {
        "id": "open_window_humidity",
        "name": "Open Window",
        "icon": "mdi:window-open",
        "trigger": {
            "type": "daily",
            "time": "08:00",
        },
        "completion": {
            "type": "sensor_threshold",
            "entity_id": "sensor.bathroom_humidity",
            "threshold": 60,
            "operator": "below",
        },
    }


ALL_EXAMPLE_CONFIGS = [
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
]
