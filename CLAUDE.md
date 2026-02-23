# CLAUDE.md — Home Assistant Chores Integration

## Overview

This is a Home Assistant custom integration (`chores`) for tracking household chores. It monitors real-world trigger conditions (appliance power cycles, daily schedules, entity state changes), detects automatic completion events, and manages a per-chore state machine that drives HA entities and events.

- **Integration domain:** `chores`
- **Version:** 3.0.0 (manifest), config flow version 2, store version 2
- **HACS minimum HA:** 2024.1.0
- **Configuration method:** YAML only (no UI config flow setup; the config flow only handles the YAML import)

---

## Repository Layout

```
home-assistant-chores/
├── .github/workflows/tests.yml           # GitHub Actions CI — runs on push/PR to main
├── ARCHITECTURE.md                        # Detailed internal architecture docs
├── CLAUDE.md                              # This file
├── docs/configuration.md                  # Full YAML configuration reference
├── example_configuration.yaml            # Reference YAML config showing all trigger/completion types
├── hacs.json                              # HACS metadata
├── pytest.ini                             # Pytest config (testpaths, asyncio_mode)
├── requirements_test.txt                  # Test dependencies
├── tests/
│   ├── conftest.py            # HA module stubs, MockHass, 10 config builders
│   ├── test_binary_sensor.py  # NeedsAttentionBinarySensor tests
│   ├── test_button.py         # Force action button tests
│   ├── test_chore_core.py     # Chore state machine tests
│   ├── test_completions.py    # All 6 completion detector tests via CompletionStage
│   ├── test_const.py          # Enum and constant smoke tests
│   ├── test_coordinator.py    # ChoresCoordinator tests
│   ├── test_example_configs.py # Full lifecycle tests for all 10 example configs
│   ├── test_listener_lifecycle.py # Listener setup/teardown lifecycle tests
│   ├── test_logbook.py        # Logbook describe function tests
│   ├── test_resets.py         # All 5 reset type tests + factory
│   ├── test_schemas.py        # YAML voluptuous schema validation tests
│   ├── test_sensor.py         # All 5 sensor entity tests + DetectorProgressSensor base
│   ├── test_store.py          # ChoreStore persistence tests
│   └── test_triggers.py       # All 5 trigger detector tests via TriggerStage
└── custom_components/
    └── chores/
        ├── __init__.py        # Integration setup, YAML schema, service registration
        ├── chore.py           # Backwards-compat re-export of Chore class
        ├── chore_core.py      # Chore state machine orchestrator (the core class)
        ├── completions.py     # CompletionStage wrapper (detector + enable/disable + gate)
        ├── config_flow.py     # Config flow (YAML import only)
        ├── const.py           # Enums, constants, event names, attribute names
        ├── coordinator.py     # DataUpdateCoordinator — holds all chores, polls, fires events
        ├── detectors/         # Generic stage-agnostic detector package
        │   ├── __init__.py    # DETECTOR_REGISTRY, create_detector() factory
        │   ├── base.py        # BaseDetector ABC
        │   ├── helpers.py     # Shared constants (WEEKDAY_MAP, WEEKDAY_SHORT_NAMES)
        │   ├── power_cycle.py # PowerCycleDetector
        │   ├── state_change.py # StateChangeDetector
        │   ├── daily.py       # DailyDetector
        │   ├── weekly.py      # WeeklyDetector
        │   ├── duration.py    # DurationDetector
        │   ├── manual.py      # ManualDetector
        │   ├── sensor_state.py # SensorStateDetector
        │   ├── contact.py     # ContactDetector
        │   ├── contact_cycle.py # ContactCycleDetector
        │   ├── presence_cycle.py # PresenceCycleDetector
        │   └── sensor_threshold.py # SensorThresholdDetector
        ├── diagnostics.py     # HA diagnostics support
        ├── gate.py            # Reusable gate logic (entity + state condition)
        ├── icon.svg           # Integration icon
        ├── manifest.json      # Integration manifest
        ├── resets.py          # Reset type implementations + factory
        ├── sensor.py          # Sensor entity classes + DETECTOR_SENSOR_DEFAULTS registry
        ├── binary_sensor.py   # Binary sensor entity (needs-attention)
        ├── button.py          # Button entities (force due/inactive/complete)
        ├── services.yaml      # Service descriptions for UI
        ├── store.py           # Persistent state store (HA .storage/chores)
        ├── strings.json       # Translations / entity strings
        ├── triggers.py        # TriggerStage wrapper (detector + gate)
        └── logbook.py         # Logbook platform — data-driven message registries
```

