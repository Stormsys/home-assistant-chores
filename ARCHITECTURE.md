## Chores Integration Architecture

This document explains the internal architecture of the `chores` Home Assistant custom integration so you can confidently extend and refactor it.

---

## 1. High-Level Flow

End-to-end flow for a chore:

1. **Configuration**
   - YAML config is validated by `CONFIG_SCHEMA` in `__init__.py`.
   - YAML is converted to an **internal config dict** by `_convert_yaml_to_internal_config`.
   - `create_chore_from_config` (in `chore.py`) builds a concrete `Chore` subclass.

2. **Coordinator & Devices**
   - `ChoresCoordinator` (in `coordinator.py`) is created in `async_setup_entry`.
   - Each `Chore` instance is registered with the coordinator via `register_chore`.
   - A Home Assistant **device** is created per chore via the device registry.

3. **Entities**
   - Platform modules (`sensor.py`, `binary_sensor.py`, `button.py`) create entities for each chore:
     - A primary state sensor (`ChoreStateSensor`).
     - Diagnostic sensors (`ChoreLastCompletedSensor`, `ChoreNextDueSensor`, `ChoreConfigurationSensor`, `ChoreRelatedEntitiesSensor`).
     - Binary sensor (`ChoreDueBinarySensor`) for "needs attention now".
     - Control buttons (`ChoreCompleteButton`, `ChoreSkipButton`, `ChoreResetToDueButton`, optional snooze buttons).
   - Entities inherit from `CoordinatorEntity` and auto-update when the coordinator refreshes.

4. **Runtime**
   - The coordinator polls every minute, recalculates each chore's status, and fires events on state transitions.
   - Sensor listeners (state change callbacks) are set up per chore for completion and notifications.
   - Persistent history is maintained via `ChoreHistoryStore`.

---

## 2. Devices and Entities

### 2.1 Device Creation

In `async_setup_entry` (`__init__.py`), after each chore is created, a **device** is registered:

- Device identifiers: `(DOMAIN, chore.id)`.
- Device name: `chore.name`.
- Device model: `chore.chore_type.replace("_", " ").title()`.

All entities for a given chore attach to this device using matching `DeviceInfo.identifiers`.

### 2.2 Entity Creation

Each platform exposes an `async_setup_entry` that reads the coordinator's chore registry and instantiates entities:

- `sensor.py`
  - `ChoreStateSensor`: the *primary* entity, exposing the unified state machine (`inactive`, `scheduled`, `due`, `complete_started`, `completed`).
  - `ChoreLastCompletedSensor`: diagnostic timestamp.
  - `ChoreNextDueSensor`: next due time for time-based chores.
  - `ChoreConfigurationSensor`: config details as attributes.
  - `ChoreRelatedEntitiesSensor`: all connected entity IDs.
- `binary_sensor.py`
  - `ChoreDueBinarySensor`: true when the chore needs attention (due or completion in progress).
- `button.py`
  - `ChoreCompleteButton`: manually complete.
  - `ChoreSkipButton`: skip this occurrence.
  - `ChoreResetToDueButton`: force back to DUE.
  - (Optionally) `ChoreSnoozeButton`: snooze notifications.

Each entity:
- Has a stable `unique_id` based on `DOMAIN` and `chore.id`.
- Sets `device_info.identifiers` to match the chore’s device.
- Uses the coordinator’s `get_chore_data(chore.id)` as its backing data.

---

## 3. Configuration → Chores

### 3.1 YAML Schema

In `__init__.py`, voluptuous schemas specify valid YAML:

- `CHORE_SCHEMA` governs each chore:
  - `chore_id`, `name`, `due`, optional `complete`, `notify`, `icon`, `allow_manual`, `overdue_hours`, `reset_time`, custom `states` (display config).
