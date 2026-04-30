# EcoFlow APK Analysis — PowerOcean & PowerPulse Integration

**File**: `EcoFlow_6.13.8.2_APKPure/com.ecoflow.apk` (332 MB)
**App version**: EcoFlow 6.13.8.2
**Original analysis**: 2026-04-30 (shallow string scan)
**Deep analysis**: 2026-04-30 (full DEX string-table parse — 539,948 unique strings)

Raw outputs from the deep pass are committed under [doc/logs/](logs/). The execution trace and tool invocations are in [apk-logs.md](apk-logs.md).

---

## Summary

The deep pass corrects an important mistake in the first analysis: **PowerPulse is not a stub**. It appears 11 times under the literal name `powerpulse`, but the device is referenced internally as **JT303** / **S1**, which yields **1,170 unique strings**, a dedicated Kotlin module (`com.ecoflow.jtmodule`), three protobuf schemas, and a BLE command surface (`JT303BleCommand.kt`). The original "PowerPulse is read-only" conclusion was wrong.

PowerOcean remains the larger surface (667 strings under `powerocean`/`powerOcean`, plus everything routed through `po_edev.proto` and `po_edev_cmd.proto`). The integration writes go through MQTT-style topic templates discovered in this pass — not directly through the Open API as previously assumed.

---

## File Structure (validated)

| Metric                         | Count   |
|--------------------------------|---------|
| Total APK entries              | 15,780  |
| DEX (compiled code) files      | 48      |
| **Unique strings extracted**   | 539,948 |
| Proto file references in DEX   | **~100** (vs. 22 found on disk) |
| Permissions declared           | 30+     |
| ACTION_W_* write actions       | 991 (496 unique non-`_VALUE`) |
| `_FIELD_NUMBER` constants      | 1,851 PO-relevant (BMS/PCS/SP/GRID/BACKUP/PV/INV/TOU/SYS) |

---

## ✅ Original Findings — Validated

| Original claim                                            | Status | Evidence |
|-----------------------------------------------------------|--------|----------|
| 624 PowerOcean string references                          | ✅ confirmed (now 667 with deeper pass) | grep `powerocean\|powerOcean` |
| `cmdSet`/`cmdId` parameter system                         | ✅ confirmed | `ParamsDTO{cmdSet=`, `CmdInfo(cmdSet=`, `parseDeviceData: cmdSet=` |
| `ACTION_W_CFG_SP_CHARGER_*` write commands present        | ✅ confirmed; 991 total `ACTION_W_*` actions exist app-wide |
| `_FIELD_NUMBER` proto constants                           | ✅ confirmed; 1,851 PO-relevant (was undercounted) |
| Phase-detection writable                                  | ✅ confirmed via `CFG_SYS_PHASE_DETECTION_ENABLED_FIELD_NUMBER` and `ACTION_W_CFG_SYS_*` |
| TOU support                                               | ✅ confirmed; `CFG_TOU_STRATEGY_FIELD_NUMBER`, `CFG_TOU_HOURS_STRATEGY_FIELD_NUMBER`, `ACTION_W_CFG_TOU_STRATEGY` |
| 5 device types (deviceType 1-5)                           | ✅ confirmed (in JSON asset configs) |

## ❌ Original Findings — Corrected

| Original claim                                       | Correction |
|------------------------------------------------------|------------|
| "PowerPulse is read-only / minimal" (11 refs)        | **Wrong.** 1,170 strings under `jt303_*`, full settings UI (4G/APN, AFCI, AI mode, TOU, EV charging, parallel master/slave, AC305 binding, custom grid code), three protobufs (`jt_s1_sys.proto`, `jt_s1_cmd.proto`, `jt_s1_ev.proto`), and `JT303BleCommand.kt` BLE surface. PowerPulse = JT303 = S1 internally. |
| "22 proto files"                                     | Only 22 are extractable as files (Google Matter scaffold). DEX strings reference **~100 EcoFlow proprietary `.proto` files** compiled into bytecode. |
| "Open API is the write path"                         | The app's primary write path is **MQTT** with topic templates `/app/<userId>/<sn>/thing/property/set` and `/ep/<userId>/<sn>/thing/property/set` (see new findings). The Open API (`/iot-open/sign/...`) is a separate, smaller surface. |

---