---

## Core Concepts

### State Machine

Each chore runs a single unified state machine defined in `ChoreState` (`const.py`):

```
INACTIVE → PENDING → DUE → STARTED → COMPLETED → INACTIVE
```

| State | Meaning |
|---|---|
| `inactive` | No action needed; waiting for next trigger. |
| `pending` | Trigger partially satisfied (e.g. daily time reached but gate not yet met). |
| `due` | Chore must be done now. |
| `started` | Multi-step completion in progress (step 1 done, waiting for step 2). |
| `completed` | Done for this cycle; waiting for reset to return to inactive. |

### Sub-States

Trigger and completion components use an independent sub-state (`SubState` in `const.py`):

```
idle → active → done
```

The `Chore.evaluate()` method maps trigger/completion sub-states to chore state transitions.

### Three-Component Architecture

Each `Chore` instance (in `chore_core.py`) is composed of three pluggable components:

1. **Trigger** (`triggers.py`) — detects *when* the chore becomes due.
2. **Completion** (`completions.py`) — detects *when* the chore has been done.
3. **Reset** (`resets.py`) — decides *when* the chore goes back to `inactive` after completion.

Each component follows a consistent pattern: abstract base class, concrete implementations, factory function.

---

## Module-by-Module Reference

### `const.py`
Defines all shared constants, enums, and event/attribute names. Always import constants from here rather than using string literals.

Key enums:
- `ChoreState` — the 5-state chore lifecycle.
- `SubState` — the 3-state sub-state for triggers and completions.
- `DetectorType` — unified namespace for all 11 detection patterns (used by detectors).
- `TriggerType` — 10 values: the 5 trigger-primary types + 5 cross-stage types from completions.
- `CompletionType` — 9 values: the 6 completion-primary types + 3 cross-stage types from triggers.
- `ResetType` — `delay`, `daily_reset`, `implicit_daily`, `implicit_weekly`, `implicit_event`.

Key constants:
- `DOMAIN = "chores"`
- `PLATFORMS = ["binary_sensor", "sensor", "button"]`
- `CONF_LOGBOOK = "logbook"` — integration-level YAML key to enable/disable all logbook entries (default `true`)
- `DEFAULT_ICON`, `DEFAULT_COOLDOWN_MINUTES`, `DEFAULT_POWER_THRESHOLD`, `DEFAULT_CURRENT_THRESHOLD`

Events fired:
- `chores.chore_pending`, `chores.chore_due`, `chores.chore_started`, `chores.chore_completed`, `chores.chore_reset`

Services:
- `chores.force_due`, `chores.force_inactive`, `chores.force_complete`

---

### `detectors/` package
Generic, stage-agnostic detection logic. Each detector monitors HA entities or the clock and transitions through `idle → active → done`. Detectors contain pure detection logic with no knowledge of enable/disable gating or gate conditions.

| Detector | Class | Steps | Behaviour |
|---|---|---|---|
| `power_cycle` | `PowerCycleDetector` | 1 | Active when power/current above threshold; done after cooldown once power drops. |
| `state_change` | `StateChangeDetector` | 1 | Active when entity is in `from` state; done when it transitions to `to` state. |
| `daily` | `DailyDetector` | 1 | Done at configured time daily. Trigger-only. |
| `weekly` | `WeeklyDetector` | 1 | Like daily but fires on specific weekdays at per-day times. Trigger-only. |
| `duration` | `DurationDetector` | 1 | Active when entity enters target state; done after `duration_hours`. Timer survives restarts. |
| `manual` | `ManualDetector` | 1 | No sensor; completed only via `force_complete`. Completion-only. |
| `sensor_state` | `SensorStateDetector` | 1 | Done when watched entity enters `target_state`. |
| `contact` | `ContactDetector` | 1 | Done when contact sensor goes `on`. |
| `contact_cycle` | `ContactCycleDetector` | 2 | Active on `on` (step 1); done on `off` (step 2). |
| `presence_cycle` | `PresenceCycleDetector` | 2 | Active when person leaves; done when they return. Auto-detects entity domain. |
| `sensor_threshold` | `SensorThresholdDetector` | 1 | Done when numeric sensor value crosses threshold (above/below/equal). |

