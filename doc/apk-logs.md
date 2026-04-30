# APK Analysis Execution Logs

**Date**: 2026-04-30
**APK Path**: `/mnt/c/code/powerocean/doc/EcoFlow_6.13.8.2_APKPure/com.ecoflow.apk` (332 MB)
**App Version**: EcoFlow 6.13.8.2
**Analyst host**: WSL Ubuntu (Linux 6.6.87.2-microsoft-standard-WSL2)
**Tools used**: `python3 3.13.5` (zipfile, struct), no external apktool/jadx/strings — DEX parser written inline.

Raw outputs from this run are also saved under [doc/logs/](logs/):
- `raw_endpoints.txt` — 430 candidate URL paths
- `raw_action_w_all.txt` — 496 unique `ACTION_W_*` writes (app-wide)
- `raw_action_w_powerocean.txt` — 70 PowerOcean-relevant subset
- `raw_po_field_numbers.txt` — 1,851 protobuf `_FIELD_NUMBER` constants
- `raw_po_writable_fields.txt` — 784 PowerOcean-relevant protobuf field constants
- `raw_jt303_powerpulse.txt` — 1,170 JT303/PowerPulse strings
- `raw_proto_files.txt` — 100 distinct `.proto` filenames referenced in DEX

---

## Pass 1 (initial, file-system level) — 2026-04-30 morning

### Execution 1: APK Structure Analysis

```
Found 1622 matching files:
  META-INF/version-control-info.textproto
  assets/321/bg/device_bg.json
  assets/ac305_add_device_ani.json
  assets/ac305_add_device_ani_images/img_0.png
  assets/bk620_energy_flow/house_device_home_lottie.json
  assets/bk621_energy_flow/device_to_grid_lottie.json
  ...
Total files: 15780
Top directories: META-INF, assets, com, firebase, google, kotlin, okhttp3, org, res
Total .class files: 0    ← code is in DEX, not classes
```

### Execution 2: Proto Files (file-system extracted)

```
Found 22 proto files:
  client_analytics.proto
  devices.proto                       ← Google Matter scaffold (NOT EcoFlow)
  devices_state.proto                 ← Google Matter scaffold (NOT EcoFlow)
  esp_local_ctrl.proto                ← ESP-Rainmaker SDK (NOT EcoFlow)
  esp_rmaker_claim.proto
  esp_rmaker_user_mapping.proto
  firebase/perf/v1/perf_metric.proto
  google/protobuf/*.proto              ← 11 standard Google
  messaging_event.proto
  messaging_event_extension.proto
  user_prefs.proto
```

> **Pass-2 correction**: 22 file-system protos is misleading. EcoFlow's proprietary protos (~80 of them: `po_edev*`, `jt_s1_*`, `cp307_*`, `dc303_*`, etc.) are compiled into DEX bytecode and only their *names* show up in DEX strings — see Pass 2 §4.

### Execution 3: DEX File Inventory

48 DEX files (`classes.dex` through `classes48.dex`), aggregate ~210 MB of compiled Kotlin/Java.

### Execution 4–6: Initial keyword survey

| Search                         | Hits  | Note |
|--------------------------------|-------|------|
| `powerocean` / `powerOcean`    | 624   | (Pass 2 raised to 667 with broader regex) |
| `powerpulse`                   | 11    | **Misleading low count** — see Pass 2 §3 |
| `cmdSet:` / `cmdId:`           | 224   | confirmed parameter system |
| `ACTION_W_*` (full)            | n/a in pass 1 | (Pass 2: 991 / 496 unique) |

---

## Pass 2 (deep, DEX string-table parse) — 2026-04-30 afternoon

### Setup

```bash
mkdir -p /tmp/apk_work
python3 -c "
import zipfile
apk='/mnt/c/code/powerocean/doc/EcoFlow_6.13.8.2_APKPure/com.ecoflow.apk'
with zipfile.ZipFile(apk) as z:
    for n in z.namelist():
        if n.endswith('.dex'):
            z.extract(n, '/tmp/apk_work/')
"
```

DEX string-table extractor (parses ULEB128 length + MUTF-8 strings from each `.dex` header):