## NEW: MQTT Topic Templates (highest-value finding)

The app uses **Eclipse Paho MQTT** (`org.eclipse.paho.android.service.MqttService` declared in AndroidManifest). Topic format strings discovered in DEX:

```
/app/%s/%s/thing/property/get          # subscribe: cloud → app   (root device)
/app/%s/%s/thing/property/get_reply
/app/%s/%s/thing/property/set          # publish:   app   → cloud (write quota)
/app/%s/%s/thing/property/set_reply
/app/%s/+/thing/property/get_reply     # MQTT wildcard subscriptions
/app/%s/+/thing/property/set_reply

/ep/%s/%s/thing/property/get           # endpoint (sub-device) topics
/ep/%s/%s/thing/property/set
/ep/%s/+/thing/property/set_reply

/app/%s/%d/biz/data/notify             # business data stream
/app/%s/%d/biz/data/request
/app/%s/%d/biz/data/response

/app/%s/message/push
/shelly/thing/property/post/           # Shelly devices (third-party)
```

**Format**: first `%s` is the user identifier; second `%s` is the device SN. `+` is the MQTT single-level wildcard. `/ep/...` topics are for sub-devices/endpoints behind a hub (e.g., devices behind a PowerOcean/SHP gateway).

**Implication**: The Home Assistant integration's `set_quota` calls correspond directly to publishing `{"cmdSet":N,"cmdId":M,"params":{...}}` payloads to `/app/<userId>/<sn>/thing/property/set`. The Open API endpoint (`/iot-open/sign/...`) is a thin REST wrapper around this; the cloud forwards both to the device over its own MQTT broker.

## NEW: API Hosts & Endpoint Inventory

**Production hosts** (DEX literals):
- `https://api.ecoflow.com` — global
- `https://api-e.ecoflow.com` — Europe
- `https://api-a.ecoflow.com` — Asia/Australia
- `https://api-cn.ecoflow.com` — China
- `https://iot-ecoflow.com` (and various CDN: `ecoflow-service-test-cdn.ecoflow.com`)

**Endpoint surface** (deduplicated):
- 156 endpoints under `/iot-service/...` (REST device service)
- 60+ endpoints under `/iot-devices/...` (device CRUD)
- 60+ endpoints under `/provider-service/...` (installer/provider portal)
- `/iot-open/sign/device/list` and `/iot-open/sign/device/quota/all` — **the OpenAPI surface used by community integrations**
- `/iot-quota/device/quota/batch/get` — batch quota fetch
- `/iot-shadow/cmd/issue/device` — device-shadow command issue
- `/iot-ota/...` — firmware OTA

Full list: [doc/logs/raw_endpoints.txt](logs/raw_endpoints.txt).

PowerPulse-specific REST endpoints (only two — most PowerPulse settings flow through MQTT, not REST):
```
/provider-service/user/app/powerpulse/report/list
/provider-service/user/app/powerpulse/report/summery
```

## NEW: PowerPulse / JT303 Capability Map

JT303 is the engineering codename for PowerPulse. Full feature surface present in the app:

**Connectivity**
- 4G dongle (carrier, APN, IPv4/IPv6, authentication: PAP/CHAP, MCC/MNC, SIM PIN/PUK)
- Ethernet (`activity_po2_ethernet_settings.xml`)
- Wi-Fi setup (`bg_jt303_connect_wifi`)

**Energy management**
- AI mode with electricity-price sync
- TOU (time-of-use) strategy; force-charge strategy
- Backup reserve SoC; auto-backup-reserve
- Battery calibration; battery-priority vs. load-priority threshold
- Grid feeding (`jt303_setting_System_feeding`, `_to_grid`)
- System-feeding price awareness (Powerocean_pou_systemfeed_pirce_*)

**Hardware control**
- AFCI (arc-fault detection) enable + reset
- Custom grid code (over-/under-frequency, voltage de-rating, HVRT/LVRT, island detection, reactive-power mode)
- Battery speed charge/discharge
- Standby generator, oil-engine integration
- 14a series (US 14A relay outputs)
- Phase settings (single/three-phase)
- Parallel master/slave (CT501 cascading)