`DETECTOR_REGISTRY` maps `DetectorType` to classes. `create_detector(config)` is the factory function.

### `triggers.py`
`TriggerStage` wraps a detector with optional gate holding. When the detector fires DONE but the gate isn't met, the stage reports ACTIVE (pending) instead. Uses `create_trigger(config)` factory.

`BaseTrigger = TriggerStage` is a backwards-compat alias.

### `completions.py`
`CompletionStage` wraps a detector with enable/disable gating, steps tracking, and optional gate holding. Completions only fire when `_enabled = True`. Uses `create_completion(config)` factory.

`BaseCompletion = CompletionStage` is a backwards-compat alias.

### `gate.py`
Reusable gate logic extracted from the old trigger classes. Checks if a gate entity is in the expected state, registers state change listeners, and provides extra attributes.

**Adding a new detector:**
1. Add `DetectorType.MY_TYPE` to `const.py`. Also add to `TriggerType` and/or `CompletionType` as appropriate.
2. Create `detectors/my_type.py`, subclass `BaseDetector`, set `detector_type` and `steps_total`.
3. Implement all abstract methods: `_reset_internal`, `async_setup_listeners`, `extra_attributes`, `_snapshot_internal`, `_restore_internal`.
4. Override `evaluate(hass)` if needed for polling, `check_immediate()` for enable-time checks.
5. Register in `DETECTOR_REGISTRY` in `detectors/__init__.py`.
6. Add schema branch(es) to `TRIGGER_SCHEMA` and/or `COMPLETION_SCHEMA` in `__init__.py`.
7. Add entry to `DETECTOR_SENSOR_DEFAULTS` in `sensor.py`.
8. Add message entries to logbook registries in `logbook.py`.

---

### `resets.py`
Reset types determine *when* a completed chore returns to `inactive`.

| Reset type | Class | Behaviour |
|---|---|---|
| `delay` | `DelayReset` | Resets after N minutes (0 = immediate). |
| `daily_reset` | `DailyReset` | Resets at a specific clock time each day. |
| `implicit_daily` | `ImplicitDailyReset` | Resets at the next occurrence of the daily trigger time (default for `daily` triggers). |
| `implicit_weekly` | `ImplicitWeeklyReset` | Resets at the next occurrence of the weekly trigger schedule (default for `weekly` triggers). |
| `implicit_event` | `ImplicitEventReset` | Resets immediately (default for `power_cycle`, `state_change`, and `duration` triggers). |

If no `reset` block is provided in YAML, `create_reset()` picks a sensible default based on the trigger type.

---

### `chore_core.py`
The `Chore` class is the state machine orchestrator. It:
- Instantiates trigger, completion, and reset via their respective factories.
- Runs `evaluate(hass)` on every coordinator poll (60 s) and when listeners fire.
- Exposes `force_due()`, `force_inactive()`, `force_complete()` for manual overrides.
- Provides `to_state_dict(hass)` for entities to read.
- Provides `snapshot_state()` / `restore_state()` for persistence across restarts.
- Keeps an in-memory completion history (last 100 records).

`chore.py` is a thin backwards-compat re-export of `Chore`; the canonical implementation is in `chore_core.py`.

---

### `coordinator.py`
`ChoresCoordinator` extends `DataUpdateCoordinator`:
- Holds all `Chore` instances in `_chores: dict[str, Chore]`.
- Polls every **60 seconds** via `_async_update_data`, calling `chore.evaluate()` and saving state.
- Registers state-change listeners for all chores via `setup_listeners()`.
- Fires HA bus events on every state transition via `_fire_event()`.
- Persists state in-memory on each transition (`_persist_chore`) and flushes to disk on every poll.
- Exposes `async_force_due/inactive/complete(chore_id)` for services and buttons.

`STATE_EVENT_MAP` maps each `ChoreState` to the corresponding event name.