- `DUE_SCHEMA`, `COMPLETE_SCHEMA`, and `NOTIFY_SCHEMA` define typed sub-configs for:
  - Due trigger types (`power_cycle`, `sensor_state`, `time`, `daily`, `scheduled`, `appliance`, etc.).
  - Completion types (`manual`, `sensor_state`, `contact_opened`, `contact_cycle`, `presence_cycle`, `button`).
  - Notification types (`none`, `time`, `sensor`, `both`, `sensor_gated_interval`).

### 3.2 YAML → Internal Config

`_convert_yaml_to_internal_config`:

- Receives a single validated YAML chore config.
- Extracts:
  - `due.type` and `due.config`.
  - `complete.type` and `.config`.
  - `notify.type` and `.config`.
  - Optional `reset_time` and `states`.
- Sets generic keys defined in `const.py`:
  - `CONF_CHORE_ID`, `CONF_CHORE_NAME`, `CONF_CHORE_ICON`, `CONF_ALLOW_MANUAL`, `CONF_OVERDUE_HOURS`, `CONF_IMMEDIATELY_OVERDUE`, `CONF_RESET_TIME`, plus a `state_config` dict for display.
- Maps **due type** to an internal `CONF_CHORE_TYPE` and type-specific configuration:
  - `power_cycle` → `smart_plug` chore with plug sensors and thresholds.
  - `sensor_state` → `sensor_triggered` chore with `due_sensor`, `due_state`, `due_threshold_hours`.
  - `time` → `time_recurring` with `recurring_hours`.
  - `daily` → `daily_reset` with a `reset_time`.
  - `scheduled` → `scheduled` with `schedule_times` and `schedule_names`.
  - `appliance` → `appliance` with `trigger_sensor`, `trigger_from`, `trigger_to`.
  - Some `contact_cycle`/`presence_cycle` cases are treated as daily-reset style with defaults.
- Maps **completion type** to:
  - `CONF_COMPLETION_TRIGGER_TYPE` value (e.g. `manual_only`, `sensor_state`, `contact_opened_closed`, `presence_away_home`, `button_pressed`).
  - Optional `CONF_COMPLETE_SENSOR`, `CONF_COMPLETE_STATE`, `CONF_COMPLETION_BUTTON`.
- Maps **notification type** to:
  - `CONF_OVERDUE_NOTIFY_MINUTES`.
  - `CONF_NOTIFY_TRIGGER_SENSOR`, `CONF_NOTIFY_TRIGGER_STATE`.
  - Optional `CONF_NOTIFICATION_TRIGGER_TYPE` for advanced behaviour (like `sensor_gated_interval`).

The result is a **flat** configuration dict suitable for storage in config entries and for the chore factory.

### 3.3 Chore Factory

`create_chore_from_config` in `chore.py`:

1. Interprets `config[CONF_CHORE_TYPE]` as a `ChoreType` enum.
2. Parses optional `completion_sequence` into a normalized list if present.
3. Parses `completion_trigger_type` into a `CompletionTriggerType` enum.
4. Builds a `common_kwargs` dict (shared: id, name, icon, manual completion, overdue config, notification config, history store, completion trigger, reset time, state display config).
5. Constructs the correct subclass:
   - `SensorTriggeredChore`
   - `TimeRecurringChore`
   - `DailyResetChore`
   - `ScheduledChore`
   - `ApplianceChore`
   - `SmartPlugChore`
6. Calls `chore.load_last_completed_from_history()` to hydrate run-time state from history.

---

## 4. Reacting to Dependent Entity State Changes

### 4.1 Coordinator-Level Setup

The coordinator owns sensor listeners:

- `ChoresCoordinator.setup_sensor_listeners()`:
  - For each chore, calls `chore.setup_completion_listener(hass, self._on_sensor_completion)`.
  - If the chore has a `notify_trigger_sensor`, sets up a separate notify listener.
  - Stores unsubscribe callbacks in an internal list (`_sensor_unsub`) for cleanup.

### 4.2 Chore Completion Listeners

Completion logic is defined by the chore type and the `completion_trigger_type`:

- `Chore._setup_completion_trigger_listener`:
  - For `MANUAL_ONLY`: no listener is set up.
  - For `BUTTON_PRESSED`:
    - Uses `async_track_state_change_event` on `completion_button`.
    - On state changes, calls the coordinator callback with `(chore_id, None)` to complete.
  - For `CONTACT_OPENED`:
    - Watches `complete_sensor` and completes when it becomes `"on"`.
  - For `CONTACT_OPENED_CLOSED`:
    - Two-phase flow:
      - Contact goes `"on"` → sets internal `_contact_opened_state = True` and calls the callback with `(chore_id, -1)` to put the chore in `COMPLETE_STARTED`.
      - Then contact goes `"off"` with `_contact_opened_state` already true → completes and clears the flag.
  - For `PRESENCE_AWAY_HOME`:
    - Similar two-step pattern using presence states (`not_home`/`away` then `home`).
  - For `SENSOR_STATE`:
    - Watches `complete_sensor` and completes when it matches `complete_state`.

`SensorTriggeredChore` additionally overrides `setup_completion_listener` to support multi-step **completion sequences**:
- Each step has its own `(sensor, state)` pair.
- Each matching state change advances the sequence; the last step triggers completion.

### 4.3 Coordinator Completion Callback

When a listener detects completion or progress, it calls the coordinator’s `_on_sensor_completion`:

- `step_index == -1` → completion started (multi-step flows) → chore moves to `COMPLETE_STARTED`, UI refresh only.
- `step_index is not None` and `completion_sequence` is defined:
  - Increments `current_progress_step`.
  - When progress reaches the end of the sequence, calls `async_complete_chore(chore_id, CompletionMethod.SENSOR)`.
- Otherwise (no sequence) → directly calls `async_complete_chore`.

---

## 5. Firing Events

### 5.1 Helper

The coordinator wraps `hass.bus.async_fire` in `_fire_and_track_event`:

- Fires the event type (e.g. `chores.chore_due`).
- Records on the chore:
  - `last_event_type`
  - `last_event_time`
  - `last_event_data`

### 5.2 Event Types

Defined in `const.py`:

- `chores.chore_due`
- `chores.chore_completed`
- `chores.chore_overdue`
- `chores.chore_overdue_reminder`
- `chores.chore_notify_triggered`
- Plus `chores.chore_scheduled` and `chores.chore_completion_started` built in the coordinator.

### 5.3 When Events are Fired

Events are fired in two main places:

1. **Status transitions** inside `_fire_status_event`:
   - When a chore enters `SCHEDULED`, `DUE`, `COMPLETE_STARTED`, etc.
   - This function also updates `last_trigger_reason` and `last_trigger_time` to explain *why* the chore changed.
2. **Reminders and notifications**:
   - `_check_overdue_reminder` fires `chores.chore_overdue_reminder` at configured time intervals while the chore is overdue.
   - Notify trigger listeners fire `chores.chore_notify_triggered` when a `notify_trigger_sensor` enters the configured state and the chore is due.

---

## 6. Time-Based Logic

### 6.1 Coordinator Polling

The coordinator extends `DataUpdateCoordinator`:

- `UPDATE_INTERVAL = timedelta(minutes=1)`.
- Every minute, `_async_update_data`:
  - Calls `chore.calculate_status(hass)` for every chore.
  - If status changed since last tick:
    - Calls `_fire_status_event`.
    - Stores the new status in `_previous_status`.
  - Detects overdue state via `chore.is_overdue(hass)` when status is `DUE`.
  - Calls `_check_overdue_reminder` to possibly send overdue reminders.
  - Computes helper info (`next_due_step`, `next_completion_step`, `next_notification_step`) for UI.

### 6.2 Time in Chore Types

Each chore type implements `calculate_status` and `calculate_next_due` using time-aware logic:

- `SensorTriggeredChore`:
  - Status depends on how long the `due_sensor` has been in `due_state` (`due_threshold_hours`).
  - Uses `state.last_changed` to compute elapsed time.
- `TimeRecurringChore`:
  - Status is `DUE` if `now - last_completed >= recurring_hours`.
  - Otherwise `COMPLETED`.
- `DailyResetChore`:
  - Has a `reset_time` string (e.g. `"05:00:00"`).
  - `_get_reset_datetime` builds today’s reset `datetime`.
  - Uses a “cycle” concept: from reset → next reset.
  - If chore was completed in the current cycle, it’s `COMPLETED`; otherwise, it becomes `DUE`.
- `ScheduledChore`:
  - Parses `schedule_times` into daily time slots.
  - Chooses the “current slot” relative to now, and uses that as `due_since`.
  - `calculate_next_due` returns the next scheduled slot (today or tomorrow).
- `ApplianceChore` / `SmartPlugChore`:
  - Track transitions indicating “cycle finished” based on appliance states or power/current thresholds plus debounce.
  - Once the cycle is detected as complete, the chore becomes `DUE` until the user completes it.

### 6.3 Time-Based Helpers

`get_next_due_step`, `get_next_completion_step`, and `get_next_notification_step` on chores produce human-readable progress messages for the UI, such as:

- “Waiting for `<sensor>` to be `<state>` for Xh Ym more”.
- “Ready (recurring interval passed)”.
- “Notify every N minutes when overdue”.

These are attached to the coordinator’s data and then to entity state attributes.

---

## 7. State Storage (Where Things Live)

### 7.1 In-Memory on Chore Instances

Non-persistent, runtime-only state (lost on restart) is kept on each `Chore` instance:

- `last_completed`, `last_due`, `due_since`, `scheduled_since`.
- `_force_due`, `_contact_opened_state`, `completion_started_at`, `current_progress_step`.
- `snooze_until`, `last_reminder_sent`, `reminder_count`, `_due_event_sent`.
- Notification gate states: `_sensor_triggered`, `_sensor_triggered_at`.
- Diagnostics: `last_event_type`, `last_event_time`, `last_event_data`, `last_trigger_reason`, `last_trigger_time`.

These fields are recalculated or repopulated after startup (e.g. from history) as needed.

### 7.2 Persistent History (`ChoreHistoryStore`)

`history.py` provides a simple persistent store:

- Uses `homeassistant.helpers.storage.Store` with a key like `chores_history`.
- Persists a dict `{chore_id: [CompletionRecord, ...]}`.
- Each `CompletionRecord` has:
  - `chore_id`, `chore_name`, `completed_at` (ISO `datetime`), `completed_by` (`CompletionMethod`).
- Supports:
  - `async_add_completion` (append + save).
  - `get_history(chore_id, days)` and `get_last_completion(chore_id)`.
  - Automatic cleanup of records older than `retention_days`.

At chore creation time, `load_last_completed_from_history()` pulls the last completion time into the `Chore` instance.

### 7.3 Persistent Configuration (Config Entries)

Non-YAML configuration is stored in Home Assistant config entries:

- `entry.data` and `entry.options` can hold `CONF_CHORES` list with each chore config.
- The coordinator’s `async_update_chore_config` helper:
  - Updates the `Chore` instance attribute.
  - Writes the updated config back to the correct `CONF_CHORES` entry.
  - Calls `hass.config_entries.async_update_entry` to persist.

YAML-based setups convert config to this internal format but can also be reloaded by updating YAML and reloading the integration.

### 7.4 Entity State and Attributes

Entities expose additional, derived state through `extra_state_attributes`, for example:

- Primary state sensor:
  - `chore_id`, `chore_type`, `completion_trigger_type`.
  - Actions (`complete`, `skip`, `reset_to_due`) and which are currently allowed.
  - Display-layer data: `message`, `state_icon`, `color`, `badge_icon`, `badge_color`.
  - Diagnostics: `last_completed`, `next_due`, `due_since`, `is_overdue`, `reminder_count`, `trigger_reason`, `trigger_time`.
  - Type-specific attributes: machine/power state for smart plugs, schedule slots for scheduled chores, etc.