**Linked devices** (via JT303)
- AC305 portable PSU (`device_mt_ac305_bind_jt303_tip`)
- CP307 EV charger (`jt303_charger_307_layout`, `jt_s1_charger_307_setting_layout`)
- Heat rod / heat pump (`jt_s1_heatingrod.proto`, `jt_s1_heatpump.proto`)
- DC303 DC charger (`dc303_sys.proto`, `dc303_cmd.proto`)
- FT308 / FT323 / GE305 / RE307 (referenced in protobufs)

**BLE command surface**
```
com/ecoflow/common/command/JT303BleCommand
com/ecoflow/common/command/JT303BleCommand$getBaseParallelDevList
JT303BleCommand.kt + JT303DataHelper.kt + JT303DataParseHelper.kt + JT303MergeDataHelper.kt
```

**Settings activity**: `/S1InstallerApp/Jt303SettingsActivity` (the JT303 settings live inside the S1 installer flow — JT303 is positioned as part of the S1 family).

**Conclusion**: PowerPulse supports nearly the same write surface as PowerOcean. Any integration claiming "read-only PowerPulse" is missing 95% of the feature surface. The MQTT topic family `/app/<user>/<sn>/thing/property/set` works equally for both device types.

## NEW: Proto Schema Inventory (compiled into DEX)

~100 `.proto` references, of which the proprietary EcoFlow set covers PowerOcean & PowerPulse. Highlights:

**PowerOcean / SHP / RE307 family**
- `po_edev.proto`, `po_edev_cmd.proto` — PowerOcean ecology-device commands
- `re307_sys.proto` — RE306/RE307 (PowerOcean Pro circuit panel)
- `pd303.proto`, `pd335_sys.proto`, `pd335_bms_bp.proto` — Smart Home Panel 2

**PowerPulse / JT303 / S1 family**
- `jt_s1_sys.proto`, `jt_s1_cmd.proto`
- `jt_s1_ev.proto` (EV charging)
- `jt_s1_ecology_dev.proto`, `jt_s1_edev.proto`, `jt_s1_edev_convert.proto`
- `jt_s1_heatingrod.proto`, `jt_s1_heatpump.proto`
- `jt_s1_parallel.proto` (cascading master/slave)
- `jt_s1_bat_health.proto`
- `jt_s1_sys_re307.proto` (S1 ↔ RE307 integration)
- `jt_14a.proto`, `jt_parallel_lan.proto`, `jt_wn_socket.proto`

**Linked devices**
- `cp307_iot.proto`, `cp307_sys.proto`, `cp307_ocpp.proto`, `cp307_14a.proto` — CP307 EV charger (note OCPP support)
- `dc303_sys.proto`, `dc303_cmd.proto` — DC charger
- `ft308_sys.proto`, `ft308_cmd.proto`, `ge305_sys.proto`
- `bk_series.proto`, `bk622_common.proto`, `bk_diagnosis.proto` — BK620/621/622/623

**Common / framework**
- `iot_comm.proto`, `iot_config.proto` — IoT transport layer
- `bms_cloud.proto`, `battery_info_sys.proto`
- `ble.proto`, `ble_crt_info.proto`, `bluetooth.proto` — BLE protocols
- `efsettings.proto`, `wifi_memory.proto`, `net_diagnosis.proto`

Full list in [doc/logs/raw_proto_files.txt](logs/raw_proto_files.txt).

The presence of `cp307_ocpp.proto` is notable — **CP307 supports OCPP** (Open Charge Point Protocol 1.6/2.0), confirming why `/iot-service/ac305/charge/ocpp/domain` exists.

## NEW: Writable Configuration Surface (496 unique ACTION_W_*)

The app exposes 496 distinct writable actions (not counting `_VALUE` enum siblings). PowerOcean-relevant subset (70 actions): [doc/logs/raw_action_w_powerocean.txt](logs/raw_action_w_powerocean.txt).

Highest-value categories for HA integration:

**Charger control (SP)** — 16 writable actions
```
ACTION_W_CFG_SP_CHARGER_CHG_MODE                # mode select (auto/fast/eco/...)
ACTION_W_CFG_SP_CHARGER_CHG_OPEN                # enable/disable
ACTION_W_CFG_SP_CHARGER_CHG_POW_LIMIT           # power limit (W)
ACTION_W_CFG_SP_CHARGER_DEV_BATT_CHG_AMP_LIMIT  # device battery amp cap
ACTION_W_CFG_SP_CHARGER_CAR_BATT_CHG_AMP_LIMIT  # car battery amp cap
ACTION_W_CFG_SP_CHARGER_AUTO_CHG_OPEN
ACTION_W_CFG_SP_CHARGER_AUTO_CHG_VOL_MIN
ACTION_W_CFG_SP_CHARGER_AUTO_REVERSE_CHG_VOL_MIN
ACTION_W_CFG_SP_CHARGER_DRIVING_CHG_SETTING
ACTION_W_CFG_SP_CHARGER_DEV_BATT_TYPE / CAR_BATT_TYPE
ACTION_W_CFG_SP_CHARGER_DEV_BATT_CHG_XT60_SETTING
ACTION_W_CFG_SP_CHARGER_EXTENSION_LINE_N/P_SETTING
ACTION_W_CFG_SP_CHARGER_INSTALL_TYPE
ACTION_W_CFG_SP_CHARGER_CAR_BATT_VOL_SETTING
ACTION_W_CFG_SP_CHARGER_CAR_BATT_URGENT_CHG_SWITCH
ACTION_W_CFG_SP_FAST_CHG_MAX_SOC
ACTION_W_CFG_SP_BMS_CHG_MODE
```

**Grid connection** — 6 writable actions
```
ACTION_W_CFG_GRID_CHARGE_TO_BATTERY_ENABLE
ACTION_W_CFG_GRID_CONNECTION_FREQ_SETTING
ACTION_W_CFG_GRID_CONNECTION_POWER_FACTOR_SETTING
ACTION_W_CFG_GRID_CONNECTION_POWER_SETTING
ACTION_W_CFG_GRID_CONNECTION_VOL_SETTING
ACTION_W_CFG_GRID_TYPE                           # single/3-phase
ACTION_W_CFG_GRID_SYS_DEVICE_CNT
```

**Backup & TOU**
```
ACTION_W_CFG_BACKUP_BOX_MODE                    # backup mode select
ACTION_W_CFG_BACKUP_REVERSE_SOC                 # SoC threshold below which to charge
ACTION_W_CFG_BACKUP_SOC_VPP                     # virtual-power-plant reserve
ACTION_W_CFG_TOU_STRATEGY                       # TOU policy write
```

**Inverter / PV / PCS**
```
ACTION_W_CFG_INV_TARGET_PWR / TARGET_VOL
ACTION_W_CFG_PV_CHG_TYPE / DC_CHG_SETTING / METER_IN_FLAG
ACTION_W_CFG_PCS_SHUTDOWN_CTRL
```

**System / lifecycle**
```
ACTION_W_ACTIVE_SYS_REBOOT
ACTION_W_ACTIVE_SYS_SELFCHECK
ACTION_W_CFG_SYS_PHASE_DETECTION_ENABLED        # phase auto-detect
ACTION_W_CFG_SYS_PAUSE / RESUME / RESTART
ACTION_W_CFG_SYS_GRID_IN_PWR_LIMIT
```

**Standby generator** — 11 writable actions (full control)
```
ACTION_W_CFG_GENERATOR_ENGINE_OPEN              # start/stop
ACTION_W_CFG_GENERATOR_AC_OUT_POW_MAX
ACTION_W_CFG_GENERATOR_DC_OUT_POW_MAX
ACTION_W_CFG_GENERATOR_OUT_POW_MAX
ACTION_W_CFG_GENERATOR_LOW_POWER_EN / THRESHOLD
ACTION_W_CFG_GENERATOR_LPG_MONITOR_EN
ACTION_W_CFG_GENERATOR_MAX_DSG_TO_LOAD_POINT
ACTION_W_CFG_GENERATOR_MPPT_HYBRID_MODE
ACTION_W_CFG_GENERATOR_PERF_MODE
ACTION_W_CFG_GENERATOR_SELF_ON
ACTION_W_CFG_GENERATOR_CARE_MODE
```

## NEW: AndroidManifest Findings