---

### `store.py`
`ChoreStore` wraps HA's `Store` helper:
- Storage key: `chores`, version 2, file: `.storage/chores`.
- In-memory dict `{"chores": {chore_id: snapshot_dict, ...}}`.
- `get_chore_state(id)` / `set_chore_state(id, data)` for per-chore access.
- `async_save()` flushes to disk (called by coordinator every poll).
- State is restored via `coordinator.register_chore()` → `chore.restore_state()`.

---

### `__init__.py`
Integration entry point:
- Defines YAML voluptuous schemas: `GATE_SCHEMA`, `SENSOR_DISPLAY_SCHEMA`, `TRIGGER_SCHEMA`, `COMPLETION_SCHEMA`, `RESET_SCHEMA`, `CHORE_SCHEMA`, `CONFIG_SCHEMA`.
- `async_setup`: reads YAML config, stores it in `hass.data[DOMAIN]["yaml_config"]`, creates/reloads the config entry.
- `async_setup_entry`: creates `ChoreStore`, `ChoresCoordinator`, builds `Chore` instances, registers devices, sets up platforms, resolves completion buttons, sets up listeners, performs first refresh, registers services.
- `async_unload_entry`: removes listeners, unloads platforms, removes services when no entries remain.
- `_async_setup_services` / `_async_remove_services`: register/remove the three global services.

---

### `logbook.py`
Logbook platform automatically discovered by HA's logbook integration. Uses **data-driven message registries** (dicts) instead of if/elif chains.

- `_PENDING_MESSAGES`, `_DUE_MESSAGES` — keyed by trigger type string.
- `_STARTED_MESSAGES`, `_COMPLETED_MESSAGES` — keyed by completion type string.
- `async_describe_events(hass, async_describe_event)` — registers a single describe callback for all five `chores.*` events.
- The callback looks up the chore from `hass.data` to access `trigger_type` and `completion_type` for dict lookups.
- Entity linkage is resolved at runtime from the entity registry using the unique ID `chores_{chore_id}`.
- Returns `None` (suppressing the entry) when the integration has `logbook: false` in YAML.

**Invariant:** whenever a new detector type is added, add entries to the appropriate message dicts in `logbook.py`.

---

### Platform Modules

#### `sensor.py`
Creates sensor entities per chore. Uses `DETECTOR_SENSOR_DEFAULTS` registry for default icons.

| Entity | Class | Unique ID suffix | Default name | Notes |
|---|---|---|---|---|
| Main state | `ChoreStateSensor` | `{domain}_{chore_id}` | `"Chore"` | `ENUM` device class; entity services. |
| Trigger progress | `TriggerProgressSensor` | `_{chore_id}_trigger` | `"Trigger Detector"` | Inherits `DetectorProgressSensor`. |
| Completion progress | `CompletionProgressSensor` | `_{chore_id}_completion` | `"Completion Detector"` | Inherits `DetectorProgressSensor`. Skipped for `manual`. |
| Reset progress | `ResetProgressSensor` | `_{chore_id}_reset` | `"Reset Detector"` | Shows `idle/waiting` with `next_reset_at`. |
| Last completed | `LastCompletedSensor` | `_{chore_id}_last_completed` | `"Last Completed"` | Diagnostic timestamp. |

`DetectorProgressSensor` is the shared base class for trigger and completion progress sensors. Default names are always `"Trigger Detector"` or `"Completion Detector"` (from fallback defaults), overridable by the YAML `sensor: { name: "..." }` block. The `DETECTOR_SENSOR_DEFAULTS` registry provides per-detector-type **icons only**.

**`DETECTOR_SENSOR_DEFAULTS` icon registry** (icons overridden by `sensor:` block in YAML):

