"""
PowerOcean integration for Home Assistant.

This module sets up the PowerOcean integration, handling:

- Initialization of the integration.
- Authentication and device setup via EcoFlow API.
- Migration of old config entries to new structure.
- Creation of a DataUpdateCoordinator for periodic polling.
- Registration in the Home Assistant device registry.
- Forwarding entry setups to sensor/platform components.
- Reloading the config entry when options are updated.

Functions:
- async_setup: Set up the integration and log basic info.
- async_setup_entry: Set up a PowerOcean device from a config entry.
- async_migrate_entry: Migrate older config entries to the latest version.
- async_unload_entry: Unload a config entry and clean up resources.
- update_listener: Reload a config entry when its options are updated.
"""

import json
from datetime import timedelta

import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_FRIENDLY_NAME,
    CONF_MODEL_ID,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
    IntegrationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import (
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    MODEL_NAME_MAP,
    PLATFORMS,
    PowerOceanModel,
)
from .ble_ocpp import async_ble_set_ocpp_url, async_find_charger_address
from .coordinator import PowerOceanCoordinator
from .ecoflow import HAEcoflowApi
from .parser import EcoflowParser


def _resolve_powerpulse_sn(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Return the PowerPulse serial number stored on the entry's endpoints."""
    endpoints = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("endpoints", {})
    inverter_sn = entry.data.get(CONF_DEVICE_ID)
    for ep_id, ep in endpoints.items():
        if ep.serial != inverter_sn and any(
            r in ep_id for r in ("EDEV_PARAM_REPORT", "EVCHARGING_REPORT")
        ):
            return ep.serial
    return None


def _build_ocpp_bind_req(
    data: dict, sn: str, enabled: bool
) -> dict[str, object]:
    """Construct a CPOcppBindReq dict from service data."""
    req: dict[str, object] = {
        "platformCode": data["platform_code"],
        "platformName": data["platform_name"],
        "platformType": data["platform_type"],
        "backendUrl": data["backend_url"],
        "secureUrl": data["secure_url"],
        "authKey": data["auth_key"],
        "sortOrder": data["sort_order"],
        "isEnabled": 1 if enabled else 0,
        "sn": sn,
    }
    if record_id := data.get("id"):
        req["id"] = record_id
    return req


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """
    Set up the PowerOcean integration.

    Args:
        hass (HomeAssistant): The Home Assistant instance.
        config (ConfigType): The configuration dictionary.

    Returns:
        bool: True if setup was successful, False otherwise.

    """
    # ── Auto-import from legacy powerocean domain ─────────────────────────────
    # When powerocean_dev is first loaded and the original powerocean integration
    # has existing entries, migrate them without user interaction.
    legacy_entries = hass.config_entries.async_entries("powerocean")
    existing_dev_sns = {
        e.data.get(CONF_DEVICE_ID) for e in hass.config_entries.async_entries(DOMAIN)
    }
    for old_entry in legacy_entries:
        sn = old_entry.data.get(CONF_DEVICE_ID)
        if sn and sn not in existing_dev_sns:
            import_data = {
                **old_entry.data,
                CONF_FRIENDLY_NAME: old_entry.options.get(
                    CONF_FRIENDLY_NAME, DEFAULT_NAME
                ),
                CONF_SCAN_INTERVAL: old_entry.options.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                ),
            }
            LOGGER.info(
                "Scheduling import of legacy powerocean entry for device %s", sn
            )
            hass.async_create_task(
                hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": SOURCE_IMPORT},
                    data=import_data,
                )
            )

    try:
        # Integration laden
        integration = await async_get_integration(hass, DOMAIN)

        # Zugriff auf manifest.json-Inhalte
        manifest = integration.manifest
        name = manifest.get("name", DOMAIN)
        version = manifest.get("version", "unknown")
        requirements = manifest.get("requirements", [])

        LOGGER.debug(
            "Loading %s v%s (requirements: %s)",
            name,
            version,
            requirements,
        )

    except KeyError as err:
        LOGGER.error("Missing expected key in integration manifest: %s", err)
        return False
    except HomeAssistantError as err:
        LOGGER.error("Home Assistant error during PowerOcean setup: %s", err)
        return False
    except Exception:
        LOGGER.exception("Unexpected error loading PowerOcean integration")
        raise

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PowerOcean from a config entry."""
    options = dict(entry.options)
    updated = False

    # Back-fill options that were missing from older config entries
    if CONF_SCAN_INTERVAL not in options:
        options[CONF_SCAN_INTERVAL] = entry.data.get("options", {}).get(
            "scan_interval", DEFAULT_SCAN_INTERVAL
        )
        updated = True

    if CONF_FRIENDLY_NAME not in options:
        options[CONF_FRIENDLY_NAME] = entry.data.get("options", {}).get(
            "friendly_name", DEFAULT_NAME
        )
        updated = True

    if updated:
        hass.config_entries.async_update_entry(entry, options=options)
        LOGGER.debug("Migrated missing options for %s: %s", entry.title, options)

    # Validate required config keys
    device_id = entry.data.get(CONF_DEVICE_ID)
    model_id = entry.data.get(CONF_MODEL_ID)
    if not device_id or not model_id:
        msg = "Missing device_id or model_id in config entry"
        raise ConfigEntryNotReady(msg)

    api = HAEcoflowApi(
        hass,
        device_id,
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        model_id,
    )

    # Authenticate against the EcoFlow cloud
    try:
        await api.async_authorize()
    except ConfigEntryNotReady:
        # Transient network error — HA will retry automatically
        raise
    except IntegrationError as e:
        # Bad credentials or unexpected API error — fail fast, no retry
        LOGGER.error("Failed to authenticate EcoFlow device %s: %s", entry.title, e)
        return False

    # Parse device structure (static metadata — run once at setup)
    raw = await api.fetch_raw()
    parser = EcoflowParser(variant=api.variant, sn=api.sn)
    endpoints = parser.parse_structure(raw)

    # Create the coordinator and perform the first polling refresh
    scan_interval = timedelta(
        seconds=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    coordinator = PowerOceanCoordinator(
        hass=hass, api=api, update_interval=scan_interval
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "endpoints": endpoints,
    }

    # Forward setup to all registered platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    model_name = MODEL_NAME_MAP[PowerOceanModel(model_id)]
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_id)},
        manufacturer="EcoFlow",
        serial_number=device_id,
        name=options.get(CONF_FRIENDLY_NAME),
        model=model_name,
        model_id=model_id,
        configuration_url="https://user-portal.ecoflow.com/",
    )

    # Reload the entry when the user updates options (e.g. polling interval)
    entry.async_on_unload(entry.add_update_listener(update_listener))

    # ── Service: set_tou_schedule ─────────────────────────────────────────────
    # observed write field: cfgTouStrategy (or cfgTouHoursStrategy for hourly variant)
    # The TOU strategy is a single JSON blob; individual hours are not exposed as
    # separate entities.
    async def handle_set_tou_schedule(call: ServiceCall) -> None:
        schedule_raw: str = call.data["schedule"]
        try:
            schedule_obj = json.loads(schedule_raw)
        except (ValueError, TypeError) as exc:
            msg = f"Invalid TOU schedule JSON: {exc}"
            raise HomeAssistantError(msg) from exc

        api_entry = hass.data[DOMAIN].get(entry.entry_id, {}).get("api")
        if api_entry is None:
            msg = "PowerOcean API not available"
            raise HomeAssistantError(msg)

        await api_entry.async_set_property({"cfgTouStrategy": schedule_obj})

    # ── Service: set_grid_type ────────────────────────────────────────────────
    # observed write field: cfgGridType
    async def handle_set_grid_type(call: ServiceCall) -> None:
        grid_type = int(call.data["grid_type"])
        api_entry = hass.data[DOMAIN].get(entry.entry_id, {}).get("api")
        if api_entry is None:
            msg = "PowerOcean API not available"
            raise HomeAssistantError(msg)

        await api_entry.async_set_property({"cfgGridType": grid_type})

    # ── Service: ocpp_list_backends ───────────────────────────────────────────
    # Returns the OCPP platform-config catalog from the EcoFlow account.
    # Useful for inspecting existing backends and discovering platform_type
    # enum values empirically.
    async def handle_ocpp_list_backends(call: ServiceCall) -> ServiceResponse:
        api_entry = hass.data[DOMAIN].get(entry.entry_id, {}).get("api")
        if api_entry is None:
            msg = "PowerOcean API not available"
            raise HomeAssistantError(msg)
        return {"backends": await api_entry.async_ocpp_list_backends()}

    # ── Service: ocpp_register_backend ────────────────────────────────────────
    # POSTs a CPOcppBindReq with isEnabled=1. Updates the EcoFlow-side catalog
    # only — does NOT yet redirect the charger at runtime (that needs the
    # vendorInfoSet proto write).
    async def handle_ocpp_register_backend(call: ServiceCall) -> ServiceResponse:
        sn = call.data.get("sn") or _resolve_powerpulse_sn(hass, entry)
        if not sn:
            msg = "PowerPulse serial number not found; pass 'sn' explicitly"
            raise HomeAssistantError(msg)
        body = _build_ocpp_bind_req(call.data, sn=sn, enabled=True)
        api_entry = hass.data[DOMAIN].get(entry.entry_id, {}).get("api")
        return await api_entry.async_ocpp_post_backend(body)

    # ── Service: ocpp_probe_runtime ───────────────────────────────────────────
    # Read-only diagnostic. Calls getDeviceProperty / acquireQuotaAll against
    # the PowerPulse SN and returns the raw payload, so the on-device OCPP
    # field names (vendorInfoSet / pileOcppParam / etc.) can be discovered
    # empirically. Used to design the runtime-handover write.
    async def handle_ocpp_probe_runtime(call: ServiceCall) -> ServiceResponse:
        api_entry = hass.data[DOMAIN].get(entry.entry_id, {}).get("api")
        if api_entry is None:
            msg = "PowerOcean API not available"
            raise HomeAssistantError(msg)
        # PowerOcean data comes from provider-service/user/device/detail, not
        # the iot-devices quota endpoints (which 500 for this product line).
        try:
            raw = await api_entry.fetch_raw()
        except Exception as err:
            raise HomeAssistantError(f"ocpp_probe_runtime fetch failed: {err}") from err
        return {"response": raw}

    # ── Service: ocpp_disable_backend ─────────────────────────────────────────
    # POSTs the same record with isEnabled=0 (the documented "tidy" path).
    async def handle_ocpp_disable_backend(call: ServiceCall) -> ServiceResponse:
        sn = call.data.get("sn") or _resolve_powerpulse_sn(hass, entry)
        if not sn:
            msg = "PowerPulse serial number not found; pass 'sn' explicitly"
            raise HomeAssistantError(msg)
        body = _build_ocpp_bind_req(call.data, sn=sn, enabled=False)
        api_entry = hass.data[DOMAIN].get(entry.entry_id, {}).get("api")
        return await api_entry.async_ocpp_post_backend(body)

    # ── Service: ocpp_get_domain ──────────────────────────────────────────────
    # GET /iot-service/ac305/charge/ocpp/domain — reads the current OCPP URL
    # that the charger believes it is connected to (OcppUrlDomain).
    # APK: o9/b.java:629
    async def handle_ocpp_get_domain(call: ServiceCall) -> ServiceResponse:
        api_entry = hass.data[DOMAIN].get(entry.entry_id, {}).get("api")
        if api_entry is None:
            raise HomeAssistantError("PowerOcean API not available")
        sn = call.data.get("sn") or _resolve_powerpulse_sn(hass, entry)
        if not sn:
            raise HomeAssistantError("PowerPulse SN not found; pass 'sn' explicitly")
        try:
            return await api_entry.async_ocpp_get_domain(sn)
        except Exception as err:
            raise HomeAssistantError(f"ocpp_get_domain failed: {err}") from err

    # ── Service: ocpp_activate_backend ────────────────────────────────────────
    # APK analysis confirmed: the EcoFlow Pro app has NO HTTP endpoint that
    # writes the OCPP URL to the charger at runtime. Only GET exists for
    # /iot-service/ac305/charge/ocpp/domain.  The /iot-devices/device/
    # setDeviceProperty path does NOT appear in the APK at all for OCPP.
    # The only confirmed runtime path is BLE cmd 770 (ocpp_ble_activate).
    # This service is kept for legacy callers but immediately raises with
    # a clear redirect message.
    async def handle_ocpp_activate_backend(call: ServiceCall) -> ServiceResponse:
        raise HomeAssistantError(
            "ocpp_activate_backend: no cloud/HTTP path exists to redirect the "
            "PowerPulse OCPP server at runtime. "
            "APK reverse-engineering confirmed the EcoFlow Pro app uses BLE cmd 770 "
            "(EcoOdmProtocol / SETTING_NETWORK) exclusively. "
            "Use ocpp_ble_activate instead — it connects via your ESPHome Bluetooth "
            "proxy, authenticates (BLE cmd 514), and pushes the OCPP URL (cmd 770) "
            "directly to the charger."
        )

    # ── Service: ocpp_reset_backend ───────────────────────────────────────────
    # Sends vendorInfoClr (CmdID 0xA3 / VENDOR_INFO_CLR) — reverts the charger
    # to EcoFlow cloud without a factory reset.
    # APK: VENDOR_INFO_CLR in cp307_ocpp.proto.
    async def handle_ocpp_reset_backend(call: ServiceCall) -> ServiceResponse:
        api_entry = hass.data[DOMAIN].get(entry.entry_id, {}).get("api")
        if api_entry is None:
            raise HomeAssistantError("PowerOcean API not available")
        powerpulse_sn = call.data.get("sn") or _resolve_powerpulse_sn(hass, entry)
        if not powerpulse_sn:
            raise HomeAssistantError("PowerPulse SN not found; pass 'sn' explicitly")
        inverter_sn = entry.data.get(CONF_DEVICE_ID)

        last_err: Exception | None = None
        for target in dict.fromkeys([powerpulse_sn, inverter_sn]):
            if not target:
                continue
            try:
                result = await api_entry.async_ocpp_vendor_info_clr(sn=target)
                return {"sn_used": target, "result": result}
            except Exception as err:  # noqa: BLE001
                LOGGER.debug("vendorInfoClr via %s failed: %s", target, err)
                last_err = err
        raise HomeAssistantError(
            f"ocpp_reset_backend failed on all targets: {last_err}"
        ) from last_err

    # ── Service: ocpp_ble_activate ────────────────────────────────────────────
    # Directly sends the OCPP server URL to the PowerPulse charger via BLE.
    # Requires an ESPHome Bluetooth proxy (or local BLE adapter) in range.
    # BLE address is auto-detected from the SN ("EF-AC310052" pattern) if
    # omitted. A per-address asyncio.Lock serialises concurrent calls.
    # Auth key = MD5(userId + sn) uppercase hex, as per APK q4.r / c0.V.
    # Cmd 514 (AUTH_WRITE) then Cmd 770 (SETTING_NETWORK).
    async def handle_ocpp_ble_activate(call: ServiceCall) -> ServiceResponse:
        api_entry = hass.data[DOMAIN].get(entry.entry_id, {}).get("api")
        if api_entry is None:
            raise HomeAssistantError("PowerOcean API not available")

        ocpp_url: str = call.data["ocpp_url"]
        backup_url: str = call.data.get("backup_url") or ocpp_url
        wifi_ssid: str = call.data.get("wifi_ssid", "")
        wifi_password: str = call.data.get("wifi_password", "")
        connect_timeout: float = float(call.data.get("connect_timeout", 15))
        response_timeout: float = float(call.data.get("response_timeout", 8))

        # Resolve charger SN: explicit > auto-discovered PowerPulse SN
        sn = call.data.get("sn") or _resolve_powerpulse_sn(hass, entry)
        if not sn:
            raise HomeAssistantError("PowerPulse SN not found; pass 'sn' explicitly")

        # Resolve BLE address: explicit > auto-detect from SN via advertisement scan
        ble_address: str | None = call.data.get("ble_address") or None
        if not ble_address:
            ble_address = await async_find_charger_address(hass, sn)
            if not ble_address:
                expected = f"EF-{sn[:4]}{sn[-4:]}"
                raise HomeAssistantError(
                    f"PowerPulse BLE address not found — charger not visible to any "
                    f"Bluetooth proxy. Expected advertisement name: {expected!r}. "
                    "Pass 'ble_address' explicitly or ensure ESPHome proxy is in range."
                )
            LOGGER.info("ble_ocpp: auto-detected BLE address %s for SN %s", ble_address, sn)

        # Resolve user ID: explicit > stored from last auth
        user_id: str = call.data.get("user_id") or getattr(api_entry, "user_id", "") or ""
        if not user_id:
            raise HomeAssistantError(
                "EcoFlow user_id not available — pass 'user_id' explicitly "
                "(find it via Developer Tools → check EcoFlow login response)"
            )

        try:
            result = await async_ble_set_ocpp_url(
                hass=hass,
                ble_address=ble_address,
                user_id=user_id,
                sn=sn,
                ocpp_url=ocpp_url,
                backup_url=backup_url,
                wifi_ssid=wifi_ssid,
                wifi_password=wifi_password,
                connect_timeout=connect_timeout,
                response_timeout=response_timeout,
            )
        except (ValueError, RuntimeError) as exc:
            raise HomeAssistantError(str(exc)) from exc

        return result

    # secure_url is required by the EcoFlow endpoint: posting an empty
    # secureUrl returns code 1006 ("安全URL地址不能为空" / "Security URL
    # cannot be empty"), even when backendUrl is a valid ws:// URL.
    # platform_type=2 is the value observed for third-party (HA lbbrhzn)
    # backends; platform_type=1 is reserved for the built-in SmartRed entry.
    _ocpp_bind_schema = vol.Schema(
        {
            vol.Required("backend_url"): cv.string,
            vol.Required("secure_url"): cv.string,
            vol.Optional("id"): cv.string,
            vol.Optional("sn"): cv.string,
            vol.Optional("platform_code", default="lbbrhzn"): cv.string,
            vol.Optional("platform_name", default="HA lbbrhzn/ocpp"): cv.string,
            vol.Optional("platform_type", default=2): vol.Coerce(int),
            vol.Optional("auth_key", default=""): cv.string,
            vol.Optional("sort_order", default=0): vol.Coerce(int),
        }
    )

    if not hass.services.has_service(DOMAIN, "ocpp_list_backends"):
        hass.services.async_register(
            DOMAIN,
            "ocpp_list_backends",
            handle_ocpp_list_backends,
            schema=vol.Schema({}),
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, "ocpp_register_backend"):
        hass.services.async_register(
            DOMAIN,
            "ocpp_register_backend",
            handle_ocpp_register_backend,
            schema=_ocpp_bind_schema,
            supports_response=SupportsResponse.OPTIONAL,
        )

    if not hass.services.has_service(DOMAIN, "ocpp_probe_runtime"):
        hass.services.async_register(
            DOMAIN,
            "ocpp_probe_runtime",
            handle_ocpp_probe_runtime,
            schema=vol.Schema({}),
            supports_response=SupportsResponse.ONLY,
        )

    if not hass.services.has_service(DOMAIN, "ocpp_disable_backend"):
        hass.services.async_register(
            DOMAIN,
            "ocpp_disable_backend",
            handle_ocpp_disable_backend,
            schema=_ocpp_bind_schema,
            supports_response=SupportsResponse.OPTIONAL,
        )

    _ocpp_sn_schema = vol.Schema({vol.Optional("sn"): cv.string})

    if not hass.services.has_service(DOMAIN, "ocpp_get_domain"):
        hass.services.async_register(
            DOMAIN,
            "ocpp_get_domain",
            handle_ocpp_get_domain,
            schema=_ocpp_sn_schema,
            supports_response=SupportsResponse.ONLY,
        )

    _ocpp_activate_schema = vol.Schema(
        {
            vol.Required("backend_url"): cv.string,
            vol.Required("device_id"): cv.string,
            vol.Optional("sn"): cv.string,
            vol.Optional("vendor", default="lbbrhzn"): cv.string,
            vol.Optional("cpo_name", default="HA lbbrhzn/ocpp"): cv.string,
            vol.Optional("profile", default=0): vol.All(
                vol.Coerce(int), vol.In([0, 1, 2])
            ),
            vol.Optional("auth_key", default=""): cv.string,
        }
    )

    if not hass.services.has_service(DOMAIN, "ocpp_activate_backend"):
        hass.services.async_register(
            DOMAIN,
            "ocpp_activate_backend",
            handle_ocpp_activate_backend,
            schema=_ocpp_activate_schema,
            supports_response=SupportsResponse.OPTIONAL,
        )

    if not hass.services.has_service(DOMAIN, "ocpp_reset_backend"):
        hass.services.async_register(
            DOMAIN,
            "ocpp_reset_backend",
            handle_ocpp_reset_backend,
            schema=_ocpp_sn_schema,
            supports_response=SupportsResponse.OPTIONAL,
        )

    _ocpp_ble_schema = vol.Schema(
        {
            vol.Optional("ble_address"): cv.string,
            vol.Required("ocpp_url"): cv.string,
            vol.Optional("backup_url"): cv.string,
            vol.Optional("sn"): cv.string,
            vol.Optional("user_id"): cv.string,
            vol.Optional("wifi_ssid", default=""): cv.string,
            vol.Optional("wifi_password", default=""): cv.string,
            vol.Optional("connect_timeout", default=15): vol.Coerce(float),
            vol.Optional("response_timeout", default=8): vol.Coerce(float),
        }
    )

    if not hass.services.has_service(DOMAIN, "ocpp_ble_activate"):
        hass.services.async_register(
            DOMAIN,
            "ocpp_ble_activate",
            handle_ocpp_ble_activate,
            schema=_ocpp_ble_schema,
            supports_response=SupportsResponse.OPTIONAL,
        )

    if not hass.services.has_service(DOMAIN, "set_tou_schedule"):
        hass.services.async_register(
            DOMAIN,
            "set_tou_schedule",
            handle_set_tou_schedule,
            schema=vol.Schema({vol.Required("schedule"): cv.string}),
        )

    if not hass.services.has_service(DOMAIN, "set_grid_type"):
        hass.services.async_register(
            DOMAIN,
            "set_grid_type",
            handle_set_grid_type,
            schema=vol.Schema(
                {vol.Required("grid_type"): vol.All(vol.Coerce(int), vol.In([0, 1]))}
            ),
        )

    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries to new structure."""
    version = entry.version
    data = dict(entry.data)
    options = dict(entry.options)

    if version < 2:
        # ALT → NEU
        if "user_input" in data:
            old = data.pop("user_input")

            data.update(
                {
                    CONF_DEVICE_ID: old.get(CONF_DEVICE_ID),
                    CONF_EMAIL: old.get(CONF_EMAIL),
                    CONF_PASSWORD: old.get(CONF_PASSWORD),
                    CONF_MODEL_ID: old.get(CONF_MODEL_ID),
                }
            )

            # Move friendly_name into options (new structure)
            options.setdefault(
                CONF_FRIENDLY_NAME,
                old.get(CONF_FRIENDLY_NAME, DEFAULT_NAME),
            )
        version = 2

    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options,
        version=version,
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and clean up resources."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        LOGGER.warning("Failed to unload platforms for %s", entry.entry_id)
        return False

    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    # Remove domain-level services when the last entry is unloaded
    if not hass.data.get(DOMAIN):
        for service_name in (
            "set_tou_schedule",
            "set_grid_type",
            "ocpp_list_backends",
            "ocpp_register_backend",
            "ocpp_disable_backend",
            "ocpp_probe_runtime",
        ):
            if hass.services.has_service(DOMAIN, service_name):
                hass.services.async_remove(DOMAIN, service_name)

    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options are updated (z.B. polling interval)."""
    LOGGER.debug("Reloading PowerOcean entry %s due to options change", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)
