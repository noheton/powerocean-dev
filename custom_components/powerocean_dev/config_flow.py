"""
Config flow for the PowerOcean integration.

This module defines the configuration flow and options flow for
adding and managing PowerOcean devices in Home Assistant.

Features:
- User authentication via EcoFlow API.
- Auto-detection of PowerOcean devices linked to the account.
- Fallback to manual serial-number and model entry when auto-detection fails.
- Optional configuration for friendly name and scan interval.
- Support for reconfiguring existing entries.
- Import path from the legacy ``powerocean`` domain.
- Sanitization of device names to ensure valid formatting.

Classes:
- PowerOceanConfigFlow: Handles the main configuration flow.
- PowerOceanOptionsFlow: Handles options for existing entries.

Functions:
- sanitize_device_name: Cleans and validates device names.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
    IntegrationError,
)
from homeassistant.helpers.selector import selector

from .const import (
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    MODEL_NAME_MAP,
    PowerOceanModel,
)
from .ecoflow import AuthenticationFailedError, HAEcoflowApi

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_FRIENDLY_NAME,
    CONF_MODEL_ID,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
)

# ── Step 1: credentials only (email + password) ──────────────────────────────
STEP_CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL, default=""): str,
        vol.Required(CONF_PASSWORD, default=""): str,
    }
)

# ── Step 2b: manual device entry (fallback when auto-detection yields nothing) ─
_MODEL_OPTIONS = [
    {"label": "PowerOcean", "value": "83"},
    {"label": "PowerOcean DC Fit", "value": "85"},
    {"label": "PowerOcean Single Phase", "value": "86"},
    {"label": "PowerOcean Plus", "value": "87"},
]

STEP_PICK_DEVICE_MANUAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID, default=""): str,
        vol.Required(CONF_MODEL_ID, default="83"): selector(
            {
                "select": {
                    "options": _MODEL_OPTIONS,
                    "mode": "dropdown",
                }
            }
        ),
    }
)

# ── Step 3: optional device settings ─────────────────────────────────────────
STEP_DEVICE_OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_FRIENDLY_NAME, default=DEFAULT_NAME): str,
        vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): selector(
            {
                "number": {
                    "min": 10,
                    "max": 60,
                    "unit_of_measurement": "s",
                    "mode": "box",
                }
            }
        ),
    }
)


class PowerOceanConfigFlow(ConfigFlow, domain=DOMAIN):
    """
    Handle the configuration flow for adding a PowerOcean device to Home Assistant.

    Flow steps:
      1. ``user`` — collect email + password, then auto-detect devices.
      2. ``pick_device`` — choose from discovered devices (selector) or enter
         serial number + model manually (fallback).
      3. ``device_options`` — optional friendly name and scan interval.

    Import path (from legacy ``powerocean`` domain):
      ``import`` — creates the entry directly from existing config data.
    """

    VERSION = 2

    def __init__(self) -> None:
        """Initialize flow instance variables."""
        self._cloud_data: dict[str, Any] = {}
        # Populated after step 1 if auto-detection succeeds
        self._discovered_devices: list[dict[str, Any]] = []

    # ── Step 1: credentials ───────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect credentials and attempt device auto-detection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api = HAEcoflowApi(
                hass=self.hass,
                serialnumber="",
                username=user_input[CONF_EMAIL],
                password=user_input[CONF_PASSWORD],
                variant="",
            )
            try:
                await api.async_authorize_only()
                self._discovered_devices = await api.async_list_devices()
            except (IntegrationError, ConfigEntryNotReady):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected error during credential check")
                errors["base"] = "unknown"

            if not errors:
                self._cloud_data = {
                    CONF_EMAIL: user_input[CONF_EMAIL],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }
                return await self.async_step_pick_device()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_CREDENTIALS_SCHEMA,
            errors=errors,
        )

    # ── Step 2: pick or enter device ──────────────────────────────────────────

    async def async_step_pick_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """
        Select a discovered device or enter one manually.

        When auto-detection found devices the step renders a drop-down
        selector whose values are encoded as ``"<sn>|<product_type>"``.
        When no devices were found (or detection failed) two plain-text /
        dropdown fields are shown instead.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            if "device_selection" in user_input:
                # Auto-detected path: parse "sn|product_type" encoded value
                raw = user_input["device_selection"]
                try:
                    sn, product_type = raw.split("|", 1)
                except ValueError:
                    errors["base"] = "unknown"
                else:
                    device_id, model_id = sn.strip(), product_type.strip()
            else:
                # Manual entry path
                device_id = user_input[CONF_DEVICE_ID]
                model_id = user_input[CONF_MODEL_ID]

            if not errors:
                unique_id = f"PowerOcean {device_id}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                self._cloud_data.update(
                    {
                        CONF_DEVICE_ID: device_id,
                        CONF_MODEL_ID: model_id,
                    }
                )
                return await self.async_step_device_options()

        # Build form schema depending on whether devices were discovered
        valid_models = {m.value for m in PowerOceanModel}
        auto_options = [
            {
                "label": (
                    f"{d['name']} — "
                    + MODEL_NAME_MAP.get(
                        PowerOceanModel(d["product_type"]), d["product_type"]
                    )
                    + f" ({d['sn']})"
                ),
                "value": f"{d['sn']}|{d['product_type']}",
            }
            for d in self._discovered_devices
            if d.get("product_type") in valid_models
        ]

        if auto_options:
            schema = vol.Schema(
                {
                    vol.Required("device_selection"): selector(
                        {
                            "select": {
                                "options": auto_options,
                                "mode": "dropdown",
                            }
                        }
                    )
                }
            )
        else:
            schema = STEP_PICK_DEVICE_MANUAL_SCHEMA

        return self.async_show_form(
            step_id="pick_device",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "count": str(len(auto_options)) if auto_options else "0"
            },
        )

    # ── Step 3: device options ────────────────────────────────────────────────

    async def async_step_device_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect optional device settings (friendly name, scan interval)."""
        errors = {}
        if user_input is not None:
            model_name = MODEL_NAME_MAP[
                PowerOceanModel(self._cloud_data[CONF_MODEL_ID])
            ]
            friendly_name = sanitize_device_name(
                user_input[CONF_FRIENDLY_NAME],
                fall_back=DEFAULT_NAME,
            )
            return self.async_create_entry(
                title=model_name,
                data=self._cloud_data,
                options={
                    **user_input,
                    CONF_FRIENDLY_NAME: friendly_name,
                },
            )

        return self.async_show_form(
            step_id="device_options",
            data_schema=STEP_DEVICE_OPTIONS_SCHEMA,
            errors=errors,
        )

    # ── Import from legacy powerocean domain ──────────────────────────────────

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """
        Import a config entry from the legacy ``powerocean`` domain.

        Called automatically by ``async_setup`` in ``__init__.py`` when a
        ``powerocean`` entry is found and no matching ``powerocean_dev`` entry
        exists yet.  Creates the new entry without showing any UI.

        Args:
            import_data: Data dict from the old config entry, optionally
                supplemented with ``CONF_FRIENDLY_NAME`` and
                ``CONF_SCAN_INTERVAL`` from the old entry's options.

        """
        device_id = import_data.get(CONF_DEVICE_ID, "")
        model_id = str(import_data.get(CONF_MODEL_ID, PowerOceanModel.POWEROCEAN))

        unique_id = f"PowerOcean {device_id}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        try:
            model_name = MODEL_NAME_MAP[PowerOceanModel(model_id)]
        except (KeyError, ValueError):
            model_name = "PowerOcean"

        LOGGER.info(
            "Importing PowerOcean device %s (model %s) from legacy integration",
            device_id,
            model_name,
        )

        return self.async_create_entry(
            title=model_name,
            data={
                CONF_DEVICE_ID: device_id,
                CONF_EMAIL: import_data.get(CONF_EMAIL, ""),
                CONF_PASSWORD: import_data.get(CONF_PASSWORD, ""),
                CONF_MODEL_ID: model_id,
            },
            options={
                CONF_FRIENDLY_NAME: import_data.get(CONF_FRIENDLY_NAME, DEFAULT_NAME),
                CONF_SCAN_INTERVAL: import_data.get(
                    CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                ),
            },
        )

    # ── Reconfigure (manual correction of existing entry) ─────────────────────

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Correct credentials, serial number, or model for an existing entry."""
        entry = self._get_reconfigure_entry()
        errors = {}

        if user_input is not None:
            merged = {**entry.data, **user_input}

            try:
                await _validate_full_credentials(self.hass, merged)
                new_unique_id = f"PowerOcean {merged[CONF_DEVICE_ID]}"

                if entry.unique_id != new_unique_id:
                    await self.async_set_unique_id(new_unique_id)

                self.hass.config_entries.async_update_entry(entry, data=merged)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfiguration_completed")
            except AuthenticationFailedError:
                errors["base"] = "invalid_auth"
            except IntegrationError:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._get_reconfigure_schema(entry),
            errors=errors,
        )

    def _get_reconfigure_schema(self, entry: ConfigEntry) -> vol.Schema:
        """Build the voluptuous schema for the reconfigure step."""
        return vol.Schema(
            {
                vol.Required(
                    CONF_DEVICE_ID, default=entry.data.get(CONF_DEVICE_ID, "")
                ): str,
                vol.Required(CONF_EMAIL, default=entry.data.get(CONF_EMAIL, "")): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(
                    CONF_MODEL_ID, default=entry.data.get(CONF_MODEL_ID, "83")
                ): selector(
                    {
                        "select": {
                            "options": _MODEL_OPTIONS,
                            "mode": "dropdown",
                        }
                    }
                ),
            }
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """
        Return the options flow handler for this config entry.

        Args:
            config_entry: The configuration entry for which the options flow
                is requested.

        Returns:
            An instance of the PowerOceanOptionsFlow class.

        """
        return PowerOceanOptionsFlow()


class PowerOceanOptionsFlow(OptionsFlow):
    """
    Handle adjustable options for an existing PowerOcean config entry.

    This flow allows the user to update:
      - Friendly name of the device.
      - Scan interval for periodic updates.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the options flow init step."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_FRIENDLY_NAME,
                        default=options.get(CONF_FRIENDLY_NAME, DEFAULT_NAME),
                    ): str,
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): selector(
                        {
                            "number": {
                                "min": 10,
                                "max": 60,
                                "unit_of_measurement": "s",
                                "mode": "box",
                            }
                        }
                    ),
                }
            ),
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _validate_full_credentials(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """
    Validate credentials by attempting a full auth + region detection.

    Used by the reconfigure step where the device SN is already known.

    Raises:
        HomeAssistantError: On connection failure.

    """
    api = HAEcoflowApi(
        hass,
        data[CONF_DEVICE_ID],
        data[CONF_EMAIL],
        data[CONF_PASSWORD],
        data[CONF_MODEL_ID],
    )
    try:
        await api.async_authorize()
    except IntegrationError as err:
        LOGGER.exception("Failed to connect to PowerOcean device")
        msg = "cannot_connect"
        raise HomeAssistantError(msg) from err
    except AuthenticationFailedError as err:
        LOGGER.exception("Authentication failed")
        msg = "cannot_connect"
        raise HomeAssistantError(msg) from err


def sanitize_device_name(
    device_name: str, fall_back: str, max_length: int = 255
) -> str:
    """
    Sanitize the device name.

    Trims whitespace, removes special characters, and enforces a maximum length.

    Args:
        device_name: Raw name string supplied by the user.
        fall_back: Value to return if the sanitized name is empty.
        max_length: Maximum allowed character length (default 255).

    Returns:
        A clean, safe device name string.

    """
    sanitized = device_name.strip()
    sanitized = re.sub(r"[^\w\s\-]", "", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized)
    sanitized = sanitized[:max_length]
    if not sanitized:
        return fall_back[:max_length]
    return sanitized
