# PowerOcean HA Integration — Refactor Implementation Log

**Date**: 2026-04-30
**Branch**: `claude/refactor-ha-integration-7dnMI`
**Target architecture**: Home Assistant 2026.x
**Equipment** (from `doc/equipment.md`):
- Inverter: `HJ37ZDH5ZG5W0109` — 12 kW PowerOcean (model code `83`)
- Battery 1: `HJ3AZDH5ZG3G0384` — 5 kWh
- Battery 2: `HJ3AZDH5ZG3G0490` — 5 kWh
- PowerPulse: `AC31ZEH4AG130052` — 11 kW (JT303 / S1)

---

## 1. Summary of Changes

| File | Change type | Summary |
|------|-------------|---------|
| `const.py` | Updated | Added 5 new platforms, `BINARY_SENSOR_KEYS`, 12 write-param constants, API write endpoint |
| `api.py` | Updated | Added `async_set_property()` write method |
| `sensor.py` | Refactored | `SensorEntityDescription` registry for 60+ known keys; binary-key filter; proper `state_class` everywhere |
| `binary_sensor.py` | **New** | 7 boolean states/error flags from EMS and DEFAULT reports |
| `button.py` | **New** | `system_reboot`, `system_selfcheck` momentary actions |
| `number.py` | **New** (pass 1) | 4 numeric write entities: backup reserve SoC, fast-charge cap, charger power limit, grid import limit |
| `select.py` | **New** | 2 mode selects: charger mode, backup mode |
| `switch.py` | Updated | 5 on/off switches: EV charger enable, grid charging, system pause, **battery heating**, **auto EV charging** |
| `number.py` | Updated | 5 numeric write entities: backup reserve SoC, fast-charge cap, charger power limit, grid import limit, **charger current limit** |
| `services.yaml` | Updated | `set_tou_schedule`, `set_grid_type` — fixed `integration:` target from `powerocean` → `powerocean_dev` |
| `strings.json` | Updated | Added `entity.*.*.*` translation tree for all 6 platforms + services |
| `translations/en.json` | Updated | Full English entity names + service descriptions |
| `translations/de.json` | Updated | Full German entity names |
| `translations/fr.json` | Updated | Full French entity names |
| `__init__.py` | Updated | Service registration for `set_tou_schedule` + `set_grid_type`; service cleanup on unload |
| `manifest.json` | Updated | Version `2026.03.04` → `2026.04.30` |

---

## 2. Architecture Decisions

### 2.1 EntityDescription Pattern

All new write-entity platforms (`binary_sensor`, `button`, `number`, `select`, `switch`) use
static `EntityDescription` data-classes that carry `translation_key`, `device_class`,
`native_unit_of_measurement`, and `state_class` at definition time — no runtime inference.

The `sensor` platform retains its dynamic discovery model (API fields vary per installation)
but is augmented by a `SENSOR_DESCRIPTIONS` dict that overlays static descriptions on the
~60 most important sensor keys. Unknown sensor keys fall back to the existing
`SensorClassHelper` regex inference, preserving backward compatibility.

### 2.2 `has_entity_name = True`

Every entity sets `_attr_has_entity_name = True`. The 2026 naming engine then
constructs the full entity name as `"{device_name} {entity_name}"` automatically.
No Python code duplicates the device name in the entity name string.

### 2.3 Binary-key Exclusion

`BINARY_SENSOR_KEYS` (defined in `const.py`) lists data-point keys that must only
appear as `binary_sensor` entities. The `sensor` platform's `async_setup_entry`
filters them out:

```python
entities = [
    PowerOceanSensor(coordinator, endpoint)
    for endpoint in endpoints.values()
    if endpoint.friendly_name not in BINARY_SENSOR_KEYS
]
```

This prevents the same data-point from appearing in both domains.

### 2.4 Write Entity State Management

Write entities (number, select, switch) use a `_cached_value`/`_cached_option`/`_cached_state`
pattern: the value is `None` (→ shown as "Unknown" in UI) until the user sets it, at which
point it is cached locally and written to the API. This avoids the complexity of mapping
write-param keys back to read-report keys (which have a non-obvious path format
`_join_id(device_sn, report_key, field_name)`).

Future improvement: extend `ValueCollector` to also maintain a flat `{field_key: value}`
dict, which would allow write entities to reflect the current device state on startup.

---

## 3. APK → Entity Mapping

### 3.1 Write Commands