| Detector type | idle icon | active icon | done icon |
|---|---|---|---|
| `power_cycle` | `mdi:power-plug-off` | `mdi:power-plug` | `mdi:power-plug-outline` |
| `state_change` | `mdi:toggle-switch-off-outline` | `mdi:toggle-switch` | `mdi:check-circle-outline` |
| `daily` | `mdi:calendar-clock` | `mdi:calendar-alert` | `mdi:calendar-check` |
| `weekly` | `mdi:calendar-week` | `mdi:calendar-alert` | `mdi:calendar-check` |
| `duration` | `mdi:timer-off-outline` | `mdi:timer-sand` | `mdi:timer-check-outline` |
| `contact` | `mdi:door-closed` | `mdi:door-open` | `mdi:check-circle` |
| `contact_cycle` | `mdi:door-closed` | `mdi:door-open` | `mdi:door-closed-lock` |
| `presence_cycle` | `mdi:home` | `mdi:home-export-outline` | `mdi:home-import-outline` |
| `sensor_state` | `mdi:eye-off-outline` | `mdi:eye` | `mdi:check-circle` |
| `sensor_threshold` | `mdi:gauge-empty` | `mdi:gauge` | `mdi:gauge-full` |

#### `binary_sensor.py`
One `NeedsAttentionBinarySensor` per chore (`PROBLEM` device class):
- `ON` when chore state is `due` or `started`.

#### `button.py`
Three buttons per chore:
- `ForceDueButton` — `{domain}_{chore_id}_force_due`
- `ForceInactiveButton` — `{domain}_{chore_id}_force_inactive`
- `ForceCompleteButton` — `{domain}_{chore_id}_force_complete`

#### `config_flow.py`
YAML-import-only config flow. Creates a single entry with unique ID `chores`. No user-facing UI steps.

---

## YAML Configuration

Add to `configuration.yaml`:

```yaml
chores:
  logbook: true              # Optional. Set false to disable all logbook entries (default: true).

  chores:
    - id: my_chore           # Required. Used as entity/device identifier.
      name: "My Chore"       # Required. Human-readable name.
      icon: mdi:broom        # Optional. Default: mdi:checkbox-marked-circle-outline
      # Per-state icons (optional):
      icon_inactive: mdi:...
      icon_pending: mdi:...
      icon_due: mdi:...
      icon_started: mdi:...
      icon_completed: mdi:...

      trigger:               # Required. See trigger types below.
        type: daily
        time: "08:00"

      completion:            # Optional. Default: manual.
        type: manual

      reset:                 # Optional. Smart defaults based on trigger type.
        type: delay
        minutes: 0

      state_labels:          # Optional. Custom display labels per state.
        inactive: "All good"
        due: "Needs doing"
        completed: "Done!"
```

### Trigger Types

```yaml
# Power cycle (washing machine, dishwasher, etc.)
trigger:
  type: power_cycle
  power_sensor: sensor.plug_power      # Optional
  current_sensor: sensor.plug_current  # Optional (at least one required)
  power_threshold: 10.0                # Default: 10.0 W
  current_threshold: 0.04              # Default: 0.04 A
  cooldown_minutes: 5                  # Default: 5
  sensor:                              # Optional trigger progress sensor
    name: "Washing Machine"
    icon_idle: mdi:washing-machine-off
    icon_active: mdi:washing-machine
    icon_done: mdi:washing-machine-alert

# Entity state change
trigger:
  type: state_change
  entity_id: input_boolean.bin_day
  from: "off"
  to: "on"

# Daily time (with optional gate)
trigger:
  type: daily
  time: "08:00"
  gate:                                # Optional: stay pending until gate is met
    entity_id: binary_sensor.bedroom_door_contact
    state: "on"

# Duration (fires after entity stays in target state for N hours)
trigger:
  type: duration
  entity_id: binary_sensor.clothes_rack_contact
  state: "on"                          # Default: "on"
  duration_hours: 48                   # Required (positive, float allowed)
```

### Completion Types

```yaml
# Manual only (use Force Complete button/service)
completion:
  type: manual

# Sensor state
completion:
  type: sensor_state
  entity_id: sensor.some_sensor
  state: "on"    # Default: "on"

# Contact (single open event)
completion:
  type: contact
  entity_id: binary_sensor.door_contact

# Contact cycle (open then close — two-step)
completion:
  type: contact_cycle
  entity_id: binary_sensor.door_contact

# Presence cycle (leave then return — two-step)
# Supports person.*, device_tracker.*, or binary_sensor.*
completion:
  type: presence_cycle
  entity_id: person.alice
```

### Reset Types