- Binary sensor:
  - `is_overdue`, `due_since`, `scheduled_since`, `is_snoozed`, etc.

These attributes are **not** stored anywhere special; they are recomputed from `Chore` state and coordinator data.

---

## 8. Services and Entity Services

### 8.1 Integration-Wide Services

Registered in `__init__._async_setup_services`:

- `chores.complete` (data: `chore_id`).
- `chores.reset` (data: `chore_id`).
- `chores.skip` (data: `chore_id`).
- `chores.snooze` (data: `chore_id`, `snooze_hours`).
- `chores.save_chore` (create/update chore).
- `chores.delete_chore` (remove chore).

These:
- Locate the correct coordinator (and thus `Chore`) based on `chore_id`.
- Delegate to coordinator methods (`async_complete_chore`, `async_reset_chore`, etc.).
- Update config entries and reload integrations when necessary (for `save_chore` / `delete_chore`).

### 8.2 Per-Entity Services

In `sensor.py`, the primary state sensor registers entity services:

- `complete` → `ChoreStateSensor.async_complete`.
- `skip` → `ChoreStateSensor.async_skip`.
- `reset_to_due` → `ChoreStateSensor.async_reset_to_due`.

These are essentially short-hands for the global integration services but scoped to a specific entity.

---

## 9. Unified State Machine

All chore types map onto a single, simple state machine defined in `ChoreStatus`:

- `INACTIVE`
  - No current action required, not scheduled.
- `SCHEDULED`
  - First trigger or partial condition met; waiting for full condition.
  - Examples:
    - Sensor is in the due state but minimum duration not yet reached.
    - Daily reset has passed but the notification gate sensor has not yet fired (for `sensor_gated_interval`).
    - Appliance is running but has not yet finished.
- `DUE`
  - User must act now; chore is fully triggered.
  - May also be **overdue** if age > `overdue_hours` (tracked via a separate boolean).
- `COMPLETE_STARTED`
  - A multi-step completion sequence has started (e.g. contact opened but not yet closed).
- `COMPLETED`
  - Done for this cycle, until next reset/interval/schedule.

This unified state machine:
- Drives entity states and icons.
- Drives events and notifications.
- Keeps the UI consistent across chore types.

---

## 10. What to Watch Out For When Refactoring

- **Maintain the factory contract**:
  - If you add or change chore types, keep `create_chore_from_config` and `_convert_yaml_to_internal_config` in sync with `CHORE_SCHEMA` and `ChoreType`.
- **Keep listeners paired with cleanup**:
  - Any call to `async_track_state_change_event` should have a matching unsubscribe call in `remove_sensor_listeners` or a chore-specific cleanup.
- **Don’t break the state machine semantics**:
  - Other parts of the code (binary sensor, UI, events) assume the meanings of `INACTIVE`, `SCHEDULED`, `DUE`, `COMPLETE_STARTED`, `COMPLETED`.
- **Handle restart/resume correctly**:
  - Only things in `ChoreHistoryStore` and config entries persist across restarts.
  - If you add new persistent state, either:
    - Store it in the history store, or
    - Add it to the chore’s serialized `to_dict()` and propagate via config entries.
- **Respect YAML vs UI config**:
  - YAML configuration is converted and then used to build chores.
  - When YAML is present, options-based config in the config entry might be overridden.
- **Avoid tight loops**:
  - Let `DataUpdateCoordinator` handle regular polling (currently every minute).
  - Use `async_track_state_change_event` and `async_track_time_interval` for event-driven or time-driven logic.

With this model in mind, you can safely:
- Add new chore types.
- Introduce new triggers/completion flows.
- Extend entity attributes for better UI.
- Introduce new services or front-end integrations without losing track of how the core state machine and persistence work.



