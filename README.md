# Chores for Home Assistant

[![GitHub Release](https://img.shields.io/github/v/release/Stormsys/home-assistant-chores?style=for-the-badge)](https://github.com/Stormsys/home-assistant-chores/releases)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1.0+-blue?style=for-the-badge&logo=home-assistant)](https://www.home-assistant.io/)
[![Alpha](https://img.shields.io/badge/Status-Alpha-red?style=for-the-badge)](https://github.com/Stormsys/home-assistant-chores)

Track household chores using your existing smart home sensors. Each chore follows a simple lifecycle — **inactive → pending → due → started → completed** — driven by real device events, not manual checklists.

> **Alpha Software:** Configuration schema and entity names may change between versions.

---

## How It Works

Chores watches your devices and marks tasks done when the physical action happens:

- **Washing machine finishes** (smart plug detects power drop) → "Unload Washing" becomes due → opening the machine door completes it
- **6am + bedroom door opens** → "Take Vitamins" becomes due → opening and closing the pill cupboard completes it
- **Walk time arrives** → "Walk the Dog" becomes due → leaving home and returning completes it
- **Bin night helper flips on** → "Take Bins Out" becomes due → leaving and returning completes it

Chores you can't auto-detect are completed manually via a button or service call.

---

## Installation

### HACS (Recommended)

1. Open HACS → **Integrations** → three-dot menu → **Custom repositories**
2. Add `https://github.com/Stormsys/home-assistant-chores` with category **Integration**
3. Find **Chores** and click **Download**
4. Restart Home Assistant

> **Note:** This integration is currently in alpha. To see alpha/beta releases in HACS, open the integration's HACS page, click the three-dot menu, and enable **Show beta versions**. Without this, HACS will only show stable releases.

### Manual

1. Copy `custom_components/chores` into your `config/custom_components/` directory
2. Restart Home Assistant

---

## Quick Start

Add to `configuration.yaml`:

```yaml
chores:
  chores:
    - id: feed_the_dog
      name: "Feed the Dog"
      icon: mdi:dog-bowl
      trigger:
        type: daily
        time: "08:00"
      completion:
        type: manual

      # Optional: delay announcements until a specific time or delay
      notify_at: "21:00"           # don't announce before 9pm
      notify_after_minutes: 30     # don't announce until 30 min after due
```

Restart Home Assistant. You'll get a sensor, binary sensor, and control buttons for the chore.

For a complete multi-chore example, see [`example_configuration.yaml`](example_configuration.yaml).

---

## Triggers, Completions, and Resets

Every chore is built from three pluggable components. Most detector types work in **either** trigger or completion position — mix and match to fit your use case.

### Triggers

Triggers define **what makes the chore due**. All triggers support an optional `gate` to hold the chore in `pending` until a secondary condition is met.

| Type | Use case | Gate support |
|------|----------|:---:|
| `daily` | Fixed time each day (e.g. "6am, but only after I'm out of bed") | Yes |
| `weekly` | Specific days and times (e.g. "Wed 21:00 and Fri 21:30") | Yes |
| `power_cycle` | Smart plug detects an appliance finishing a cycle | Yes |
| `state_change` | Any entity transitions between two states | Yes |
| `duration` | Entity stays in a target state for N hours (e.g. drying rack out for 48h) | Yes |
| `sensor_state` | Entity enters a target state | Yes |
| `contact` | Contact sensor opens | Yes |
| `contact_cycle` | Contact opens then closes | Yes |
| `presence_cycle` | Person/tracker leaves then returns | Yes |
| `sensor_threshold` | Numeric sensor crosses a threshold | Yes |

### Completions

Completions define **how the chore gets marked done**. Only active while the chore is `due` or `started`. All types (except `manual`) support an optional `gate`.

| Type | Steps | Use case |
|------|:-----:|----------|
| `manual` | — | Button press or service call only |
| `contact` | 1 | Contact sensor opens (machine door, drawer) |
| `contact_cycle` | 2 | Contact opens *then* closes (pill box, cupboard) |
| `presence_cycle` | 2 | Person leaves *then* returns home (walks, errands) |
| `sensor_state` | 1 | Any entity enters a target state |
| `sensor_threshold` | 1 | Numeric sensor crosses a threshold (above/below/equal) |
| `power_cycle` | 2 | Appliance finishes a power cycle |
| `state_change` | 1 | Entity transitions between two states |
| `duration` | 2 | Entity stays in target state for N hours |

### Resets

Resets control **when a completed chore goes back to inactive**. If omitted, a sensible default is chosen based on the trigger type.

| Type | Use case |
|------|----------|
| `delay` | Fixed delay after completion (0 = immediate) |
| `daily_reset` | Reset at a specific time each day |
| *(auto)* | `daily`/`weekly` triggers reset at next occurrence; event-based triggers reset immediately |

Full YAML reference with all parameters: **[Configuration Reference](docs/configuration.md)**

---

## State Machine

```
INACTIVE ──trigger fires──→ PENDING ──gate met──→ DUE
                                                   │
                              ┌── 1-step ──→ COMPLETED
                              │                    │
                              └── 2-step ──→ STARTED ──→ COMPLETED
                                                              │
                                                         reset fires
                                                              │
                                                           INACTIVE
```

Single-step completions (`manual`, `contact`, `sensor_state`) skip `STARTED` and go straight from `DUE` to `COMPLETED`. Two-step completions (`contact_cycle`, `presence_cycle`) use the `STARTED` intermediate state.

---

## Entities Created

Each chore gets its own device with these entities:

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.<chore_id>_chore` | Sensor | Primary state: inactive, pending, due, started, completed |
| `sensor.<chore_id>_trigger_detector` | Sensor | Trigger progress: idle, active, done |
| `sensor.<chore_id>_completion_detector` | Sensor | Completion progress: idle, active, done |
| `sensor.<chore_id>_reset_detector` | Sensor | Reset status: idle, waiting |
| `sensor.<chore_id>_last_completed` | Sensor | Timestamp of last completion (diagnostic) |
| `binary_sensor.<chore_id>_needs_attention` | Binary Sensor | `on` when chore is due or started |
| `button.<chore_id>_force_due` | Button | Force into due state |
| `button.<chore_id>_force_complete` | Button | Force into completed state |
| `button.<chore_id>_force_inactive` | Button | Force into inactive state |

Entity names use the `has_entity_name` pattern — HA combines the device name (chore name) with the entity name. For example, a chore named "Unload Washing Machine" produces `sensor.unload_washing_machine_chore`.

---

## Services and Events

### Services

| Service | Description |
|---------|-------------|
| `chores.force_due` | Force a chore to `due` |
| `chores.force_inactive` | Force a chore to `inactive` |
| `chores.force_complete` | Force a chore to `completed` |

All require `chore_id` in the service data. The same actions are available as entity services on each chore's main sensor and as button presses.

### Events

Every state transition fires an event on the HA bus:

| Event | When |
|-------|------|
| `chores.chore_pending` | Chore enters pending |
| `chores.chore_due` | Chore becomes due |
| `chores.chore_started` | Multi-step completion started |
| `chores.chore_completed` | Chore completed |
| `chores.chore_reset` | Chore resets to inactive |

Event data includes `chore_id`, `chore_name`, `previous_state`, and `new_state`.

**Example automation:**

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

## Dashboard Tips

The binary sensor (`binary_sensor.<chore_id>_needs_attention`) is the most useful entity for dashboards. Use it with conditional cards to only show chores that need attention.

```yaml
type: custom:mushroom-entity-card
entity: binary_sensor.unload_washing_needs_attention
name: Washing Machine
icon: mdi:washing-machine
tap_action:
  action: call-service
  service: chores.force_complete
  service_data:
    chore_id: unload_washing
```

---

## Known Limitations

- YAML-only configuration (no UI config flow)
- No built-in notifications — use HA automations with `chores.*` events
- Not yet in the default HACS catalogue (add as custom repository)
- `state_change` trigger does not support wildcard states

---

## Documentation

| Document | Description |
|----------|-------------|
| [Configuration Reference](docs/configuration.md) | Full YAML schema, all trigger/completion/reset types with parameters |
| [Architecture](ARCHITECTURE.md) | Internal design for contributors |
| [Example Config](example_configuration.yaml) | Complete working configuration with all trigger and completion types |

---

## Contributing

Issues and pull requests welcome at [GitHub](https://github.com/Stormsys/home-assistant-chores/issues).

---

## License

MIT
