"""
PowerOcean select platform — mode-selection parameters.

APK sources (CFG_*_FIELD_NUMBER → camelCase write key):
  CFG_SP_CHARGER_CHG_MODE_FIELD_NUMBER → cfgSpChargerChgMode
  CFG_BACKUP_BOX_MODE_FIELD_NUMBER     → cfgBackupBoxMode

Option integer values are derived from EcoFlow app layout strings and
community protocol analysis.  Confirm values on hardware before relying
on them in automations.
"""

from dataclasses import dataclass, field

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PARAM_BACKUP_BOX_MODE, PARAM_CHARGER_MODE
from .coordinator import PowerOceanCoordinator


@dataclass(frozen=True)
class PowerOceanSelectDescription(SelectEntityDescription):
    """Extends SelectEntityDescription with API write key and value mapping."""

    param_key: str = ""
    option_values: dict[str, int] = field(default_factory=dict)
    # True = entity belongs to the PowerPulse child device
    is_powerpulse: bool = False
    # Coordinator data field name whose integer value maps to an option string.
    # Searched as {device_sn}_*_{state_field} in coordinator.data.
    state_field: str = ""


SELECT_DESCRIPTIONS: list[PowerOceanSelectDescription] = [
    # ── PowerPulse charger mode ───────────────────────────────────────────────
    # ACTION_W_CFG_SP_CHARGER_CHG_MODE (SP = SmartPower / EV charger subsystem)
    # workMode is present in both EDEV_PARAM_REPORT and EVCHARGING_REPORT.
    PowerOceanSelectDescription(
        key="charger_mode",
        translation_key="charger_mode",
        options=["auto", "fast", "eco"],
        entity_category=EntityCategory.CONFIG,
        icon="mdi:ev-station",
        param_key=PARAM_CHARGER_MODE,
        option_values={"auto": 0, "fast": 1, "eco": 2},
        is_powerpulse=True,
        state_field="workMode",
    ),
    # ── Backup box (outage protection) mode ──────────────────────────────────
    # ACTION_W_CFG_BACKUP_BOX_MODE
    PowerOceanSelectDescription(
        key="backup_mode",
        translation_key="backup_mode",
        options=["self_use", "backup", "off"],
        entity_category=EntityCategory.CONFIG,
        icon="mdi:home-battery",
        param_key=PARAM_BACKUP_BOX_MODE,
        option_values={"self_use": 0, "backup": 1, "off": 2},
    ),
]

# Reverse mapping: API integer → option string (used for state read-back)
_OPTION_BY_VALUE: dict[str, dict[int, str]] = {
    desc.key: {v: k for k, v in desc.option_values.items()}
    for desc in SELECT_DESCRIPTIONS
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up PowerOcean select entities for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    endpoints = data["endpoints"]

    pp_sn = _find_powerpulse_sn(endpoints, coordinator.api.sn)

    entities = [
        PowerOceanSelect(coordinator, description, pp_sn=pp_sn)
        for description in SELECT_DESCRIPTIONS
    ]
    async_add_entities(entities)


def _find_powerpulse_sn(endpoints: dict, inverter_sn: str) -> str | None:
    """Return the PowerPulse serial number from the endpoint registry, or None."""
    for ep_id, ep in endpoints.items():
        if ep.serial != inverter_sn and any(
            r in ep_id for r in ("EDEV_PARAM_REPORT", "EVCHARGING_REPORT")
        ):
            return ep.serial
    return None


class PowerOceanSelect(CoordinatorEntity, SelectEntity):
    """Dropdown selector for a PowerOcean operating mode."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PowerOceanCoordinator,
        description: PowerOceanSelectDescription,
        pp_sn: str | None = None,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._param_key = description.param_key
        self._option_values = description.option_values
        self._reverse_map = _OPTION_BY_VALUE.get(description.key, {})
        self._cached_option: str | None = None
        self._attr_unique_id = f"{coordinator.api.sn}_{description.key}"
        self._device_sn = (
            pp_sn if (description.is_powerpulse and pp_sn) else coordinator.api.sn
        )

    def _read_coordinator_option(self) -> str | None:
        """Look up the current option from coordinator.data."""
        f = self.entity_description.state_field
        if not f or not self._device_sn:
            return None
        data = self.coordinator.data or {}
        prefix = self._device_sn + "_"
        suffix = "_" + f
        for key, value in data.items():
            if key.startswith(prefix) and key.endswith(suffix):
                return self._reverse_map.get(int(value))
        return None

    @property
    def current_option(self) -> str | None:
        """Return current option — live coordinator data preferred, cached as fallback."""
        live = self._read_coordinator_option()
        if live is not None:
            return live
        return self._cached_option

    async def async_select_option(self, option: str) -> None:
        """Write the selected mode to the inverter."""
        int_value = self._option_values[option]
        await self.coordinator.api.async_set_property({self._param_key: int_value})
        self._cached_option = option
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._device_sn)})
