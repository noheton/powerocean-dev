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
from homeassistant.core import HomeAssistant, ServiceCall
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
from .coordinator import PowerOceanCoordinator
from .ecoflow import HAEcoflowApi
from .parser import EcoflowParser


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
    # APK source: ACTION_W_CFG_TOU_STRATEGY / CFG_TOU_HOURS_STRATEGY_FIELD_NUMBER
    # The TOU strategy is a single JSON blob; individual hours are not exposed as
    # separate entities per APK analysis recommendation.
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
    # APK source: ACTION_W_CFG_GRID_TYPE / CFG_GRID_TYPE_FIELD_NUMBER
    async def handle_set_grid_type(call: ServiceCall) -> None:
        grid_type = int(call.data["grid_type"])
        api_entry = hass.data[DOMAIN].get(entry.entry_id, {}).get("api")
        if api_entry is None:
            msg = "PowerOcean API not available"
            raise HomeAssistantError(msg)

        await api_entry.async_set_property({"cfgGridType": grid_type})

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
        for service_name in ("set_tou_schedule", "set_grid_type"):
            if hass.services.has_service(DOMAIN, service_name):
                hass.services.async_remove(DOMAIN, service_name)

    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options are updated (z.B. polling interval)."""
    LOGGER.debug("Reloading PowerOcean entry %s due to options change", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)
