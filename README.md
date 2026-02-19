# Chores for Home Assistant

[![GitHub Release](https://img.shields.io/github/v/release/your-repo/ha-chores?style=for-the-badge)](https://github.com/your-repo/ha-chores/releases)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1.0+-blue?style=for-the-badge&logo=home-assistant)](https://www.home-assistant.io/)
[![Alpha](https://img.shields.io/badge/Status-Alpha-red?style=for-the-badge)](https://github.com/your-repo/ha-chores)

A Home Assistant custom integration for tracking household chores and recurring tasks using your existing sensors, contact sensors, and device trackers. Each chore moves through a consistent state machine — **inactive → pending → due → started → completed** — driven by real smart home events.

> **Alpha Software:** This integration is in early development. Configuration schema and entity names may change between versions. Expect rough edges.

---

## What It Does

Chores connects your smart home sensors to household tasks. Instead of manually ticking off a checklist, the integration watches your actual devices and marks chores done when the physical action is detected:

- Washing machine finishes a cycle → "Unload Washing" becomes due → opening the machine door marks it complete
- 6am arrives and the bedroom door opens → "Take Elvanse" becomes due → opening the pill cupboard marks it complete
- Dog walk time arrives → "Walk Fay" becomes due → leaving and returning home marks it complete
- A helper boolean flips on → "Take Bins Out" becomes due → leaving the house and returning marks it complete

Chores you cannot auto-detect can be completed manually via a button or Home Assistant service call.

---

## Features

- **Three trigger types:** daily schedule, power cycle detection (smart plugs), entity state change
- **Trigger gates:** hold a chore pending until a secondary condition is met (e.g. bedroom door opens before the morning reminder fires)
- **Four completion types:** manual, contact open, contact open→close cycle, presence away→home cycle
- **Per-chore reset control:** daily reset at a fixed time, delay-based reset after completion
- **Customisable state labels:** rename inactive/pending/due/started/completed per chore
- **Diagnostic sensors per chore:** trigger progress, completion progress, last completed timestamp
- **Binary sensor per chore:** goes `on` when the chore needs attention (useful for dashboards and notifications)
- **Control buttons per chore:** force due, force complete, force inactive (for testing and overrides)
- **HA event bus integration:** fires events on every state transition for use in automations
- **Services:** `complete`, `reset`, `skip`, `snooze` callable from automations or scripts
- **HACS installable**

---

## Installation

### Via HACS (Recommended)

1. Open HACS in your Home Assistant UI
2. Go to **Integrations**
3. Click the three-dot menu → **Custom repositories**
4. Add `https://github.com/your-repo/ha-chores` with category **Integration**
5. Find **Chores** in the list and click **Download**
6. Restart Home Assistant

### Manual

1. Download the latest release from [GitHub releases](https://github.com/your-repo/ha-chores/releases)
2. Copy the `custom_components/chores` directory into your `config/custom_components/` directory
3. Restart Home Assistant

---

## Configuration

Chores is configured entirely in YAML. Add the following to your `configuration.yaml`:

```yaml
chores:
  chores:
    - id: my_chore
      name: "My Chore"
      # ... see below
```

Each chore requires an `id`, a `name`, a `trigger`, and a `completion`.

---

## Chore Schema

```yaml
- id: unique_snake_case_id        # required, used for entity IDs
  name: "Human Readable Name"     # required, shown in UI
  icon: mdi:some-icon             # optional, MDI icon

  state_labels:                   # optional, customise state display text
    inactive: "Idle"
    pending: "Waiting"
    due: "Ready"
    started: "In Progress"
    completed: "Done"

  trigger:                        # required, what causes this chore to become due
    type: daily | power_cycle | state_change
    # ... type-specific options

  completion:                     # required, how the chore is marked done
    type: manual | contact | contact_cycle | presence_cycle
    # ... type-specific options

  reset:                          # optional, when the chore resets to inactive
    type: daily_reset | delay
    # ... type-specific options
```

---

## Trigger Types

Triggers define what causes a chore to become due.

### `daily` — Fixed Time Each Day

The chore becomes due at a specific time every day.

```yaml
trigger:
  type: daily
  time: "06:00"          # required, 24-hour format HH:MM
  gate:                  # optional, only fire when this entity is in the right state
    entity_id: binary_sensor.bedroom_door_contact
    state: "on"
  sensor:                # optional, name and icons for the trigger progress sensor
    name: "Morning Alarm"
    icon_idle: mdi:clock-outline
    icon_active: mdi:clock-alert
    icon_done: mdi:bell-ring
```

**With a gate:** The chore becomes `pending` at `time`, but only transitions to `due` once the gate entity enters the specified state. This is useful for "6am but only after I've got up" logic.

**Without a gate:** The chore goes directly from `inactive` to `due` at the specified time.

---

### `power_cycle` — Smart Plug / Appliance Cycle Detection

Monitors power and current sensors on a smart plug. When the power drops below the threshold after being above it (appliance finished), the chore becomes due.

```yaml
trigger:
  type: power_cycle
  power_sensor: sensor.washing_machine_plug_power       # required
  current_sensor: sensor.washing_machine_plug_current   # required
  power_threshold: 10          # watts, below this = idle (default: 10)
  current_threshold: 0.04      # amps, below this = idle (default: 0.04)
  cooldown_minutes: 5          # wait this long after power drops before triggering (default: 5)
  sensor:
    name: "Washing Machine"
    icon_idle: mdi:washing-machine-off
    icon_active: mdi:washing-machine
    icon_done: mdi:washing-machine-alert
```

The trigger tracks three sub-states (`idle` → `active` → `done`):
- `idle`: appliance is off / not running
- `active`: appliance is running (power above threshold)
- `done`: appliance has finished (power dropped, cooldown elapsed) — chore is now `due`

---

### `state_change` — Entity State Transition

Fires when a specific entity transitions between two states.

```yaml
trigger:
  type: state_change
  entity_id: input_boolean.bin_day    # required
  from: "off"                         # required
  to: "on"                            # required
  sensor:
    name: "Bin Day"
    icon_idle: mdi:delete-off
    icon_done: mdi:delete-alert
```

Useful for helper booleans set by other automations (e.g. a calendar automation that sets `input_boolean.bin_day` on the right night).

---

## Completion Types

Completions define how the chore is marked done once it is `due`.

### `manual` — Button or Service Call

No automatic detection. The chore must be completed via the **Force Complete** button, an automation, or a service call.

```yaml
completion:
  type: manual
```

---

### `contact` — Contact Sensor Opens

The chore is marked complete the moment a contact/binary sensor turns `on` (opens). A single-step completion.

```yaml
completion:
  type: contact
  entity_id: binary_sensor.washing_machine_door_contact   # required
  sensor:
    name: "Machine Door"
    icon_idle: mdi:door-closed
    icon_done: mdi:door-open
```

Suitable for: machine doors, cupboard doors, drawers — anything where opening once means the task is done.

---

### `contact_cycle` — Contact Opens Then Closes

A two-step completion. The chore moves to `started` when the contact opens, then to `completed` when it closes again. Useful when you want confirmation that the person actually interacted with the thing (e.g. opened and closed a pill box).

```yaml
completion:
  type: contact_cycle
  entity_id: binary_sensor.coffee_cupboard_door_contact   # required
  sensor:
    name: "Pill Box Used"
    icon_idle: mdi:door-closed
    icon_done: mdi:door-open
```

State flow: `due` → (contact opens) → `started` → (contact closes) → `completed`

---

### `presence_cycle` — Leave Home Then Return

A two-step completion using a device tracker. The chore moves to `started` when the tracked device leaves, then `completed` when it returns. Useful for walks, errands, and anything that requires leaving the house.

```yaml
completion:
  type: presence_cycle
  entity_id: device_tracker.potty_bermuda_tracker    # required
  sensor:
    name: "Dog Walk"
    icon_idle: mdi:home
    icon_active: mdi:walk
    icon_done: mdi:home-check
```

State flow: `due` → (device leaves) → `started` → (device returns home) → `completed`

---

## Reset Types

Resets control when a completed chore returns to `inactive` ready for the next cycle.

### `daily_reset` — Reset at a Fixed Time Each Day

```yaml
reset:
  type: daily_reset
  time: "06:00"    # reset at 6am every day
```

Use this when the chore should reset at the start of each day regardless of when it was completed.

### `delay` — Reset After a Fixed Delay

```yaml
reset:
  type: delay
  hours: 12    # reset 12 hours after completion
```

> **Default behaviour:** If no `reset` is specified, the integration applies a sensible default based on the trigger type. Daily triggers reset at the next occurrence of their trigger time. Power-cycle and state-change triggers reset shortly after completion.

---

## Trigger Gates

Any `daily` trigger can have a gate — a secondary entity condition that must be true before the chore fires:

```yaml
trigger:
  type: daily
  time: "06:00"
  gate:
    entity_id: binary_sensor.bedroom_door_contact
    state: "on"
```

Without the gate, the chore would fire at 6:00 even if the person is still asleep. With the gate, the chore waits in `pending` state from 6:00 until the bedroom door actually opens, then becomes `due`.

Gate entities can be any binary sensor, input boolean, or other entity with a readable state.

---

## State Labels

Every chore has five states. The labels shown in the UI for each state can be customised per chore:

```yaml
state_labels:
  inactive: "Idle"
  pending: "Waiting"
  due: "Ready to unload"
  started: "Running"
  completed: "Done"
```

Default labels (if omitted):

| State | Default Label |
|-------|--------------|
| `inactive` | `inactive` |
| `pending` | `pending` |
| `due` | `due` |
| `started` | `started` |
| `completed` | `completed` |

---

## Sensor Display Options

Trigger and completion entries can each include a `sensor` block to control the name and icon shown by their associated progress sensor:

```yaml
sensor:
  name: "Sensor display name"
  icon_idle: mdi:some-icon        # shown when sub-state is idle
  icon_active: mdi:some-icon      # shown when sub-state is active (mid-cycle)
  icon_done: mdi:some-icon        # shown when sub-state is done
```

---

## Entities Created Per Chore

For each chore with ID `my_chore`, the integration creates:

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.my_chore` | Sensor | Primary state: `inactive`, `pending`, `due`, `started`, `completed` |
| `sensor.my_chore_trigger` | Sensor | Trigger sub-state: `idle`, `active`, `done` |
| `sensor.my_chore_completion` | Sensor | Completion sub-state: `idle`, `active`, `done` |
| `sensor.my_chore_last_completed` | Sensor | Timestamp of last completion |
| `binary_sensor.my_chore` | Binary Sensor | `on` when the chore is due or in progress (needs attention) |
| `button.my_chore_force_due` | Button | Force chore into `due` state |
| `button.my_chore_force_complete` | Button | Force chore into `completed` state |
| `button.my_chore_force_inactive` | Button | Force chore into `inactive` state |

All entities are grouped under a single **device** per chore in the device registry.

---

## State Machine

All chores follow the same state machine:

```
INACTIVE
   │
   │  trigger fires (time / power cycle / state change)
   ▼
PENDING  ──── (if gate configured, waits here for gate condition)
   │
   │  gate condition met (or no gate)
   ▼
DUE
   │
   │  first step of completion (for multi-step completions)
   ▼
STARTED
   │
   │  completion confirmed
   ▼
COMPLETED
   │
   │  reset fires
   ▼
INACTIVE
```

For single-step completions (`manual`, `contact`), the `started` state is skipped — the chore goes directly from `due` to `completed`.

---

## Services

The following services are available:

| Service | Description |
|---------|-------------|
| `chores.complete` | Mark a chore complete by `chore_id` |
| `chores.reset` | Reset a chore to inactive by `chore_id` |
| `chores.skip` | Skip the current occurrence by `chore_id` |
| `chores.snooze` | Snooze a chore for N hours by `chore_id` |

Example automation using a service:

```yaml
automation:
  - alias: "Complete morning feed via NFC tag"
    trigger:
      - platform: tag
        tag_id: abc123
    action:
      - service: chores.complete
        data:
          chore_id: feed_fay_morning
```

Per-entity button services (`force_due`, `force_inactive`, `force_complete`) are also available on each `sensor.<chore_id>` entity.

---

## Events

The integration fires events on the Home Assistant event bus for every state transition. Use these in automations for notifications or other reactions.

| Event | Fired When |
|-------|-----------|
| `chores.chore_pending` | Chore enters pending state |
| `chores.chore_due` | Chore becomes due |
| `chores.chore_started` | Completion sequence started (multi-step) |
| `chores.chore_completed` | Chore is completed |
| `chores.chore_reset` | Chore resets to inactive |
| `chores.chore_overdue` | Chore first becomes overdue |
| `chores.chore_overdue_reminder` | Periodic overdue reminder fired |

Event data includes: `chore_id`, `chore_name`, `previous_state`, `new_state`, `timestamp`.

Example automation listening to an event:

```yaml
automation:
  - alias: "Notify when washing is ready"
    trigger:
      - platform: event
        event_type: chores.chore_due
        event_data:
          chore_id: unload_washing
    action:
      - service: notify.mobile_app_my_phone
        data:
          message: "Washing machine is done — go unload it"
```

---

## Real-World Example Configuration

This is a complete working example demonstrating all three trigger types and all four completion types:

```yaml
chores:
  chores:

    # Smart plug detects washing machine cycle end.
    # Opening the machine door marks it complete.
    - id: unload_washing
      name: "Unload Washing Machine"
      icon: mdi:washing-machine
      state_labels:
        inactive: "Idle"
        pending: "Waiting"
        due: "Ready to unload"
        started: "Running"
        completed: "Done"
      trigger:
        type: power_cycle
        power_sensor: sensor.washing_machine_plug_power
        current_sensor: sensor.washing_machine_plug_current
        power_threshold: 10
        current_threshold: 0.04
        cooldown_minutes: 5
        sensor:
          name: "Trigger: Washing Machine"
          icon_idle: mdi:washing-machine-off
          icon_active: mdi:washing-machine
          icon_done: mdi:washing-machine-alert
      completion:
        type: contact
        entity_id: binary_sensor.washing_machine_door_contact
        sensor:
          name: "Detect: Machine Door"
          icon_idle: mdi:door-closed
          icon_done: mdi:door-open

    # Due at 6am. Gate holds until bedroom door opens.
    # Opening and closing the pill cupboard marks it done.
    - id: take_elvanse
      name: "Take Elvanse"
      icon: mdi:pill
      state_labels:
        inactive: "Nothing to do"
        pending: "Waiting for you to wake up"
        due: "You need to take the pill"
        started: "Put it back please"
        completed: "Done"
      trigger:
        type: daily
        time: "06:00"
        gate:
          entity_id: binary_sensor.bedroom_door_contact
          state: "on"
        sensor:
          name: "Trigger: Morning out of bed"
          icon_idle: mdi:clock-outline
          icon_active: mdi:clock-alert
          icon_done: mdi:bell-ring
      completion:
        type: contact_cycle
        entity_id: binary_sensor.coffee_cupboard_door_contact
        sensor:
          name: "Detect: Pill Box Used"
          icon_idle: mdi:door-closed
          icon_done: mdi:door-open

    # Due at 6am. Completed manually.
    - id: feed_fay_morning
      name: "Feed Fay Morning"
      icon: mdi:dog-bowl
      trigger:
        type: daily
        time: "06:00"
      completion:
        type: manual

    # Due at 19:00 when home. Completed manually.
    - id: feed_fay_evening
      name: "Feed Fay Evening"
      icon: mdi:dog-bowl
      trigger:
        type: daily
        time: "19:00"
        gate:
          entity_id: binary_sensor.person_at_home
          state: "on"
        sensor:
          name: "Trigger: 19:00 & Home"
          icon_idle: mdi:clock-outline
          icon_done: mdi:bell-ring
      completion:
        type: manual
      reset:
        type: daily_reset
        time: "06:00"

    # Due at 6am after getting up. Leaving and returning home completes.
    - id: walk_fay_morning
      name: "Walk Fay Morning"
      icon: mdi:dog-side
      trigger:
        type: daily
        time: "06:00"
        gate:
          entity_id: binary_sensor.bedroom_door_contact
          state: "on"
        sensor:
          name: "Trigger: 6AM / Wake Up"
          icon_idle: mdi:clock-outline
          icon_done: mdi:bell-ring
      completion:
        type: presence_cycle
        entity_id: device_tracker.potty_bermuda_tracker
        sensor:
          name: "Detect: Potty Holder Left & Returned"
          icon_idle: mdi:home
          icon_active: mdi:walk
          icon_done: mdi:home-check

    # Due at 18:30 when home. Presence cycle completes.
    - id: walk_fay_afternoon
      name: "Walk Fay Afternoon"
      icon: mdi:dog-side
      trigger:
        type: daily
        time: "18:30"
        gate:
          entity_id: binary_sensor.person_at_home
          state: "on"
        sensor:
          name: "Trigger: 18:30 & Home"
          icon_idle: mdi:clock-outline
          icon_done: mdi:bell-ring
      completion:
        type: presence_cycle
        entity_id: device_tracker.potty_bermuda_tracker
        sensor:
          name: "Detect: Potty Holder Left & Returned"
          icon_idle: mdi:home
          icon_active: mdi:walk
          icon_done: mdi:home-check
      reset:
        type: daily_reset
        time: "06:00"

    # Triggered when an automation flips input_boolean.bin_day on.
    # Presence cycle (leave + return) marks complete.
    - id: take_bins_out
      name: "Take Bins Out"
      icon: mdi:delete
      trigger:
        type: state_change
        entity_id: input_boolean.bin_day
        from: "off"
        to: "on"
        sensor:
          name: "Bin Day"
          icon_idle: mdi:delete-off
          icon_done: mdi:delete-alert
      completion:
        type: presence_cycle
        entity_id: person.diogo
        sensor:
          name: "Bin Run"
          icon_idle: mdi:home
          icon_active: mdi:walk
          icon_done: mdi:home-check
```

---

## Dashboard

The binary sensor per chore (`binary_sensor.<chore_id>`) is the most useful entity for dashboards. Use it with a conditional card to only show chores that need attention, or with a Mushroom card for a clean overview.

Example Mushroom entity card:

```yaml
type: custom:mushroom-entity-card
entity: binary_sensor.unload_washing
name: Washing Machine
icon: mdi:washing-machine
tap_action:
  action: call-service
  service: chores.complete
  service_data:
    chore_id: unload_washing
```

---

## Known Limitations (Alpha)

- No UI configuration — YAML only
- Persistent state is partially lost on restart (last completed time is persisted; other runtime state is recalculated)
- No built-in notification system — use HA automations triggered by `chores.*` events
- HACS installation requires adding as a custom repository (not yet in the default HACS catalogue)
- The `state_change` trigger does not currently support wildcard states

---

## Contributing

Issues and pull requests welcome at [GitHub](https://github.com/your-repo/ha-chores/issues).

This is alpha software. If something breaks or a config key doesn't work as documented, please open an issue with your configuration (redact any personal entity IDs if needed).

---

## Architecture

For contributors and advanced users, see [ARCHITECTURE.md](ARCHITECTURE.md) for a detailed breakdown of the internal state machine, trigger/completion/reset component model, coordinator polling, event system, and storage strategy.

---

## License

MIT
