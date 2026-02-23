## Chores Integration Architecture

This document explains the internal architecture of the `chores` Home Assistant custom integration so you can confidently extend and refactor it.

---

## 1. High-Level Design

The integration is built on a **composition model** with three layers:

1. **Detectors** — generic, stage-agnostic detection logic (`detectors/`)
2. **Stage Wrappers** — role-specific behavior: `TriggerStage` (`triggers.py`) and `CompletionStage` (`completions.py`)
3. **Chore** — the state machine orchestrator (`chore_core.py`) that combines trigger, completion, and reset

```
Chore
 ├── TriggerStage
 │    ├── BaseDetector (e.g. DailyDetector, PowerCycleDetector)
 │    └── Gate (optional)
 ├── CompletionStage
 │    ├── BaseDetector (e.g. ContactCycleDetector, SensorStateDetector)
 │    └── Gate (optional)
 └── BaseReset (e.g. ImplicitDailyReset, DelayReset)
```

---

## 2. Detectors (`detectors/` package)

Detectors are the core detection primitives.  Each detector monitors HA entities or the clock and transitions through the `SubState` enum:

```
idle  →  active (optional)  →  done
```

**Key properties:**
- Detectors are **stage-agnostic** — they contain pure detection logic with no knowledge of enable/disable gating, steps tracking, or gate conditions.
- Each detector declares which stages it supports via `supported_stages()` (returns `frozenset[str]`).
- Most detectors support both `"trigger"` and `"completion"` stages.  Exceptions: `DailyDetector` and `WeeklyDetector` (trigger-only), `ManualDetector` (completion-only).

### Package Structure

```
detectors/
├── __init__.py          # DETECTOR_REGISTRY, create_detector() factory
├── base.py              # BaseDetector ABC
├── helpers.py           # Shared constants (WEEKDAY_MAP, WEEKDAY_SHORT_NAMES)
├── power_cycle.py       # PowerCycleDetector
├── state_change.py      # StateChangeDetector
├── daily.py             # DailyDetector
├── weekly.py            # WeeklyDetector
├── duration.py          # DurationDetector
├── manual.py            # ManualDetector
├── sensor_state.py      # SensorStateDetector
├── contact.py           # ContactDetector
├── contact_cycle.py     # ContactCycleDetector
├── presence_cycle.py    # PresenceCycleDetector
└── sensor_threshold.py  # SensorThresholdDetector
```

### BaseDetector ABC

All detectors inherit from `BaseDetector` and implement:

| Method | Purpose |
|--------|---------|
| `_reset_internal()` | Reset detector-specific tracking state |
| `async_setup_listeners(hass, on_state_change)` | Register HA event listeners |
| `extra_attributes(hass)` | Return state attributes for progress sensor |
| `_snapshot_internal()` | Return detector-specific state for persistence |
| `_restore_internal(data)` | Restore detector-specific state |

Optional overrides:
- `evaluate(hass)` — for polling-based detection (default: no-op)
- `check_immediate(hass, on_state_change)` — for enable-time checks (used by SensorThresholdDetector)

### Detector Registry

`DETECTOR_REGISTRY` in `detectors/__init__.py` maps `DetectorType` enum values to detector classes.  The `create_detector(config)` factory reads `config["type"]` and instantiates the correct class.

### Adding a New Detector

1. Create `detectors/my_detector.py`, subclass `BaseDetector`.
2. Set `detector_type = DetectorType.MY_DETECTOR` and `steps_total`.
3. Implement all abstract methods.
4. Add `DetectorType.MY_DETECTOR` to `const.py`.
5. Register in `DETECTOR_REGISTRY` in `detectors/__init__.py`.
6. Add schema branch(es) to `TRIGGER_SCHEMA` and/or `COMPLETION_SCHEMA` in `__init__.py`.
7. Add an entry to `DETECTOR_SENSOR_DEFAULTS` in `sensor.py`.
8. Add message entries to the logbook registries in `logbook.py`.
9. Add tests.