```python
import struct
def parse_dex_strings(dex_path):
    with open(dex_path, 'rb') as f:
        if not f.read(8).startswith(b'dex\n'): return []
        f.seek(0x38)
        string_ids_size = struct.unpack('<I', f.read(4))[0]
        string_ids_off = struct.unpack('<I', f.read(4))[0]
        f.seek(string_ids_off)
        offs = [struct.unpack('<I', f.read(4))[0] for _ in range(string_ids_size)]
        out = []
        for off in offs:
            f.seek(off)
            length = 0; shift = 0
            while True:
                b = f.read(1)[0]
                length |= (b & 0x7f) << shift
                if b < 0x80: break
                shift += 7
            data = b''
            while True:
                b = f.read(1)
                if b == b'\x00' or b == b'': break
                data += b
            out.append(data.decode('utf-8', errors='replace'))
        return out
```

Output:

```
Total unique strings: 539948
Saved to /tmp/apk_work/all_strings.txt   (~75 MB raw)
```

### §1 — API Endpoint Surface

**Command**:
```
grep -E "^/(provider-service|iot|app-service|cms-service|api|open-api)" \
  /tmp/apk_work/endpoints.txt | sort -u
```

**Result** — 430 candidate URL paths total. Buckets:
- 156 `/iot-service/...` (REST device service)
- ~60 `/iot-devices/...` (device CRUD)
- ~60 `/provider-service/...` (installer portal)
- 4 `/iot-open/...` (the public Open API surface)

**Production hosts** (from string literals):
```
https://api.ecoflow.com
https://api-e.ecoflow.com
https://api-a.ecoflow.com
https://api-cn.ecoflow.com
https://iot-ecoflow.com
ecoflow-service-test-cdn.ecoflow.com
```

**Notable PowerOcean / device endpoints**:
```
/iot-open/sign/device/list                       ← Open API (community-used)
/iot-open/sign/device/quota/all                  ← Open API (community-used)
/iot-quota/device/quota/batch/get
/iot-shadow/cmd/issue/device                     ← device-shadow command issue
/iot-shadow/cmd/issue/homepageDevice
/iot-devices/device/setDeviceProperty
/iot-devices/device/setDevicePropertyWithPower
/iot-devices/device/getDeviceProperty
/iot-service/dashboard/platform/getSystemDeviceList
/iot-service/dashboard/platform/getSystemDeviceInfoListBySn
/provider-service/app/device/property
/provider-service/app/device/list
```

**PowerPulse REST surface** (only two — most flow through MQTT):
```
/provider-service/user/app/powerpulse/report/list
/provider-service/user/app/powerpulse/report/summery
```

Full list: [doc/logs/raw_endpoints.txt](logs/raw_endpoints.txt).

### §2 — MQTT Topic Templates (NEW high-value finding)

**Command**:
```
grep -E "/thing/property/" /tmp/apk_work/all_strings.txt | sort -u
```

**Result**:
```
/app/%s/%s/thing/property/get
/app/%s/%s/thing/property/get_reply
/app/%s/%s/thing/property/set
/app/%s/%s/thing/property/set_reply
/app/%s/+/thing/property/                ← MQTT wildcard subscription
/app/%s/+/thing/property/get_reply
/app/%s/+/thing/property/set_reply
/ep/%s/%s/thing/property/get
/ep/%s/%s/thing/property/get_reply
/ep/%s/%s/thing/property/set
/ep/%s/%s/thing/property/set_reply
/ep/%s/+/thing/property/
/ep/%s/+/thing/property/get_reply
/ep/%s/+/thing/property/set_reply
/app/%s/%d/biz/data/notify
/app/%s/%d/biz/data/request
/app/%s/%d/biz/data/response
/app/%s/message/push
/shelly/thing/property/post/
```

Format: `<userId>` then `<deviceSn>`. `+` is single-level wildcard. `/ep/...` are sub-device endpoints.

**Eclipse Paho MQTT** registered in AndroidManifest:
```
org.eclipse.paho.android.service.MqttService
```

### §3 — PowerPulse / JT303 deep dive (correction to Pass 1)

**Pass 1 error**: searched for literal `powerpulse` only → 11 hits → concluded "minimal".

**Pass 2 correction**: PowerPulse's engineering name is **JT303** (filed under family **S1**). Re-search:

```
grep -iE "jt303|powerpulse" /tmp/apk_work/all_strings.txt | wc -l
→ 1170
```

