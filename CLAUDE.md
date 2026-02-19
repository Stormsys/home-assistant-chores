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
├── ARCHITECTURE.md                        # Detailed internal architecture docs
├── CLAUDE.md                              # This file
├── example_configuration.yaml            # Reference YAML config showing all trigger/completion types
├── hacs.json                              # HACS metadata
└── custom_components/
    └── chores/
        ├── __init__.py        # Integration setup, YAML schema, service registration
        ├── chore.py           # Backwards-compat re-export of Chore class
        ├── chore_core.py      # Chore state machine orchestrator (the core class)
        ├── completions.py     # Completion type implementations + factory
        ├── config_flow.py     # Config flow (YAML import only)
        ├── const.py           # Enums, constants, event names, attribute names
        ├── coordinator.py     # DataUpdateCoordinator — holds all chores, polls, fires events
        ├── diagnostics.py     # HA diagnostics support
        ├── icon.svg           # Integration icon
        ├── manifest.json      # Integration manifest
        ├── resets.py          # Reset type implementations + factory
        ├── sensor.py          # Sensor entity classes
        ├── binary_sensor.py   # Binary sensor entity (needs-attention)
        ├── button.py          # Button entities (force due/inactive/complete)
        ├── services.yaml      # Service descriptions for UI
        ├── store.py           # Persistent state store (HA .storage/chores)
        ├── strings.json       # Translations / entity strings
        ├── triggers.py        # Trigger type implementations + factory
        └── logbook.py         # Logbook platform — human-readable entries for all state events
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
- `TriggerType` — `power_cycle`, `state_change`, `daily`.
- `CompletionType` — `manual`, `sensor_state`, `contact`, `contact_cycle`, `presence_cycle`.
- `ResetType` — `delay`, `daily_reset`, `implicit_daily`, `implicit_event`.

Key constants:
- `DOMAIN = "chores"`
- `PLATFORMS = ["binary_sensor", "sensor", "button"]`
- `CONF_LOGBOOK = "logbook"` — per-chore YAML key controlling logbook entries (default `true`)
- `DEFAULT_ICON`, `DEFAULT_COOLDOWN_MINUTES`, `DEFAULT_POWER_THRESHOLD`, `DEFAULT_CURRENT_THRESHOLD`

Events fired:
- `chores.chore_pending`, `chores.chore_due`, `chores.chore_started`, `chores.chore_completed`, `chores.chore_reset`

Services:
- `chores.force_due`, `chores.force_inactive`, `chores.force_complete`

---

### `triggers.py`
Trigger types detect *when* a chore should become due.

| Trigger type | Class | Behaviour |
|---|---|---|
| `power_cycle` | `PowerCycleTrigger` | Active when power/current above threshold; done after cooldown once power drops. |
| `state_change` | `StateChangeTrigger` | Active when entity is in `from` state; done when it transitions to `to` state. |
| `daily` | `DailyTrigger` | Done at configured time daily. Optionally stays pending until a gate entity enters the expected state. |

**Adding a new trigger:**
1. Subclass `BaseTrigger`.
2. Set `trigger_type: TriggerType` class attribute.
3. Implement all abstract methods: `_reset_internal`, `async_setup_listeners`, `extra_attributes`, `_snapshot_internal`, `_restore_internal`.
4. Override `evaluate(hass)` if the trigger needs time-based polling (called every 60 s).
5. Register in `TRIGGER_FACTORY` dict at the bottom of `triggers.py`.
6. Add the new type to `TriggerType` enum in `const.py`.
7. Add a voluptuous schema branch to `TRIGGER_SCHEMA` in `__init__.py`.

All listeners must be registered via `self._listeners.append(unsub)` so they are cleaned up by `async_remove_listeners()`.

---

### `completions.py`
Completion types detect *when* a chore has been performed.