---

## 3. Stage Wrappers

### TriggerStage (`triggers.py`)

Wraps a detector with:
- **Gate holding**: when the detector fires DONE but an optional gate isn't met, the stage reports `ACTIVE` (pending) instead.
- **Polling**: delegates `evaluate()` to the detector and applies gate logic.
- **Persistence**: snapshots/restores both detector state and gate-holding flag.

```python
trigger = create_trigger({"type": "daily", "time": "08:00", "gate": {...}})
# trigger.detector → DailyDetector instance
# trigger._gate → Gate instance (or None)
```

### CompletionStage (`completions.py`)

Wraps a detector with:
- **Enable/disable gating**: completions only fire when explicitly enabled (chore is due/pending).  The `_on_detector_change` callback checks `_enabled` before propagating.
- **Steps tracking**: derives `steps_done` from detector state.
- **Gate holding**: same pattern as TriggerStage.
- **Enable-time check**: calls `detector.check_immediate()` on enable for detectors that support it (e.g. SensorThresholdDetector).

```python
comp = create_completion({"type": "contact_cycle", "entity_id": "binary_sensor.door"})
comp.enable()   # Start listening
comp.disable()  # Stop propagating events
comp.reset()    # Full reset to idle
```

### Gate (`gate.py`)

Reusable gate logic extracted from the old trigger classes:
- `is_met(hass)` — checks if the gate entity is in the expected state.
- `async_setup_listener(hass, on_gate_change)` — registers a state change listener.
- `async_remove_listeners()` — cleans up.
- `extra_attributes(hass)` — returns gate entity state info.

---

## 4. Chore State Machine (`chore_core.py`)

Each `Chore` runs a unified state machine:

```
INACTIVE → PENDING → DUE → STARTED → COMPLETED → INACTIVE
```

| State | Meaning |
|-------|---------|
| `inactive` | Waiting for next trigger |
| `pending` | Trigger partially satisfied (e.g. time reached but gate not met) |
| `due` | Chore must be done now |
| `started` | Multi-step completion in progress (step 1 done) |
| `completed` | Done; waiting for reset |

The `evaluate(hass)` method maps trigger/completion sub-states to chore state transitions:

| Trigger State | Completion State | Chore State |
|---------------|------------------|-------------|
| `active` | — | `PENDING` |
| `done` | `idle` | `DUE` |
| `done` | `active` | `STARTED` |
| `done` | `done` | `COMPLETED` |

Force actions (`force_due`, `force_inactive`, `force_complete`) bypass the normal state machine for manual overrides.

---

## 5. Coordinator (`coordinator.py`)

`ChoresCoordinator` extends `DataUpdateCoordinator`:

- **Polling**: every 60 seconds, calls `chore.evaluate()` for all chores.
- **Listeners**: `setup_listeners()` delegates to each chore's `async_setup_listeners()`.
- **Events**: fires HA bus events on every state transition (`STATE_EVENT_MAP`).
- **Persistence**: saves state via `ChoreStore` on every poll and state change.
- **Services**: exposes `async_force_due/inactive/complete(chore_id)`.

---

## 6. Entities

### Sensor Entities (`sensor.py`)

Uses a **registry-based approach** for default names and icons via `DETECTOR_SENSOR_DEFAULTS`:

| Sensor | Purpose |
|--------|---------|
| `ChoreStateSensor` | Main state machine (`ENUM` device class) |
| `TriggerProgressSensor` | Trigger sub-state (idle/active/done) |
| `CompletionProgressSensor` | Completion sub-state (idle/active/done) |
| `ResetProgressSensor` | Reset status (idle/waiting) |
| `LastCompletedSensor` | Diagnostic timestamp |

`TriggerProgressSensor` and `CompletionProgressSensor` both inherit from `DetectorProgressSensor`, which uses the `DETECTOR_SENSOR_DEFAULTS` registry to look up default names and icons by detector type, with special handling for dynamic names (daily time formatting, weekly schedule formatting).

