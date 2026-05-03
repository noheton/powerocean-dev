# OCPP 1.6 — Investigation Playbook

This file is the prep work for adding an OCPP-backend config flow to PowerPulse. The goal is to capture the request/response schema for `/provider-service/app/ocppPlatformConfig` so we can build the flow without guessing field names.

## Why this is necessary

We've confirmed (see [apk.md § OCPP 1.6 support](apk.md#ocpp-16-support-cp307--powerpulse)) that CP307/PowerPulse supports OCPP and that EcoFlow exposes endpoints to point the charger at a custom central system. The screen in the EcoFlow app appears to be integrator-only, so a mitmproxy capture isn't feasible. The only remaining path is to dig the schema out of the decompiled APK.

The APK in `doc/EcoFlow_6.13.8.2_APKPure/com.ecoflow.apk` is stored in git-LFS. **You will need to run the steps below outside this sandbox** (Claude Code session in the cloud has no `git-lfs` / `apktool` / `jadx`).

## Prerequisites

```bash
# Pull the actual APK
git lfs install
git lfs pull --include="doc/EcoFlow_6.13.8.2_APKPure/com.ecoflow.apk"

# One of:
brew install jadx                  # macOS
# or
sudo apt install jadx              # Debian/Ubuntu
```

## Decompile

```bash
cd doc/EcoFlow_6.13.8.2_APKPure
jadx -d /tmp/ecoflow-jadx com.ecoflow.apk
# expect ~10-20 min, ~1.5 GB output
```

## Grep recipes

Run these against `/tmp/ecoflow-jadx/sources/` and paste interesting hits into a new file `doc/logs/raw_ocpp.txt`.

### 1. Endpoint constants and DTO names

```bash
grep -rn "ocppPlatformConfig\|ocpp/domain\|OcppPlatform\|OcppConfig" /tmp/ecoflow-jadx/sources/
```

Look for:
- A Retrofit/OkHttp interface declaring the call (annotation `@POST` / `@PUT` / `@GET` with the path).
- The request body class — usually a Kotlin data class or Java POJO with `@SerializedName` annotations giving JSON field names.

### 2. Request body fields

Once you have the DTO class name from step 1 (e.g. `OcppPlatformConfigReq`):

```bash
grep -rn "OcppPlatformConfigReq\|OcppPlatformConfig " /tmp/ecoflow-jadx/sources/ | head -50
# then read the file:
cat /tmp/ecoflow-jadx/sources/<path-to-class>.java
```

We expect to find some subset of:
- `url` / `serverUrl` / `wsUrl` (the OCPP central-system URL)
- `cpId` / `chargePointId` / `chargeBoxId` (the OCPP identity string)
- `authKey` / `password` / `token` (OCPP 1.6 security profile 1)
- `sn` (target charger serial)
- `vendor` / `model` / `name` (display fields)

### 3. UI layer — confirm integrator-only gating

```bash
grep -rn "ocpp" /tmp/ecoflow-jadx/resources/res/layout*/ /tmp/ecoflow-jadx/resources/res/values*/strings*.xml
```

Look for:
- A layout file (`*_ocpp_*.xml`) — confirms the screen exists in the APK.
- An `if`/`when` block referencing a role flag (`isInstaller`, `roleType`, etc.) before opening that screen — confirms gating.

### 4. Reset / fallback to EcoFlow cloud

```bash
grep -rn "resetOcpp\|defaultOcpp\|ecoflowOcpp\|ocpp.*default\|ocpp.*reset" /tmp/ecoflow-jadx/sources/
```

If nothing turns up, factory reset may be the only way back. **Document this as a user-facing warning before shipping the flow.**

### 5. The proto schema

```bash
find /tmp/ecoflow-jadx -name "Cp307Ocpp*" -o -name "*cp307_ocpp*"
```

The compiled `cp307_ocpp.proto` may give us OCPP-over-MQTT field shapes (status, last connection, etc.) — useful for read-only "OCPP connection state" sensors regardless of whether we ship the writer.

## What to capture in `doc/logs/raw_ocpp.txt`

Minimum to unblock implementation:

1. The exact HTTP method + path (`PUT /provider-service/app/ocppPlatformConfig`?).
2. The request JSON shape with field names and types.
3. The response shape (success envelope, error codes).
4. Whether `sn` is in the body, the URL, or in a separate "assign" call.
5. Any role/permission check found in step 3.

Once that's in, the config-flow implementation in `custom_components/powerocean_dev/config_flow.py` is a ~100-line addition modelled on the existing options flow, plus a thin API helper in `custom_components/powerocean_dev/api/` calling the endpoint with the existing bearer token.

## Implementation skeleton (for after the schema is captured)

Files to touch:

- `custom_components/powerocean_dev/api/` — add `set_ocpp_platform()` calling `PUT /provider-service/app/ocppPlatformConfig` with the captured body shape.
- `custom_components/powerocean_dev/config_flow.py` — add an `OptionsFlowHandler.async_step_ocpp` with the URL / CP-ID / auth-key form and the warning text.
- `custom_components/powerocean_dev/services.yaml` + `__init__.py` — register `set_ocpp_backend` service for scripting.
- `custom_components/powerocean_dev/strings.json` + `translations/*.json` — DE/FR/EN copy for the form and the warning.
- Unit tests: a new fixture `tests/fixtures/ocpp_platform_config.json` and a coordinator-level test verifying the request body matches the captured shape byte-for-byte.

Do **not** start any of this until `raw_ocpp.txt` exists.