```yaml
# Immediate (default for power_cycle / state_change / duration triggers)
reset:
  type: delay
  minutes: 0

# Fixed delay
reset:
  type: delay
  minutes: 30

# Daily reset at a specific time
reset:
  type: daily_reset
  time: "05:00"
```

---

## Services

Three global services (all require `chore_id`):

| Service | Description |
|---|---|
| `chores.force_due` | Force chore to `due` from any state. |
| `chores.force_inactive` | Force chore to `inactive` from any state. |
| `chores.force_complete` | Force chore to `completed` from any state. |

The same three actions are also available as entity services on `ChoreStateSensor` entities and as press-actions on the button entities.

---

## Events

All events share common data fields: `chore_id`, `chore_name`, `previous_state`, `new_state`.

| Event | Fires when |
|---|---|
| `chores.chore_pending` | Chore enters `pending` state. |
| `chores.chore_due` | Chore enters `due` state. |
| `chores.chore_started` | Chore enters `started` state (step 1 of 2-step completion). |
| `chores.chore_completed` | Chore enters `completed` state. |
| `chores.chore_reset` | Chore returns to `inactive` state. |

---

## Persistence

State survives HA restarts through two mechanisms:

1. **`ChoreStore`** — persists full chore snapshots to `.storage/chores`. Includes trigger state, completion state, completion history, and timestamps. Loaded at startup before listeners are set up.
2. **In-memory completion history** — kept on each `Chore` instance (last 100 records). Snapshotted into the store on every coordinator save.

Fields that are **not** persisted (recalculated at runtime):
- Listener subscriptions.
- `_machine_running` for `PowerCycleDetector` (re-evaluated on next state change).

---

## Development Conventions

### Code Style
- All async HA-facing code uses `async def` with `await`.
- Callbacks registered with HA event helpers use `@callback` decorator.
- Internal listener cleanup: always `self._listeners.append(unsub)` and use `async_remove_listeners()`.
- Constants and attribute names are defined in `const.py` as `Final` strings — never use raw string literals.
- Module-level logger: `_LOGGER = logging.getLogger(__name__)`.
- Use `from __future__ import annotations` in every module.
- Use `homeassistant.util.dt` (`dt_util`) for all datetime operations — never use `datetime.now()` directly.

### Extending the Integration

**Adding a new detector type:**
1. Add `DetectorType.MY_TYPE` to `const.py`. Also add to `TriggerType` and/or `CompletionType`.
2. Create `detectors/my_type.py`, subclass `BaseDetector`.
3. Register in `DETECTOR_REGISTRY` in `detectors/__init__.py`.
4. Add schema branch(es) to `TRIGGER_SCHEMA` and/or `COMPLETION_SCHEMA` in `__init__.py`.
5. Add entry to `DETECTOR_SENSOR_DEFAULTS` in `sensor.py`.
6. Add message entries to logbook registries (`_PENDING_MESSAGES`, `_DUE_MESSAGES`, `_STARTED_MESSAGES`, `_COMPLETED_MESSAGES`) in `logbook.py`.
7. Add tests: unit tests in `test_triggers.py`/`test_completions.py`, describe tests in `test_logbook.py`, sensor defaults in `test_sensor.py`, enum count in `test_const.py`, schema validation in `test_schemas.py`.
8. Add a config builder to `conftest.py` and a lifecycle test to `test_example_configs.py`.

**Adding a new reset type:**
1. Add value to `ResetType` in `const.py`.
2. Create a class extending `BaseReset` in `resets.py`.
3. Register in `create_reset()` factory.
4. Add a schema branch to `RESET_SCHEMA` in `__init__.py`.
5. Add tests: unit tests in `test_resets.py`, enum count in `test_const.py`, schema validation in `test_schemas.py`.

**Adding new persistent state fields:**
- Either add them to the detector's `_snapshot_internal()` / `_restore_internal()` methods, or store them in the store directly.