| APK Action / Field number | Proto field (camelCase) | HA entity type | Entity key | Notes |
|---------------------------|------------------------|----------------|------------|-------|
| `ACTION_W_ACTIVE_SYS_REBOOT` | `activeSysReboot` | `button` | `system_reboot` | Trigger payload `{activeSysReboot: 1}` |
| `ACTION_W_ACTIVE_SYS_SELFCHECK` | `activeSysSelfcheck` | `button` | `system_selfcheck` | Trigger payload `{activeSysSelfcheck: 1}` |
| `ACTION_W_CFG_BACKUP_REVERSE_SOC` / `CFG_BACKUP_REVERSE_SOC_FIELD_NUMBER` | `cfgBackupReverseSoc` | `number` | `backup_reserve_soc` | Range 0–100 %, step 1 |
| `ACTION_W_CFG_SP_FAST_CHG_MAX_SOC` / `CFG_SP_FAST_CHG_MAX_SOC_FIELD_NUMBER` | `cfgSpFastChgMaxSoc` | `number` | `fast_chg_max_soc` | Range 50–100 %, step 1 |
| `ACTION_W_CFG_SP_CHARGER_CHG_POW_LIMIT` / `CFG_SP_CHARGER_CHG_POW_LIMIT_FIELD_NUMBER` | `cfgSpChargerChgPowLimit` | `number` | `charger_power_limit` | Range 0–11 000 W (equipment: 11 kW PowerPulse), step 100 W |
| `ACTION_W_CFG_SYS_GRID_IN_PWR_LIMIT` / `CFG_SYS_GRID_IN_PWR_LIMIT_FIELD_NUMBER` | `cfgSysGridInPwrLimit` | `number` | `grid_in_pwr_limit` | Range 0–12 000 W (equipment: 12 kW inverter), step 100 W |
| `ACTION_W_CFG_SP_CHARGER_CHG_MODE` / `CFG_SP_CHARGER_CHG_MODE_FIELD_NUMBER` | `cfgSpChargerChgMode` | `select` | `charger_mode` | Options 0=auto / 1=fast / 2=eco |
| `ACTION_W_CFG_BACKUP_BOX_MODE` / `CFG_BACKUP_BOX_MODE_FIELD_NUMBER` | `cfgBackupBoxMode` | `select` | `backup_mode` | Options 0=self_use / 1=backup / 2=off |
| `ACTION_W_CFG_SP_CHARGER_CHG_OPEN` / `CFG_SP_CHARGER_CHG_OPEN_FIELD_NUMBER` | `cfgSpChargerChgOpen` | `switch` | `charger_enable` | 1=on / 0=off |
| `ACTION_W_CFG_GRID_CHARGE_TO_BATTERY_ENABLE` / `CFG_GRID_CHARGE_TO_BATTERY_ENABLE_FIELD_NUMBER` | `cfgGridChargeToBatteryEnable` | `switch` | `grid_charge_enable` | 1=on / 0=off |
| `ACTION_W_CFG_SYS_PAUSE` + `ACTION_W_CFG_SYS_RESUME` / `CFG_SYS_PAUSE_FIELD_NUMBER` | `cfgSysPause` / `cfgSysResume` | `switch` | `system_pause` | ON writes pause=1; OFF writes resume=1 |
| `ACTION_W_CFG_TOU_STRATEGY` / `CFG_TOU_STRATEGY_FIELD_NUMBER` + `CFG_TOU_HOURS_STRATEGY_FIELD_NUMBER` | `cfgTouStrategy` | `service` | `powerocean.set_tou_schedule` | Full JSON blob; see services.yaml |
| `ACTION_W_CFG_GRID_TYPE` / `CFG_GRID_TYPE_FIELD_NUMBER` | `cfgGridType` | `service` | `powerocean.set_grid_type` | 0=single-phase / 1=three-phase |

> **Note on write parameter names**: The camelCase field names are derived by converting
> the UPPER_SNAKE proto field-number constants (e.g. `CFG_BACKUP_REVERSE_SOC_FIELD_NUMBER`)
> to camelCase (e.g. `cfgBackupReverseSoc`). This derivation is consistent with the pattern
> used in the EcoFlow consumer REST API as observed in the existing integration.
> Values should be verified on hardware before using in production automations.

### 3.2 Write Endpoint

APK string `"/iot-devices/device/setDeviceProperty"` was found in the DEX string table
alongside bearer-auth header patterns. The integration uses this endpoint with the
same bearer token obtained during `async_authorize()`.