Categories present (regex `^jt303_(\w+)_` extracted via `awk -F_ '{print $2}'`):
```
14a, 3rd, 4g, afci, ai, automation, backup, bat, battery, bind, cdz, charge,
check, circuit, commission, cooling, country, cp307, ct501, custom, customize,
device, energy, err, ethernet, ev, export, firmware, ft308, ft323, generation,
grid, heat, heating, hp, import, inverter, italy, light, mode, network, oil,
peakingshaving, phase, popup, scene, setting, smart, solar, system, tou
```

This is a fully-featured device — comparable scope to PowerOcean.

**Class structure**:
```
com.ecoflow.jtmodule          ← top-level Kotlin module
com.ecoflow.jtmodule.s1       ← S1 / JT303 dashboard, settings, popups
com.ecoflow.jtmodule.s1.detail.charger.cp307
com.ecoflow.jtmodule.s1.dashboard.{backup,heatrod,powerheat}
com.ecoflow.jtmodule.s1.detail.dialog
com.ecoflow.jtmodule.dc       ← DC charger (DC303)
com.ecoflow.jtmodule.dc.proto.dc303
com.ecoflow.jtmodule.proto    ← compiled .proto descriptors
```

**BLE command surface**:
```
com/ecoflow/common/command/JT303BleCommand
com/ecoflow/common/command/JT303BleCommand$getBaseParallelDevList$1$1
com/ecoflow/common/helper/JT303DataHelper
com/ecoflow/common/helper/JT303DataParseHelper
com/ecoflow/common/helper/JT303MergeDataHelper
```

Filenames referenced in stack traces:
```
JT303BleCommand.kt
JT303DataHelper.kt
JT303DataParseHelper.kt
JT303MergeDataHelper.kt
```

**Settings entry point**: `/S1InstallerApp/Jt303SettingsActivity` (route registered in `TheRouter` JSON config).

### §4 — Proto File Inventory (DEX-referenced ≠ file-system extracted)

**Command**:
```
grep -oE '[a-z][a-z0-9_]+\.proto' /tmp/apk_work/all_strings.txt | sort -u
→ 100 distinct .proto names
```

**EcoFlow proprietary protos** (compiled into DEX, not extractable as files):

PowerOcean / SHP family:
```
po_edev.proto              ← PowerOcean ecology device
po_edev_cmd.proto          ← PowerOcean device commands
re307_sys.proto            ← RE306/RE307 panel
pd303.proto                ← Smart Home Panel 2
pd335_sys.proto, pd335_bms_bp.proto
```

PowerPulse / JT303 / S1 family:
```
jt_s1_sys.proto
jt_s1_cmd.proto
jt_s1_ev.proto             ← EV charging integration
jt_s1_ecology_dev.proto
jt_s1_edev.proto
jt_s1_edev_convert.proto
jt_s1_heatingrod.proto
jt_s1_heatpump.proto
jt_s1_parallel.proto       ← cascading master/slave
jt_s1_bat_health.proto
jt_s1_sys_re307.proto
jt_14a.proto
jt_parallel_lan.proto
jt_wn_socket.proto
```

CP307 EV charger family:
```
cp307_iot.proto
cp307_sys.proto
cp307_ocpp.proto           ← OCPP 1.6/2.0 support (open charge point protocol)
cp307_14a.proto
```

DC charger / others:
```
dc303_sys.proto, dc303_cmd.proto
ft308_sys.proto, ft308_cmd.proto
ge305_sys.proto
bk_series.proto, bk622_common.proto, bk_diagnosis.proto
ac517_apl_comm.proto, dc009_apl_comm.proto, dc013_apl_comm.proto
generator_wireless_sys.proto
fd100_sys.proto, pr705.proto
yj751_*.proto              ← DELTA Pro 3 / new portable PSU family
wn511_*.proto              ← WN511 socket
```

Common framework:
```
iot_comm.proto, iot_config.proto
bms_cloud.proto, battery_info_sys.proto
ble.proto, ble_crt_info.proto, bluetooth.proto
efsettings.proto, wifi_memory.proto, net_diagnosis.proto
auto_task.proto, x_log.proto
```

Full list: [doc/logs/raw_proto_files.txt](logs/raw_proto_files.txt).

### §5 — Writable action surface

**Command**:
```
grep -E "^ACTION_W_" /tmp/apk_work/all_strings.txt | grep -v "_VALUE$" | sort -u
→ 496 unique writable actions (app-wide, all device types)
```

