# EcoFlow PowerOcean for Home Assistant

[![GitHub release](https://img.shields.io/github/release/niltrip/powerocean?include_prereleases=&sort=semver&color=blue)](https://github.com/niltrip/powerocean/releases/)
[![issues - powerocean](https://img.shields.io/github/issues/niltrip/powerocean)](https://github.com/niltrip/powerocean/issues)
[![GH-code-size](https://img.shields.io/github/languages/code-size/niltrip/powerocean?color=red)](https://github.com/niltrip/powerocean)
[![GH-last-commit](https://img.shields.io/github/last-commit/niltrip/powerocean?style=flat-square)](https://github.com/niltrip/powerocean/commits/main)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![HACS validation](https://github.com/niltrip/powerocean/workflows/Validate/badge.svg)](https://github.com/niltrip/powerocean/actions?query=workflow:"Validate")
![installation_badge](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=integration%20usage&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.powerocean_dev.total)

[Home Assistant](https://home-assistant.io/) custom component for EcoFlow **PowerOcean** hybrid inverter systems and the attached **PowerPulse** EV charger.

Cloud-polling integration: no local MQTT broker, no API key, no router setup. Authenticates against the EcoFlow consumer cloud with your app credentials and exposes the full sensor + control surface to Home Assistant.

> **Note on screenshots:** the inline screenshots in this repo (under `documentation/`) date from the original PowerOcean integration and **predate** the auto-detect config flow, the PowerPulse sub-device, and the OCPP options/services added in 2026.05. They will be refreshed in a future release; the textual setup walkthrough below is authoritative.

---

## Features

- **Auto-detection config flow** — log in with email + password, the integration discovers your PowerOcean devices, no serial-number lookup needed
- **60+ sensors** — power, energy, voltage, current, temperature, SoC, SoH, inverter heartbeat, MPPT strings, EMS counters
- **Energy Dashboard** — grid import/export, solar yield, battery charge/discharge, all auto-discovered
- **PowerPulse EV charger as a sub-device** — appears as its own HA device under the inverter, with its own settable entities (charger enable, mode, current/power limits, automatic charging)
- **PowerGlow heating rod** — temperature + power sensors when present
- **Battery sub-devices** — one HA device per battery pack with SoC, SoH, voltage, current, cycles, temperatures
- **Write controls** — backup reserve SoC, fast-charge cap, charger power/current/mode, grid import limit, battery heating, EV charger enable/auto, system pause/reboot/self-check
- **Services** — `set_tou_schedule`, `set_grid_type`, plus three OCPP catalog services for PowerPulse (see below)
- **Migration** — automatically imports entries from the legacy `powerocean` integration on first load
- **Multi-language** — English, German, French UI

---

## Supported hardware

| Device | Model code | Notes |
|---|---|---|
| PowerOcean | 83 | Three-phase hybrid inverter |
| PowerOcean DC Fit | 85 | DC-coupled retrofit |
| PowerOcean Single Phase | 86 | Single-phase variant |
| PowerOcean Plus | 87 | Higher-power three-phase |
| PowerOcean Battery | — | Auto-discovered as sub-device |
| PowerPulse 11 kW (CP307 / JT303) | — | Auto-discovered as sub-device when bound to the inverter |
| PowerGlow heating rod | — | Auto-discovered as sub-device |

PowerPulse and PowerGlow are not standalone — they must be bound to a PowerOcean inverter in the EcoFlow app and polled through the inverter's serial number. See [`doc/README.md`](doc/README.md) for the architecture rationale and the OCPP-only path for charger-only setups.

---

## Installation

### HACS (recommended)

1. Open HACS → Integrations → Custom repositories
2. Add `https://github.com/niltrip/powerocean` with category **Integration**
3. Search for **EcoFlow PowerOcean** and install
4. Restart Home Assistant

### Manual

1. Download the latest release and extract `custom_components/powerocean_dev`
2. Copy it into `<config>/custom_components/powerocean_dev/`
3. Restart Home Assistant

---

## Setup

**Settings → Devices & Services → Add Integration → EcoFlow PowerOcean**.

1. **Credentials.** Enter your EcoFlow account email + password. The integration authenticates against the EcoFlow cloud and probes the EU and US regions automatically.
2. **Device selection.** Auto-detected PowerOcean devices appear in a drop-down (`<name> — <model> (<sn>)`). If detection returns nothing — unsupported region, locked account, transient API change — the form falls back to manual serial-number + model-code entry.
3. **Device options.** Optional friendly name and polling interval (10–60 s, default 10 s).

After setup the inverter, each battery, the PowerPulse charger, and the PowerGlow heater appear as separate HA devices, all linked via `via_device` to the inverter.

### OCPP options (PowerPulse only, optional)

After the entry is created, **Configure → OCPP** lets you store the connection details for a third-party OCPP 1.6 central system (the [lbbrhzn/ocpp HACS integration](https://github.com/lbbrhzn/ocpp) is the supported host). These options are only stored — the actual catalog write to the EcoFlow cloud is performed via the [OCPP services](#ocpp-services) below.

---

## Migration from the original integration

If you are already running the original `niltrip/powerocean` custom integration, `powerocean_dev` will detect your existing config entries on first load and import them automatically — no manual re-entry. The original entries are left untouched; you can remove them once you have verified the new integration works.

---

## Entities

### Settable controls

| Entity | Type | Device | Description |
|---|---|---|---|
| Backup Reserve SoC | number | Inverter | Minimum battery SoC before grid draw |
| Fast Charge Upper Limit | number | Inverter | Maximum SoC during fast charge |
| Grid Import Power Limit | number | Inverter | Cap on grid draw (W) |
| Charger Mode | select | Inverter | Automatic / Fast / Economy |
| Backup Mode | select | Inverter | Self-use / Backup / Off |
| Grid Charging | switch | Inverter | Enable / disable charging from the grid |
| System Pause | switch | Inverter | Pause / resume the inverter |
| Battery Heating | switch | Inverter | Enable cell heating (sub-zero climates) |
| Reboot System | button | Inverter | Trigger a system reboot |
| Run Self-check | button | Inverter | Trigger a self-check cycle |
| Charger Power Limit | number | PowerPulse | Max output power (W) |
| Charger Current Limit | number | PowerPulse | Max AC charging current (6–32 A) |
| EV Charger | switch | PowerPulse | Enable / disable PowerPulse |
| Automatic EV Charging | switch | PowerPulse | TOU / solar-priority auto mode |

Read-only sensor coverage (≈60 sensors plus binary sensors per inverter, plus battery and PowerPulse sensors per sub-device) is exhaustive — see `custom_components/powerocean_dev/strings.json` for the full list with friendly names.

---

## Services

### `powerocean_dev.set_tou_schedule`

Write a Time-of-Use strategy as a JSON blob to the inverter (`cfgTouStrategy`).

```yaml
service: powerocean_dev.set_tou_schedule
data:
  schedule: '{"cfgTouStrategy": ...}'
```

### `powerocean_dev.set_grid_type`

Switch between single-phase (`0`) and three-phase (`1`) grid connection.

```yaml
service: powerocean_dev.set_grid_type
data:
  grid_type: 1
```

### OCPP services

PowerPulse natively supports OCPP 1.6, and EcoFlow exposes endpoints to point the charger at a third-party central system. These three services manage the EcoFlow-side **catalog** of OCPP backends.

> **Important caveat.** The catalog write alone does not redirect the charger at runtime — that handover requires an additional proto write (`vendorInfoSet`) which is not yet shipped. Use these services to pre-stage your account, inspect existing entries, and discover the `platformType` enum empirically; the runtime switch will land in a follow-up release.

#### `powerocean_dev.ocpp_list_backends`

Read the OCPP platform-config catalog from your EcoFlow account. Returns each record verbatim (id, sn, platformCode, backendUrl, isEnabled, …).

```yaml
service: powerocean_dev.ocpp_list_backends
response_variable: ocpp
```

#### `powerocean_dev.ocpp_register_backend`

Register an OCPP central system in the EcoFlow catalog with `isEnabled=1`.

```yaml
service: powerocean_dev.ocpp_register_backend
data:
  backend_url: ws://homeassistant.local:9000
  # sn auto-detected from the PowerPulse device on this entry
  # platform_code defaults to "lbbrhzn"
  # platform_name defaults to "HA lbbrhzn/ocpp"
  # platform_type defaults to 0
  # auth_key empty → OCPP 1.6 security profile 0 (unauthenticated)
```

#### `powerocean_dev.ocpp_disable_backend`

Mark an existing record as inactive (`isEnabled=0`). EcoFlow exposes no DELETE endpoint; this is the documented "tidy" path.

```yaml
service: powerocean_dev.ocpp_disable_backend
data:
  backend_url: ws://homeassistant.local:9000
```

---

## Troubleshooting

Enable debug logging during initial setup:

```yaml
logger:
  default: warn
  logs:
    custom_components.powerocean_dev: debug
```

Key log messages:

| Message | Meaning |
|---|---|
| `EMS heartbeat missing 'pcsMeterPower'` | Grid-flow sensors will read 0 W until the field appears |
| `EMS heartbeat missing 'emsBpPower'` | Battery-flow sensors will read 0 W |
| `House consumption is negative` | Possible meter sign-convention mismatch — check wiring |
| `Using mocked API response` | Test mode is active (`USE_MOCKED_RESPONSE = True` in `const.py`) |
| `PowerPulse serial number not found` | `ocpp_*` service called but no PowerPulse on this entry — pass `sn:` explicitly |

If you see `cannot_connect` during setup: confirm the credentials work in the EcoFlow mobile app, then retry. The integration probes both EU and US regions automatically.

---

## Documentation

The architecture quick-reference and pointers into the source tree live in [`doc/README.md`](doc/README.md). Reverse-engineering notes, decompiled artefacts, vendor PDFs, and the personal-data reference installation file have been removed for legal reasons; see the same file for context.

The integration code itself is the authoritative reference for protocol details — the API endpoints, write-side parameter names, and OCPP request schema are inlined where they are used (`api.py`, `const.py`, `__init__.py`, `services.yaml`).

---

## Credits

- Primary inspiration: [niltrip/powerocean](https://github.com/niltrip/powerocean)
- Original concept: [tolwi/hassio-ecoflow-cloud](https://github.com/tolwi/hassio-ecoflow-cloud)
- Inspired by: [evercape/hass-resol-KM2](https://github.com/evercape/hass-resol-KM2)
- Thanks to the Home Assistant community and all contributors