Payload format:
```json
{"sn": "<device_sn>", "params": {"<camelCase_field>": <value>}}
```

Previous code assumption: all data was read-only via `/provider-service/user/device/detail`.
APK analysis (Pass 2, §1) confirmed `/iot-devices/device/setDeviceProperty` and
`/iot-devices/device/setDevicePropertyWithPower` as dedicated write endpoints.

### 3.3 Boolean States → Binary Sensor

The following EMS_HEARTBEAT / DEFAULT data-points were previously created as regular
`sensor` entities.  They have been migrated to `binary_sensor`:

| Data-point key | Old domain | New domain | Device class |
|----------------|-----------|-----------|--------------|
| `online` | `sensor` | `binary_sensor` | `connectivity` |
| `emsBpSelfcheckState` | `sensor` | `binary_sensor` | `problem` |
| `emsMpptSelfcheckState` | `sensor` | `binary_sensor` | `problem` |
| `emsMpptRunState` | `sensor` | `binary_sensor` | `running` |
| `epoSwitchState` | `sensor` | `binary_sensor` | `safety` |
| `autoDetectStartPowerEn` | `sensor` | `binary_sensor` | *(none)* |
| `isPvToInvDirectly` | `sensor` | `binary_sensor` | *(none)* |

### 3.4 PowerPulse (JT303) — Current State

APK Pass 2 confirmed PowerPulse = JT303 = S1.  The existing integration already
handles the PowerPulse report via `WALLBOX_SYS` / `EDEV_PARAM_REPORT` parsers and
correctly identifies `AC31ZEH4AG130052` as a sub-device.

This refactor adds:
- `switch.charger_enable` — `cfgSpChargerChgOpen` (PowerPulse on/off)
- `select.charger_mode` — `cfgSpChargerChgMode` (auto / fast / eco)
- `number.charger_power_limit` — `cfgSpChargerChgPowLimit` (max 11 000 W)

These entities attach to the main inverter device (`HJ37ZDH5ZG5W0109`) because
they write through the inverter API, not directly to the PowerPulse sub-device.

### 3.5 Dropped / Out-of-Scope Items

| Feature | Reason omitted |
|---------|---------------|
| Generator control (11 actions) | `equipment.md` has no generator add-on |
| `ACTION_W_CFG_SP_CHARGER_CAR_BATT_CHG_AMP_LIMIT` | Overlaps with `charger_power_limit`; amp-level control not needed for 11 kW AC charger |
| Direct PowerPulse MQTT write (`/app/<userId>/<sn>/thing/property/set`) | REST API is the supported public surface; MQTT requires broker credentials not available via consumer auth |
| TOU hours as individual entities | APK analysis explicitly recommends a single-blob service call |
| Phase detection switch | `CFG_SYS_PHASE_DETECTION_ENABLED` absent from `raw_action_w_powerocean.txt`; equipment is fixed three-phase |

---

## 4. Statistics and Energy Dashboard

All numeric sensors in `SENSOR_DESCRIPTIONS` have explicit `state_class`:
- `SensorStateClass.MEASUREMENT` — instantaneous values (power, voltage, current, temperature, SoC)
- `SensorStateClass.TOTAL_INCREASING` — cumulative counters (energy, cycles)
- `SensorStateClass.TOTAL` — period-reset totals (`bpTotalChgEnergy` / `bpTotalDsgEnergy`)

The `device_class` + `native_unit_of_measurement` pairings are chosen so HA's
Energy Dashboard auto-discovers the following sensors:
- **Solar production**: `totalElectricityGeneration` (kWh, total_increasing)
- **Grid import**: `gridInDayEnergy` (Wh, total_increasing)
- **Grid export**: `gridOutDayEnergy` (Wh, total_increasing)
- **Battery charge**: `bpInDayEnergy` (Wh, total_increasing)
- **Battery discharge**: `bpOutDayEnergy` (Wh, total_increasing)
- **Home consumption**: `loadDayEnergy` (Wh, total_increasing)

---

## 5. Naming Engine

`has_entity_name = True` is set on every entity class.  HA 2026 then combines the
device name (set at device-registry level in `__init__.py`) with the entity's
`translation_key`-resolved name.  Example:

> Device name: **Florian Krebs**
> Entity translation: **Battery State of Charge**
> Result in UI: **Florian Krebs Battery State of Charge**