**Filtered to PowerOcean-relevant**:
```
grep -E "ACTION_W_(CFG_SP_|CFG_PCS_|CFG_BMS_|CFG_BACKUP_|CFG_BREAK|CFG_PV|
                    CFG_GRID|CFG_BAT|CFG_INV|CFG_VPP|CFG_TOU|CFG_PHASE|
                    CFG_AC_OUT_|CFG_ATS|CFG_SYS_|CFG_TIME|CFG_GENE|
                    ACTIVE_TIME_TASK|ACTIVE_SYS_REBOOT|ACTIVE_SYS_SELF|
                    ACTIVE_SELECTED_TIME)" \
  /tmp/apk_work/action_w_all.txt
→ 70 actions
```

Top-value sample (full list in [doc/logs/raw_action_w_powerocean.txt](logs/raw_action_w_powerocean.txt)):

```
ACTION_W_ACTIVE_SELECTED_TIME_TASK_V2
ACTION_W_ACTIVE_SYS_REBOOT
ACTION_W_ACTIVE_SYS_SELFCHECK
ACTION_W_CFG_BACKUP_BOX_MODE
ACTION_W_CFG_BACKUP_REVERSE_SOC
ACTION_W_CFG_BACKUP_SOC_VPP
ACTION_W_CFG_GENERATOR_ENGINE_OPEN          ← generator start/stop!
ACTION_W_CFG_GENERATOR_AC_OUT_POW_MAX
ACTION_W_CFG_GENERATOR_DC_OUT_POW_MAX
ACTION_W_CFG_GENERATOR_LOW_POWER_EN
ACTION_W_CFG_GENERATOR_LOW_POWER_THRESHOLD
ACTION_W_CFG_GENERATOR_LPG_MONITOR_EN
ACTION_W_CFG_GENERATOR_PERF_MODE
ACTION_W_CFG_GRID_CHARGE_TO_BATTERY_ENABLE
ACTION_W_CFG_GRID_CONNECTION_FREQ_SETTING
ACTION_W_CFG_GRID_CONNECTION_POWER_FACTOR_SETTING
ACTION_W_CFG_GRID_CONNECTION_POWER_SETTING
ACTION_W_CFG_GRID_CONNECTION_VOL_SETTING
ACTION_W_CFG_GRID_TYPE
ACTION_W_CFG_INV_TARGET_PWR
ACTION_W_CFG_INV_TARGET_VOL
ACTION_W_CFG_PCS_SHUTDOWN_CTRL
ACTION_W_CFG_PV_CHG_TYPE
ACTION_W_CFG_PV_DC_CHG_SETTING
ACTION_W_CFG_PV_METER_IN_FLAG
ACTION_W_CFG_SP_CHARGER_AUTO_CHG_OPEN
ACTION_W_CFG_SP_CHARGER_AUTO_CHG_VOL_MIN
ACTION_W_CFG_SP_CHARGER_AUTO_REVERSE_CHG_VOL_MIN
ACTION_W_CFG_SP_CHARGER_CAR_BATT_CHG_AMP_LIMIT
ACTION_W_CFG_SP_CHARGER_CAR_BATT_TYPE
ACTION_W_CFG_SP_CHARGER_CHG_MODE
ACTION_W_CFG_SP_CHARGER_CHG_OPEN
ACTION_W_CFG_SP_CHARGER_CHG_POW_LIMIT
ACTION_W_CFG_SP_CHARGER_DEV_BATT_CHG_AMP_LIMIT
ACTION_W_CFG_SP_CHARGER_DEV_BATT_TYPE
ACTION_W_CFG_SP_FAST_CHG_MAX_SOC
ACTION_W_CFG_TOU_STRATEGY
```

### §6 — `_FIELD_NUMBER` proto field constants

**Command**:
```
grep -E "_FIELD_NUMBER" /tmp/apk_work/all_strings.txt \
  | grep -iE "sp_|shp|grid|backup|pv|bms|inv|tou|pcs|ats|gen_|sys_|wifi|cfg" \
  | sort -u
→ 1851 unique
```

Saved: [doc/logs/raw_po_field_numbers.txt](logs/raw_po_field_numbers.txt) (full) and [raw_po_writable_fields.txt](logs/raw_po_writable_fields.txt) (filtered to writable categories).