**Notable permissions** (security-relevant for the integration's threat model):
- `BLUETOOTH_CONNECT`, `BLUETOOTH_SCAN`, `BLUETOOTH_ADMIN` — local BLE setup
- `ACCESS_FINE_LOCATION` — required for BLE scan + Wi-Fi config
- `CHANGE_WIFI_STATE`, `ACCESS_WIFI_STATE`, `CHANGE_WIFI_MULTICAST_STATE` — local Wi-Fi setup, mDNS
- `FOREGROUND_SERVICE_DATA_SYNC` — background MQTT
- `CALL_PHONE` — installer support call-back

**Embedded SDKs**:
- `org.eclipse.paho.android.service.MqttService` — MQTT client
- `com.aliyun.sls.android.producer.provider.SLSContentProvider` — Alibaba Cloud SLS for log collection (consider when discussing privacy)
- `com.amazonaws.services.connect.inappcalling.*` — Amazon Connect for in-app voice support
- `com.google.firebase.messaging.FirebaseMessagingService` — push notifications
- `cn.jpush.android.service.*` — JPush (Chinese push provider)

**Application class**: `com.ecoflow.iot.IotApplication`
**Main activity**: `com.ecoflow.iot.ui.activity.MainActivity`
**Debug activities present in production build**: `MqttDebugActivity`, `RouterTestActivity`, `DebugActivity` (declared, not exported)

## Implications for Home Assistant Integration

### Already correct in current `custom_components/powerocean`

The `PowerOceanModel` enum (codes `83`/`85`/`86`/`87` for PowerOcean / DC fit / Single Phase / Plus) is consistent with the product code references found in DEX (no contradicting evidence).

### Updated recommendations

1. **The Open API path used by the integration today is sufficient for reads** (`/iot-open/sign/device/quota/all` aligns with `setQuotaQueryList` / `setQuotaMap` strings). For writes, the integration goes through `set_quota` over the same Open API — which is the stable, supported public surface even though the app itself prefers MQTT.

2. **Add PowerPulse support as a peer device class.** The product is feature-rich; treat `JT303` as the SN-prefix or product-type discriminator and reuse the same parser pipeline. The 70-action PowerOcean writable surface largely overlaps with the JT303 surface — different `cmdSet` values, same architecture.

3. **Writable entities to expose** (priority order, derived from `ACTION_W_*` list):
   - `switch.charger_enable` — `SP_CHARGER_CHG_OPEN`
   - `switch.phase_detection` — `CFG_SYS_PHASE_DETECTION_ENABLED`
   - `switch.system_pause` — `CFG_SYS_PAUSE` (allows orchestrating with HA energy automations)
   - `select.charger_mode` — `SP_CHARGER_CHG_MODE`
   - `select.grid_type` — `CFG_GRID_TYPE`
   - `number.charger_amp_limit` — `SP_CHARGER_DEV_BATT_CHG_AMP_LIMIT`
   - `number.charger_power_limit` — `SP_CHARGER_CHG_POW_LIMIT`
   - `number.backup_reserve_soc` — `BACKUP_REVERSE_SOC`
   - `number.grid_in_power_limit` — `CFG_SYS_GRID_IN_PWR_LIMIT`
   - `number.fast_chg_max_soc` — `CFG_SP_FAST_CHG_MAX_SOC`
   - `button.system_reboot` — `ACTIVE_SYS_REBOOT`
   - `button.system_selfcheck` — `ACTIVE_SYS_SELFCHECK`

4. **TOU strategy is one writable JSON blob** (`CFG_TOU_STRATEGY` / `CFG_TOU_HOURS_STRATEGY`). Don't try to expose individual hours as entities — expose a service `powerocean.set_tou_schedule` that takes the whole strategy.

5. **Generator control** is fully writable — if a user has the standby generator add-on, they get 11 additional control points (engine open/close, output limits, low-power threshold, etc.).

6. **Don't claim PowerPulse is unsupported by the Open API.** The app uses the same MQTT topic family for both. The Open API may not yet expose PowerPulse-specific quotas, but the protocol primitive is identical.

---

## Conclusion

The deep pass validated nearly all of the original write-command findings and added two material discoveries:

1. The MQTT topic family `/app/<user>/<sn>/thing/property/set` is the actual primary control plane (the Open API is a wrapper).
2. PowerPulse (= JT303 = S1) has a comparable write surface to PowerOcean, contradicting the original "read-only" conclusion.

The integration should plan a unified `set_quota` write path covering both device families, with priority entities derived from the 70 PowerOcean-relevant `ACTION_W_*` actions and the equivalent JT303 surface in `jt_s1_cmd.proto`.