German Voice Assist will resolve to **Ladezustand der Batterie** via `de.json`.

---

## 6. Known Limitations / Future Work

1. **Write-param names need hardware confirmation** — camelCase derivation is consistent
   but the exact API field names should be verified by capturing a successful write
   from the EcoFlow app (e.g., via `MqttDebugActivity` or mitmproxy).

2. **State read-back for write entities** — number/select/switch entities currently
   show "Unknown" until the user sets a value.  This can be improved by:
   - Extending `ValueCollector` with a flat `{key: value}` secondary index.
   - Mapping write-param keys to their corresponding report-field unique_ids.

3. **PowerPulse direct sub-device write** — the `set_quota` path via the main inverter
   SN may route commands to the PowerPulse.  If not, the PowerPulse SN
   (`AC31ZEH4AG130052`) should be used in `async_set_property` for SP charger commands.

4. **Region detection for write** — `_detect_region` only probes EU/US; Asia/CN hosts
   (`api-a`, `api-cn`) are not tried.  Add them if deployments outside EU/US report
   write failures.

---

## 7. Refactor Pass 2 — 2026-04-30

### 7.1 New Write Entities Added

APK analysis pass 2 (`raw_action_w_powerocean.txt`) identified three additional write
surfaces not covered in pass 1:

| Entity key | Platform | APK action | Proto camelCase key | Equipment relevance |
|---|---|---|---|---|
| `battery_heat` | `switch` | `ACTION_W_CFG_BMS_BATTERY_HEAT` | `cfgBmsBatteryHeat` | Critical for 2× 5 kWh batteries in German winter (< 0 °C reduces charge acceptance) |
| `charger_auto_chg` | `switch` | `ACTION_W_CFG_SP_CHARGER_AUTO_CHG_OPEN` | `cfgSpChargerAutoChgOpen` | Enables PowerPulse smart TOU / solar-priority auto-charging |
| `charger_amp_limit` | `number` | `ACTION_W_CFG_SP_CHARGER_DEV_BATT_CHG_AMP_LIMIT` | `cfgSpChargerDevBattChgAmpLimit` | IEC 61851 AC charging current cap (6–32 A) for 11 kW PowerPulse |

All three entities attach to the main inverter device (`HJ37ZDH5ZG5W0109`) because
write commands route through the inverter API, not directly to the sub-device.

### 7.2 services.yaml Domain Fix

`target: device: integration:` was referencing `powerocean` (original domain) instead
of `powerocean_dev` (current domain). Fixed in both `set_tou_schedule` and
`set_grid_type` service definitions.

### 7.3 Energy-Flow Interpolation Logging

`parser.py._handle_ems_heartbeat_mode()` now emits targeted `LOGGER.warning()` calls
when either `pcsMeterPower` or `emsBpPower` is absent from the EMS heartbeat response.
These two fields are the sole inputs for the eight derived energy-flow sensors
(`housePower`, `gridPower`, `gridToBattery`, etc.). When absent, the derived values are
silently zero — the warnings make this visible in HA logs and reference the specific
APK field name to aid debugging.

Additionally, a `LOGGER.warning()` fires when the computed house consumption would be
negative (indicating a `pcsMeterPower` sign-convention mismatch with the APK analysis).

`LOGGER.debug()` logs emit the raw inputs and computed outputs for each EMS heartbeat
cycle, enabling detailed trace-level analysis without noise in production.

### 7.4 Code Quality — German Comments Removed

All German-language code comments and docstrings across all Python modules have been
translated to English, including:
- `coordinator.py` — docstring `_async_update_data`
- `__init__.py` — inline comments in `async_setup_entry`, `async_migrate_entry`
- `parser.py` — 6 inline comments
- `utils.py` — `clean_zero` docstring + `BoxSchema.sensors` comment
- `config_flow.py` — 5 method docstrings and inline comments

### 7.5 Translation Updates

`strings.json`, `translations/en.json`, `translations/de.json`, `translations/fr.json`
each received entries for the 3 new entities:

| Key | EN | DE | FR |
|---|---|---|---|
| `switch.battery_heat` | Battery Heating | Batterieheizung | Chauffage batterie |
| `switch.charger_auto_chg` | Automatic EV Charging | Automatisches Laden | Charge automatique VE |
| `number.charger_amp_limit` | Charger Current Limit | Ladestrom Limit | Limite courant de charge |
   write failures.