These confirm the read surface is far richer than the integration's current 30-ish sensor map.

### §7 — `cmdSet` / `cmdId` parameter system

**Command**:
```
grep -iE "cmdSet=|cmdId=" /tmp/apk_work/all_strings.txt | grep -v "_VALUE$" | sort -u
```

**Format-string fragments found** (these confirm how requests are constructed):
```
ParamsDTO{cmdSet=
CmdInfo(cmdSet=
parseDeviceData: cmdSet=
JT303DataParseData: cmdSet=
Dc303DataParseData: cmdSet=
sendCommand: cmdId=0x
transferBleData_payload cmdSet=
[配网响应] 收到配网相关指令: cmdSet=        ← Chinese: "[provisioning response] received provisioning command: cmdSet="
创建设备命令: cmdSet=0x                 ← Chinese: "create device command: cmdSet=0x"
```

The format `cmdSet=0x...` confirms hex command codes; `cmdId=0x...` confirms hex sub-IDs. This matches the OpenAPI request schema `{"cmdSet": N, "cmdId": M, "params": {...}}`.

### §8 — AndroidManifest.xml (binary XML)

Parsed UTF-16LE strings from the binary AndroidManifest:

**Permissions of interest**:
```
android.permission.INTERNET
android.permission.ACCESS_NETWORK_STATE / WIFI_STATE
android.permission.CHANGE_WIFI_STATE / CHANGE_WIFI_MULTICAST_STATE
android.permission.BLUETOOTH / BLUETOOTH_ADMIN / BLUETOOTH_CONNECT / BLUETOOTH_SCAN
android.permission.ACCESS_FINE_LOCATION / ACCESS_COARSE_LOCATION
android.permission.FOREGROUND_SERVICE / FOREGROUND_SERVICE_DATA_SYNC
android.permission.CALL_PHONE
android.permission.CAMERA
android.permission.FLASHLIGHT
```

**Embedded SDKs**:
```
org.eclipse.paho.android.service.MqttService
com.aliyun.sls.android.producer.provider.SLSContentProvider     ← Alibaba Cloud SLS (logging)
com.amazonaws.services.connect.inappcalling.*                    ← Amazon Connect (in-app voice support)
com.google.firebase.messaging.FirebaseMessagingService
cn.jpush.android.service.*                                       ← JPush (Chinese push)
```

**Application class**: `com.ecoflow.iot.IotApplication`
**Main entry**: `com.ecoflow.iot.ui.activity.SplashActivity` → `MainActivity`
**Debug surfaces declared (not exported)**:
```
com.ecoflow.iot.debug.ui.DebugActivity
com.ecoflow.iot.debug.ui.MqttDebugActivity     ← in-app MQTT broker tester
com.ecoflow.iot.debug.ui.RouterTestActivity
```

### §9 — Route map (TheRouter)

JSON literal embedded in DEX maps deep-link paths to activity classes. PowerOcean section excerpt:

```json
[{"path":"/powerOcean/POOutageHistoryActivity","className":"com.ecoflow.po.sapce.dashboard.POOutageHistoryActivity"},
 {"path":"/powerOcean/PONewDashboardActivity","className":"com.ecoflow.po.sapce.dashboard.PONewDashboardActivity"},
 {"path":"/powerOcean/PODashboardActivity","className":"com.ecoflow.po.sapce.dashboard.PODashboardActivity"},
 {"path":"/powerOcean/SHPInitGuideATSActivity","className":"com.ecoflow.po.ats.initialization.SHPInitProActivity"},
 {"path":"/powerOcean/SHPInitGuideActivity","className":"com.ecoflow.po.ats.initialization.SHPInitGuideActivity"},
 {"path":"/powerOcean/installer/SceneSettingActivity","className":"com.ecoflow.installer.setting.scene.PoSceneSettingActivity"},
 {"path":"/powerOcean/SettingsActivity","className":"com.ecoflow.installer.setting.PoSettingsActivity"},
 {"path":"/powerOcean/SettingGridActivity","className":"com.ecoflow.installer.setting.PoGridSettingActivity"},
 {"path":"/powerOcean/PoEnergySettingActivity","className":"com.ecoflow.installer.setting.PoEnergySettingActivity"},
 {"path":"/powerOcean/SelfTestActivity","className":"com.ecoflow.installer.selftest.PoSelfCheckActivity"},
 {"path":"/powerOcean/PoNetWorkDetectionActivity","className":"com.ecoflow.installer.network.PoNetworkDetectionActivity"},
 {"path":"/powerOcean/POMainActivity","className":"com.ecoflow.installer.main.PoInstallMainActivity"},
 {"path":"/powerOcean/POInstallInitActivity","className":"com.ecoflow.installer.init.PoInstallInitActivity"},
 {"path":"/powerOcean/SystemDevicesActivity","className":"com.ecoflow.installer.device.SystemDevicesActivity"},
 {"path":"/powerOcean/StandbyGeneratorActivity","className":"com.ecoflow.installer.device.StandbyGeneratorActivity"},
 {"path":"/powerOcean/InstallationRecordActivity","className":"com.ecoflow.common.installation.InstallationRecordActivity"},
 ...]
```