### Binary Sensor (`binary_sensor.py`)

`NeedsAttentionBinarySensor` — `ON` when chore state is `due` or `started`.

### Buttons (`button.py`)

Three buttons per chore: Force Due, Force Inactive, Force Complete.

---

## 7. Logbook (`logbook.py`)

Uses **data-driven message registries** instead of if/elif chains:
- `_PENDING_MESSAGES` — keyed by trigger type
- `_DUE_MESSAGES` — keyed by trigger type
- `_STARTED_MESSAGES` — keyed by completion type
- `_COMPLETED_MESSAGES` — keyed by completion type

Adding a new detector type only requires adding entries to the appropriate dicts.

---

## 8. Cross-Stage Detectors

The generic detector architecture allows most detectors to be used in either trigger or completion position:

| Detector | Trigger | Completion | Notes |
|----------|---------|------------|-------|
| `power_cycle` | Primary | Cross-stage | |
| `state_change` | Primary | Cross-stage | |
| `daily` | Primary | No | Trigger-only |
| `weekly` | Primary | No | Trigger-only |
| `duration` | Primary | Cross-stage | |
| `manual` | No | Primary | Completion-only |
| `sensor_state` | Cross-stage | Primary | |
| `contact` | Cross-stage | Primary | |
| `contact_cycle` | Cross-stage | Primary | |
| `presence_cycle` | Cross-stage | Primary | |
| `sensor_threshold` | Cross-stage | Primary | |

Both `TriggerType` and `CompletionType` enums include all cross-stage values.  The YAML schemas (`TRIGGER_SCHEMA`, `COMPLETION_SCHEMA`) accept cross-stage types with full parameter support.

---

## 9. Persistence (`store.py`)

`ChoreStore` wraps HA's `Store` helper:
- Storage key: `chores`, version 2, file: `.storage/chores`.
- In-memory dict: `{"chores": {chore_id: snapshot_dict, ...}}`.
- Snapshots include trigger, completion, and reset state, plus completion history (last 100 records).
- State restored at startup via `coordinator.register_chore()` → `chore.restore_state()`.

Fields **not** persisted (recalculated at runtime):
- Listener subscriptions
- `_machine_running` for PowerCycleDetector

---

## 10. Configuration (`__init__.py`)

### YAML Schemas

- `TRIGGER_SCHEMA` — `vol.Any(...)` with branches for all trigger-capable detector types.
- `COMPLETION_SCHEMA` — `vol.Any(...)` with branches for all completion-capable detector types.
- `GATE_SCHEMA` — shared gate definition (`entity_id` + `state`).
- `RESET_SCHEMA` — `delay` and `daily_reset`.
- `CHORE_SCHEMA` — full chore definition with trigger, completion, reset, state labels, icons.
- `CONFIG_SCHEMA` — integration-level: `logbook` flag + chores list.

### Gate Support

All trigger and completion types support an optional `gate` block.  Gates hold the stage in `ACTIVE` (pending) until the gate entity enters the specified state.

---

## 11. What to Watch Out For When Refactoring

- **Detector contract**: all detectors must implement BaseDetector's abstract methods and register in DETECTOR_REGISTRY.
- **Listener cleanup**: every `async_track_*` call must append its unsub to `self._listeners`.
- **Completion enable/disable**: completions only fire when `_enabled = True`.  The `Chore` class manages this lifecycle.
- **Gate holding invariant**: when `_gate_holding` is True, stage reports `ACTIVE` regardless of detector state.
- **Factory/schema sync**: if you add a detector type, keep `DETECTOR_REGISTRY`, enum, YAML schema, sensor defaults, and logbook entries in sync.
- **State machine semantics**: `INACTIVE`, `PENDING`, `DUE`, `STARTED`, `COMPLETED` are used by binary sensors, events, entities, and logbook.
- **Polling interval**: 60 seconds.  Use event listeners for time-sensitive detection.
