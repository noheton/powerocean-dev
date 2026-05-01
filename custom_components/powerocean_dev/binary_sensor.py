"""PowerOcean binary sensor platform — boolean states and error flags."""

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BINARY_SENSOR_KEYS, DOMAIN
from .coordinator import PowerOceanCoordinator
from .types import PowerOceanEndPoint

# ── Static descriptions for all known boolean data-points ────────────────────
# Sourced from REPORT_DATAPOINTS and APK field analysis.
# Keys listed here are EXCLUDED from the sensor platform to avoid duplication.

BINARY_SENSOR_DESCRIPTIONS: dict[str, BinarySensorEntityDescription] = {
    # ── Connectivity ─────────────────────────────────────────────────────────
    "online": BinarySensorEntityDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    # ── Self-check / fault states ────────────────────────────────────────────
    # is_on = True means "problem detected" (device_class=PROBLEM convention)
    "emsBpSelfcheckState": BinarySensorEntityDescription(
        key="emsBpSelfcheckState",
        translation_key="ems_bp_selfcheck",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "emsMpptSelfcheckState": BinarySensorEntityDescription(
        key="emsMpptSelfcheckState",
        translation_key="ems_mppt_selfcheck",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ── Running state ────────────────────────────────────────────────────────
    "emsMpptRunState": BinarySensorEntityDescription(
        key="emsMpptRunState",
        translation_key="ems_mppt_run_state",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ── Safety / protection ───────────────────────────────────────────────────
    "epoSwitchState": BinarySensorEntityDescription(
        key="epoSwitchState",
        translation_key="epo_switch_state",
        device_class=BinarySensorDeviceClass.SAFETY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ── Configurational flags ─────────────────────────────────────────────────
    "autoDetectStartPowerEn": BinarySensorEntityDescription(
        key="autoDetectStartPowerEn",
        translation_key="auto_detect_start_power",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:auto-fix",
    ),
    "isPvToInvDirectly": BinarySensorEntityDescription(
        key="isPvToInvDirectly",
        translation_key="pv_to_inv_directly",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:solar-power",
    ),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up PowerOcean binary sensors for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    endpoints = data["endpoints"]

    entities = [
        PowerOceanBinarySensor(coordinator, endpoint)
        for endpoint in endpoints.values()
        if endpoint.friendly_name in BINARY_SENSOR_KEYS
    ]

    async_add_entities(entities)


class PowerOceanBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for a boolean PowerOcean state or error flag."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PowerOceanCoordinator,
        endpoint: PowerOceanEndPoint,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.endpoint = endpoint
        self._endpoint_id = endpoint.internal_unique_id

        key = endpoint.friendly_name
        if description := BINARY_SENSOR_DESCRIPTIONS.get(key):
            self.entity_description = description
        else:
            self._attr_name = key
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        self._attr_unique_id = self._endpoint_id

    @property
    def is_on(self) -> bool | None:
        """Return True when the flag/state is active (non-zero / truthy)."""
        val: Any = self.coordinator.data.get(self._endpoint_id)
        if val is None:
            return None
        return bool(val)

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device info for Home Assistant device registry."""
        return self.endpoint.device_info