This confirms `SHP*` (Smart Home Panel) screens are integrated under the PowerOcean route namespace — they share an installer flow.

### §10 — `EcoDevCmdSets` enum

Three independent `EcoDevCmdSets` enums exist (one per device family):

```
com/ecoflow/common/proto/PoEdevCmd$EcoDevCmdSets       ← PowerOcean
com/ecoflow/jtmodule/proto/JtS1Edev$EcoDevCmdSets      ← JT303 / S1 (PowerPulse)
com/ecoflow/jtmodule/proto/JtS1EcologyDev$EcoDevCmdSets ← JT303 ecology devices
```

The enum values are not exposed in string form (they're protobuf enum integers). To extract them, `dex2jar`/`jadx` would be needed — out of scope for this string-only pass. The presence of three independent enums confirms each family has its own `cmdSet` numbering namespace.

---

## Pass 2 result summary

| Surface                               | Count    | Diff vs. Pass 1            |
|---------------------------------------|----------|----------------------------|
| Total unique DEX strings              | 539,948  | (not measured in Pass 1)   |
| URL endpoint candidates               | 430      | new                        |
| `/iot-service/*` endpoints            | 156      | new                        |
| `ACTION_W_*` actions (unique)         | 496      | new (Pass 1 found ~3)      |
| PowerOcean-targeted `ACTION_W_*`      | 70       | new                        |
| `_FIELD_NUMBER` constants (PO subset) | 1,851    | new                        |
| MQTT topic templates                  | 14       | new                        |
| Proto files referenced in DEX         | 100      | up from 22 (5x undercount) |
| PowerPulse / JT303 strings            | 1,170    | up from 11 (105x undercount) |

The deep pass changed two conclusions material to the Home Assistant integration:
1. **PowerPulse is feature-complete and writable**, not a read-only stub.
2. **The MQTT topic family `/app/<user>/<sn>/thing/property/set` is the underlying control plane**; the Open API is the supported public façade, but understanding the MQTT layer matters for diagnosing latency / ack issues.

---

## Reproducing the analysis

```bash
# 1. Extract DEX files to /tmp/apk_work/
python3 -c "
import zipfile
apk='/path/to/com.ecoflow.apk'
with zipfile.ZipFile(apk) as z:
    [z.extract(n, '/tmp/apk_work/') for n in z.namelist() if n.endswith('.dex')]
"

# 2. Run the inline DEX string parser (see Pass 2 §Setup) and write to all_strings.txt

# 3. Bucket-search:
grep -iE "powerocean|powerOcean" /tmp/apk_work/all_strings.txt | sort -u > po.txt
grep -iE "jt303|powerpulse" /tmp/apk_work/all_strings.txt | sort -u > pp.txt
grep -E "^ACTION_W_" /tmp/apk_work/all_strings.txt | grep -v _VALUE$ | sort -u > writes.txt
grep -E "_FIELD_NUMBER" /tmp/apk_work/all_strings.txt | sort -u > fields.txt
grep -oE '[a-z][a-z0-9_]+\.proto' /tmp/apk_work/all_strings.txt | sort -u > protos.txt
grep -E "/thing/property/" /tmp/apk_work/all_strings.txt | sort -u > mqtt_topics.txt
```

For an even deeper pass (proto schema reconstruction, `EcoDevCmdSets` enum values, full Kotlin source recovery), use `jadx -d out com.ecoflow.apk` — that pulls full method bodies, not just string tables. Not done here because the string-table evidence was sufficient to validate and extend the original findings.
