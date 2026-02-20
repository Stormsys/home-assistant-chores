# Configuration Reference

Chores is configured entirely in YAML. Add a `chores:` block to your `configuration.yaml`.

For a complete working example, see [`example_configuration.yaml`](../example_configuration.yaml).

---

## Chore Schema

```yaml
chores:
  logbook: true                    # optional, default: true
  chores:
    - id: unique_snake_case_id     # required, used for entity IDs
      name: "Human Readable Name"  # required, shown in UI
      icon: mdi:some-icon          # optional

      trigger:                     # required — what makes this chore due
        type: daily | power_cycle | state_change
        # ... type-specific options (see below)

      completion:                  # optional, default: manual
        type: manual | contact | contact_cycle | presence_cycle | sensor_state
        # ... type-specific options (see below)

      reset:                       # optional — smart defaults per trigger type
        type: daily_reset | delay
        # ... type-specific options (see below)

      state_labels:                # optional — custom display text per state
        inactive: "Idle"
        pending: "Waiting"
        due: "Ready"
        started: "In Progress"
        completed: "Done"

      # Per-state icons (all optional):
      icon_inactive: mdi:...
      icon_pending: mdi:...
      icon_due: mdi:...
      icon_started: mdi:...
      icon_completed: mdi:...
```

---

## Trigger Types

Triggers define what causes a chore to become due.

### `daily` — Fixed Time Each Day

The chore becomes due at a specific time every day. Optionally, a **gate** can hold the chore in `pending` until a secondary condition is met (e.g. "6am but only after I've got up").

```yaml
trigger:
  type: daily
  time: "06:00"          # required, 24-hour format HH:MM
  gate:                  # optional
    entity_id: binary_sensor.bedroom_door_contact
    state: "on"
  sensor:                # optional, customise the trigger progress sensor
    name: "Morning Alarm"
    icon_idle: mdi:clock-outline
    icon_active: mdi:clock-alert
    icon_done: mdi:bell-ring
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `time` | Yes | — | Time the chore becomes due (HH:MM, 24-hour) |
| `gate.entity_id` | No | — | Entity that must match `gate.state` before the chore fires |
| `gate.state` | No | — | Required state of the gate entity |

**Without a gate:** `inactive` -> `due` at the specified time.
**With a gate:** `inactive` -> `pending` at `time`, then -> `due` once the gate entity enters the specified state.

---

### `power_cycle` — Appliance Cycle Detection

Monitors power and/or current sensors on a smart plug. When readings drop below threshold after being above (appliance finished), the chore becomes due.

```yaml
trigger:
  type: power_cycle
  power_sensor: sensor.washing_machine_plug_power
  current_sensor: sensor.washing_machine_plug_current
  power_threshold: 10
  current_threshold: 0.04
  cooldown_minutes: 5
  sensor:
    name: "Washing Machine"
    icon_idle: mdi:washing-machine-off
    icon_active: mdi:washing-machine
    icon_done: mdi:washing-machine-alert
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `power_sensor` | No* | — | Power sensor entity |
| `current_sensor` | No* | — | Current sensor entity |
| `power_threshold` | No | `10.0` W | Below this = idle |
| `current_threshold` | No | `0.04` A | Below this = idle |
| `cooldown_minutes` | No | `5` | Wait after power drops before triggering |

*At least one of `power_sensor` or `current_sensor` is required.

Sub-states: `idle` (off) -> `active` (running) -> `done` (finished, cooldown elapsed).

---

### `state_change` — Entity State Transition

Fires when a specific entity transitions between two states.