| Completion type | Class | Steps | Behaviour |
|---|---|---|---|
| `manual` | `ManualCompletion` | 1 | No sensor; completed only via `force_complete` service/button. |
| `sensor_state` | `SensorStateCompletion` | 1 | Done when watched entity enters `target_state`. |
| `contact` | `ContactCompletion` | 1 | Done when contact sensor goes `on`. |
| `contact_cycle` | `ContactCycleCompletion` | 2 | Active on `on` (step 1); done on `off` (step 2). Drives `STARTED` intermediate state. |
| `presence_cycle` | `PresenceCycleCompletion` | 2 | Active when person leaves (`not_home` / `off`); done when they return (`home` / `on`). Auto-detects entity domain. |

Completions are **disabled by default**. The `Chore` class calls `completion.enable()` when the chore enters `DUE`/`PENDING`, and `completion.reset()` when returning to `INACTIVE`.

**Adding a new completion:**
1. Subclass `BaseCompletion`.
2. Set `completion_type: CompletionType` and `steps_total: int` class attributes.
3. Implement all abstract methods.
4. Register in `COMPLETION_FACTORY` dict and `CompletionType` enum.
5. Add a voluptuous schema branch to `COMPLETION_SCHEMA` in `__init__.py`.

---

### `resets.py`
Reset types determine *when* a completed chore returns to `inactive`.

| Reset type | Class | Behaviour |
|---|---|---|
| `delay` | `DelayReset` | Resets after N minutes (0 = immediate). |
| `daily_reset` | `DailyReset` | Resets at a specific clock time each day. |
| `implicit_daily` | `ImplicitDailyReset` | Resets at the next occurrence of the daily trigger time (default for `daily` triggers). |
| `implicit_event` | `ImplicitEventReset` | Resets immediately (default for `power_cycle` and `state_change` triggers). |

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
Logbook platform automatically discovered by HA's logbook integration. Provides human-readable entries for every chore state transition event, linked to the chore's main sensor entity.

- `async_describe_events(hass, async_describe_event)` — registers a single describe callback for all five `chores.*` events.
- The callback looks up the chore from `hass.data` to access `trigger_type` and `completion_type` for context-aware messages.
- Entity linkage is resolved at runtime from the entity registry using the unique ID `chores_{chore_id}`.
- Returns `None` (suppressing the entry) when the chore has `logbook: false` in YAML — checked via the `logbook_enabled` flag included in every event's data payload.

**Invariant:** whenever a new `TriggerType` or `CompletionType` is added, a matching branch must be added to `_describe_pending`/`_describe_due` (for triggers) or `_describe_started`/`_describe_completed` (for completions) in `logbook.py` so the new type gets a meaningful message rather than falling through to the generic default.

---

### Platform Modules

#### `sensor.py`
Creates sensor entities per chore:

| Entity | Unique ID suffix | Notes |
|---|---|---|
| `ChoreStateSensor` | `{domain}_{chore_id}` | Main state machine; `ENUM` device class; exposes `to_state_dict` as attributes. Entity services: `force_due`, `force_inactive`, `force_complete`. |
| `TriggerProgressSensor` | `_{chore_id}_trigger` | Always created; shows `idle/active/done`. Default name and icons are type-aware (see below). |
| `CompletionProgressSensor` | `_{chore_id}_completion` | Always created except for `manual` completion; shows `idle/active/done`. Default name and icons are type-aware (see below). |
| `ResetProgressSensor` | `_{chore_id}_reset` | Always created; shows `idle/waiting` with `next_reset_at`. |
| `LastCompletedSensor` | `_{chore_id}_last_completed` | Diagnostic; timestamp device class; exposes `completed_by`, `completion_count_today`, `completion_count_7d`. |

**Default trigger sensor names/icons** (overridden by `sensor:` block in YAML):

| Trigger type | Default name | idle icon | active icon | done icon |
|---|---|---|---|---|
| `daily` | `Daily at HH:MM` | `mdi:calendar-clock` | `mdi:calendar-alert` | `mdi:calendar-check` |
| `power_cycle` | `Power Monitor` | `mdi:power-plug-off` | `mdi:power-plug` | `mdi:power-plug-outline` |
| `state_change` | `State Monitor` | `mdi:toggle-switch-off-outline` | `mdi:toggle-switch` | `mdi:check-circle-outline` |

**Default completion sensor names/icons** (overridden by `sensor:` block in YAML):