### Critical Invariants to Preserve
- **State machine semantics** — `INACTIVE`, `PENDING`, `DUE`, `STARTED`, `COMPLETED` are used by binary sensors, events, and entities. Do not redefine their meaning.
- **Listener cleanup** — every `async_track_*` call must have a corresponding unsubscribe stored in `self._listeners`.
- **Completion enable/disable** — completions only fire when `_enabled = True`. The `Chore` class manages this. Do not bypass it.
- **Detector registry sync** — if you add a detector type, keep `DETECTOR_REGISTRY`, `DetectorType` enum, `TriggerType`/`CompletionType` enums, YAML schemas, `DETECTOR_SENSOR_DEFAULTS`, and logbook message dicts all in sync.
- **Single coordinator per entry** — `hass.data[DOMAIN][entry.entry_id]["coordinator"]` is the canonical access point.
- **Polling interval** — the coordinator polls every 60 seconds (`UPDATE_INTERVAL` in `coordinator.py`). Do not tighten this for time-sensitive checks; use event listeners instead.
- **Logbook coverage** — when adding a new detector type, always add entries to the message dicts in `logbook.py`. The `logbook_enabled` and `forced` flags must always be included in event data via `coordinator._fire_event`.

---

## Device and Entity Naming

Devices are registered per chore with:
- `identifiers`: `{("chores", chore_id)}`
- `name`: `chore.name`
- `model`: `chore.trigger_type` (formatted as title case)

### Unique ID convention

Unique IDs are stable internal identifiers (never change, survive renames). All follow `chores_{chore_id}[_suffix]`:

| Entity | Unique ID |
|---|---|
| Main state sensor | `chores_{chore_id}` |
| Trigger progress sensor | `chores_{chore_id}_trigger` |
| Completion progress sensor | `chores_{chore_id}_completion` |
| Reset progress sensor | `chores_{chore_id}_reset` |
| Last completed diagnostic | `chores_{chore_id}_last_completed` |
| Force due button | `chores_{chore_id}_force_due` |
| Force inactive button | `chores_{chore_id}_force_inactive` |
| Force complete button | `chores_{chore_id}_force_complete` |
| Needs attention binary sensor | `chores_{chore_id}_needs_attention` |

**Rule:** if you add a new entity for a chore, append a `_snake_case_suffix` to `chores_{chore_id}`. If you add an integration-level entity (not per-chore), use `chores_{descriptor}`.

### Display name convention

The `_attr_has_entity_name = True` pattern is used on all entity classes — HA concatenates the **device name** (chore name) with the **entity name** for display. Entity names are role-focused and never repeat the chore name:

| Entity name | Displayed as (chore "Take Vitamins") | Entity ID |
|---|---|---|
| `"Chore"` (main sensor) | "Take Vitamins Chore" | `sensor.take_vitamins_chore` |
| `"Trigger Detector"` (trigger) | "Take Vitamins Trigger Detector" | `sensor.take_vitamins_trigger_detector` |
| `"Completion Detector"` (completion) | "Take Vitamins Completion Detector" | `sensor.take_vitamins_completion_detector` |
| `"Reset Detector"` (reset) | "Take Vitamins Reset Detector" | `sensor.take_vitamins_reset_detector` |
| `"Last Completed"` (diagnostic) | "Take Vitamins Last Completed" | `sensor.take_vitamins_last_completed` |
| `"Needs Attention"` (binary) | "Take Vitamins Needs Attention" | `binary_sensor.take_vitamins_needs_attention` |
| `"Force Due"` (button) | "Take Vitamins Force Due" | `button.take_vitamins_force_due` |
| `"Force Inactive"` (button) | "Take Vitamins Force Inactive" | `button.take_vitamins_force_inactive` |
| `"Force Complete"` (button) | "Take Vitamins Force Complete" | `button.take_vitamins_force_complete` |

Trigger and completion sensor names can be overridden via the YAML `sensor: { name: "..." }` block.

---

## Testing

### Running Tests

```bash
pytest tests/ -v --tb=short
```

All 472 tests should pass. Tests run on every push and PR to `main` via GitHub Actions (`.github/workflows/tests.yml`).

### CI Setup

The GitHub Actions workflow runs on Python 3.11 and 3.12. It installs `homeassistant` with `--no-deps` and then installs only the subset of HA runtime dependencies the test suite actually needs. Heavy dependencies (cryptography, jwt, websocket_api, auth) are stubbed out in `conftest.py` so the suite stays fast and portable.

### Test Architecture

Tests do **not** use `pytest-homeassistant-custom-component`. Instead, `tests/conftest.py` provides a lightweight stub layer:

- **Stubbed HA modules:** `config_entries`, `update_coordinator`, entity platform bases (`SensorEntity`, `BinarySensorEntity`, `ButtonEntity`), device/entity registries. These are replaced with minimal stand-ins before any `custom_components` imports.
- **Real HA modules used:** `homeassistant.core`, `homeassistant.util.dt`, `homeassistant.helpers.event`, `homeassistant.helpers.config_validation`, `homeassistant.helpers.storage`, `voluptuous`.
- **`MockHass`** — lightweight mock with `MockStates` (get/set/remove) and `MockBus` (async_fire with event collection). Used by trigger, completion, and coordinator tests.
- **9 config builder functions** — one per example configuration in `example_configuration.yaml`. These return fresh `dict` configs that match the validated YAML schemas.
- **`freezegun`** — used for time-dependent tests (cooldowns, daily/weekly triggers, duration timers, resets).

### Test File Map

| Test file | What it covers | Key signal |
|---|---|---|
| `test_const.py` | Enums, event names, constants | Catches accidental renames or missing enum values |
| `test_triggers.py` | All 5 trigger types + factory | Sub-state transitions, cooldown timers, gate logic, snapshot/restore |
| `test_completions.py` | All 5 completion types + factory | Enable/disable, 1-step vs 2-step, entity auto-detection |
| `test_resets.py` | All 5 reset types + factory | Time arithmetic, implicit defaults per trigger type |
| `test_chore_core.py` | `Chore` state machine | All transitions, force actions, timestamps, completion history, persistence |
| `test_schemas.py` | YAML voluptuous schemas | All 9 example configs validate; invalid configs rejected |
| `test_example_configs.py` | **Full lifecycle integration** | Each of the 9 example configs exercised from INACTIVE → COMPLETED → INACTIVE |
| `test_coordinator.py` | `ChoresCoordinator` | Event firing, force actions, state persistence, logbook flags |
| `test_store.py` | `ChoreStore` | Load/save/get/set/remove round-trips |
| `test_logbook.py` | Logbook describe functions | Every trigger/completion type produces a meaningful message |
| `test_sensor.py` | All 5 sensor entities | Unique IDs, names, icons per sub-state, type-aware defaults |
| `test_binary_sensor.py` | `NeedsAttentionBinarySensor` | ON when due/started, OFF otherwise |
| `test_button.py` | 3 force action buttons | Unique IDs, `async_press` delegates to coordinator |

### Verifying a Change

After any code change, run:

```bash
pytest tests/ -v --tb=short
```

**All 472 tests must pass before committing.** If you added a new component type, trigger type, or entity, you must also add tests (see "Keeping Tests Up to Date" below).

### Keeping Tests Up to Date

When extending the integration, add tests alongside the code change. The table below shows which test files need updates for each kind of change:

| Change | Test files to update |
|---|---|
| New detector type | `test_triggers.py` and/or `test_completions.py` (detector unit tests), `test_logbook.py` (message entries), `test_sensor.py` (sensor defaults), `test_const.py` (enum counts), `test_schemas.py` (schema validation), add config builder to `conftest.py` and lifecycle test to `test_example_configs.py` |
| New reset type | `test_resets.py` (unit tests), `test_const.py` (enum count), `test_schemas.py` (schema validation) |
| New entity | Corresponding `test_sensor.py` / `test_binary_sensor.py` / `test_button.py` |
| New example config | Add config builder to `conftest.py`, add lifecycle test to `test_example_configs.py`, add schema test to `test_schemas.py` |
| State machine change | `test_chore_core.py`, `test_example_configs.py` (lifecycle tests) |
| New persistent field | `test_chore_core.py` (snapshot/restore), `test_store.py` if store format changes |
| New service/event | `test_coordinator.py`, `test_const.py` |

### Debugging

For issues not caught by tests, use a real or dev HA instance:
- Use HA's Developer Tools → Events to watch `chores.*` events.
- Use Developer Tools → States to inspect entity attributes.
- Enable debug logging with:
  ```yaml
  logger:
    logs:
      custom_components.chores: debug
  ```
- The `diagnostics.py` module provides the HA diagnostics endpoint.
