# Chores for Home Assistant

[![GitHub Release](https://img.shields.io/github/v/release/your-repo/ha-chores?style=for-the-badge)](https://github.com/your-repo/ha-chores/releases)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1.0+-blue?style=for-the-badge&logo=home-assistant)](https://www.home-assistant.io/)
[![Alpha](https://img.shields.io/badge/Status-Alpha-red?style=for-the-badge)](https://github.com/your-repo/ha-chores)

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
2. Add `https://github.com/your-repo/ha-chores` with category **Integration**
3. Find **Chores** and click **Download**
4. Restart Home Assistant

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
```

Restart Home Assistant. You'll get a sensor, binary sensor, and control buttons for the chore.

For a complete multi-chore example, see [`example_configuration.yaml`](example_configuration.yaml).

---

## Triggers, Completions, and Resets

Every chore is built from three components:

| Component | Purpose | Types |
|-----------|---------|-------|
| **Trigger** | What makes the chore due | `daily`, `power_cycle`, `state_change` |
| **Completion** | How the chore gets marked done | `manual`, `contact`, `contact_cycle`, `presence_cycle`, `sensor_state` |
| **Reset** | When it goes back to inactive | `delay`, `daily_reset` (or auto-selected defaults) |

**Triggers** at a glance:

| Type | Use case |
|------|----------|
| `daily` | Fixed time each day, with optional gate (e.g. "after 6am, but only once I'm out of bed") |
| `power_cycle` | Smart plug detects an appliance finishing a cycle |
| `state_change` | Any entity transitions between two states |

**Completions** at a glance:

| Type | Steps | Use case |
|------|-------|----------|
| `manual` | — | Button press or service call only |
| `contact` | 1 | Contact sensor opens (door, drawer) |
| `contact_cycle` | 2 | Contact opens *then* closes (pill box, cupboard) |
| `presence_cycle` | 2 | Person leaves *then* returns home (walks, errands) |
| `sensor_state` | 1 | Any entity enters a target state |

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
| `sensor.<chore_id>` | Sensor | Primary state: inactive, pending, due, started, completed |
| `sensor.<chore_id>_trigger` | Sensor | Trigger progress: idle, active, done |
| `sensor.<chore_id>_completion` | Sensor | Completion progress: idle, active, done |
| `sensor.<chore_id>_reset` | Sensor | Reset status: idle, waiting |
| `sensor.<chore_id>_last_completed` | Sensor | Timestamp of last completion (diagnostic) |
| `binary_sensor.<chore_id>_needs_attention` | Binary Sensor | `on` when chore is due or started |
| `button.<chore_id>_force_due` | Button | Force into due state |
| `button.<chore_id>_force_complete` | Button | Force into completed state |
| `button.<chore_id>_force_inactive` | Button | Force into inactive state |

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

Issues and pull requests welcome at [GitHub](https://github.com/your-repo/ha-chores/issues).

---

## License

MIT