| Completion type | Default name | idle icon | active icon | done icon |
|---|---|---|---|---|
| `contact` | `Contact` | `mdi:door-closed` | `mdi:door-open` | `mdi:check-circle` |
| `contact_cycle` | `Contact Cycle` | `mdi:door-closed` | `mdi:door-open` | `mdi:door-closed-lock` |
| `presence_cycle` | `Presence` | `mdi:home` | `mdi:walk` | `mdi:home-account` |
| `sensor_state` | `Sensor State` | `mdi:eye-off-outline` | `mdi:eye` | `mdi:check-circle` |

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

      logbook: true          # Optional. Set false to suppress logbook entries for this chore.
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
# Immediate (default for power_cycle / state_change triggers)
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
- `_machine_running` for `PowerCycleTrigger` (re-evaluated on next state change).

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

**Adding a new trigger type:**
1. Add value to `TriggerType` in `const.py`.
2. Create a class extending `BaseTrigger` in `triggers.py`.
3. Register in `TRIGGER_FACTORY`.
4. Add a schema branch to `TRIGGER_SCHEMA` in `__init__.py`.
5. Add a `_describe_pending` and `_describe_due` branch for the new type in `logbook.py`.

**Adding a new completion type:**
1. Add value to `CompletionType` in `const.py`.
2. Create a class extending `BaseCompletion` in `completions.py`.
3. Register in `COMPLETION_FACTORY`.
4. Add a schema branch to `COMPLETION_SCHEMA` in `__init__.py`.
5. Add a `_describe_started` and `_describe_completed` branch for the new type in `logbook.py`.

**Adding a new reset type:**
1. Add value to `ResetType` in `const.py`.
2. Create a class extending `BaseReset` in `resets.py`.
3. Register in `create_reset()` factory.
4. Add a schema branch to `RESET_SCHEMA` in `__init__.py`.

**Adding new persistent state fields:**
- Either add them to the component's `_snapshot_internal()` / `_restore_internal()` methods, or store them in the store directly.

### Critical Invariants to Preserve
- **State machine semantics** — `INACTIVE`, `PENDING`, `DUE`, `STARTED`, `COMPLETED` are used by binary sensors, events, and entities. Do not redefine their meaning.
- **Listener cleanup** — every `async_track_*` call must have a corresponding unsubscribe stored in `self._listeners`.
- **Completion enable/disable** — completions only fire when `_enabled = True`. The `Chore` class manages this. Do not bypass it.
- **Factory contract** — if you add a chore component type, keep its factory and the YAML schema in sync.
- **Single coordinator per entry** — `hass.data[DOMAIN][entry.entry_id]["coordinator"]` is the canonical access point.
- **Polling interval** — the coordinator polls every 60 seconds (`UPDATE_INTERVAL` in `coordinator.py`). Do not tighten this for time-sensitive checks; use event listeners instead.
- **Logbook coverage** — when adding a new `TriggerType` or `CompletionType`, always add a matching branch in `logbook.py`. The logbook describe functions fall back to generic messages, but every type should have a specific, human-readable description. The `logbook_enabled` flag and `forced` flag must be included in all event data via `coordinator._fire_event`.

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

The `_attr_has_entity_name = True` pattern is used on all entity classes — HA concatenates the **device name** (chore name) with the **entity name** for display. Keep entity names short and role-focused, not repeating the chore name:

| Entity name | Displayed as (chore "Take Vitamins") |
|---|---|
| `"Take Vitamins"` (main sensor) | "Take Vitamins" |
| `"Daily at 06:00"` (trigger) | "Take Vitamins Daily at 06:00" |
| `"Contact Cycle"` (completion) | "Take Vitamins Contact Cycle" |
| `"Reset"` (reset sensor) | "Take Vitamins Reset" |

---

## Testing and Debugging

There is no test suite in this repository. When making changes:
- Test by loading the integration in a real or dev HA instance.
- Use HA's Developer Tools → Events to watch `chores.*` events.
- Use Developer Tools → States to inspect entity attributes.
- Enable debug logging with:
  ```yaml
  logger:
    logs:
      custom_components.chores: debug
  ```
- The `diagnostics.py` module provides the HA diagnostics endpoint.