```yaml
trigger:
  type: state_change
  entity_id: input_boolean.bin_day
  from: "off"
  to: "on"
  sensor:
    name: "Bin Day"
    icon_idle: mdi:delete-off
    icon_done: mdi:delete-alert
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `entity_id` | Yes | — | Entity to watch |
| `from` | Yes | — | State to transition from |
| `to` | Yes | — | State to transition to |

Useful for helper booleans set by other automations (e.g. a calendar automation that sets `input_boolean.bin_day` on the right night).

---

## Completion Types

Completions define how a chore is marked done once it is `due`. Completions are only active while the chore is in `due` or `pending` state.

### `manual` — Button or Service Call

No automatic detection. Complete via the **Force Complete** button, an automation, or a service call.

```yaml
completion:
  type: manual
```

---

### `sensor_state` — Sensor Matches Target

Done when a watched entity enters a target state.

```yaml
completion:
  type: sensor_state
  entity_id: sensor.some_sensor
  state: "on"    # default: "on"
```

---

### `contact` — Contact Sensor Opens

Single-step. Complete the moment a contact/binary sensor turns `on`. Good for machine doors, cupboard doors, drawers.

```yaml
completion:
  type: contact
  entity_id: binary_sensor.washing_machine_door_contact
  sensor:
    name: "Machine Door"
    icon_idle: mdi:door-closed
    icon_done: mdi:door-open
```

---

### `contact_cycle` — Open Then Close

Two-step. The chore moves to `started` when the contact opens, then to `completed` when it closes again. Confirms the person actually interacted with the thing (e.g. opened and closed a pill box).

```yaml
completion:
  type: contact_cycle
  entity_id: binary_sensor.coffee_cupboard_door_contact
  sensor:
    name: "Pill Box"
    icon_idle: mdi:door-closed
    icon_done: mdi:door-open
```

State flow: `due` -> (opens) -> `started` -> (closes) -> `completed`

---

### `presence_cycle` — Leave Then Return

Two-step using a device tracker, person, or binary sensor. The chore moves to `started` when the tracked entity leaves, then `completed` when it returns. Good for walks, errands, taking out bins.

```yaml
completion:
  type: presence_cycle
  entity_id: device_tracker.potty_bermuda_tracker
  sensor:
    name: "Dog Walk"
    icon_idle: mdi:home
    icon_active: mdi:walk
    icon_done: mdi:home-check
```

State flow: `due` -> (leaves) -> `started` -> (returns) -> `completed`

Supports `person.*`, `device_tracker.*`, and `binary_sensor.*` entities.

---

## Reset Types

Resets control when a completed chore returns to `inactive`, ready for the next cycle.

### `daily_reset` — Fixed Time Each Day

```yaml
reset:
  type: daily_reset
  time: "06:00"
```

Use when the chore should reset at the same time each day regardless of when it was completed.

### `delay` — Fixed Delay After Completion

```yaml
reset:
  type: delay
  minutes: 0     # 0 = immediate
```

**Default behaviour:** If no `reset` is specified, the integration picks a sensible default:

| Trigger type | Default reset |
|---|---|
| `daily` | Resets at the next occurrence of the trigger time |
| `power_cycle` | Resets shortly after completion |
| `state_change` | Resets shortly after completion |

---

## Sensor Display Options

Trigger and completion blocks can each include a `sensor` sub-block to customise the name and icons of their progress sensor entity:

```yaml
sensor:
  name: "Display name"
  icon_idle: mdi:some-icon        # shown when sub-state is idle
  icon_active: mdi:some-icon      # shown when sub-state is active
  icon_done: mdi:some-icon        # shown when sub-state is done
```

If omitted, sensible defaults are used based on the trigger/completion type. See the main [README](../README.md#entities-created) for the full default table.

---

## State Labels

Customise the display text for each state on a per-chore basis:

```yaml
state_labels:
  inactive: "All good"
  pending: "Waiting..."
  due: "Ready to unload"
  started: "In progress"
  completed: "Done!"
```

If omitted, the raw state names (`inactive`, `pending`, `due`, `started`, `completed`) are used.

---

## Logbook

The integration logs every state transition to Home Assistant's logbook with human-readable messages. Disable all logbook entries with:

```yaml
chores:
  logbook: false
  chores:
    # ...
```
