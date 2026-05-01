"""
PowerOcean number platform — numeric adjustable parameters.

APK sources (CFG_*_FIELD_NUMBER → camelCase write key):
  CFG_BACKUP_REVERSE_SOC_FIELD_NUMBER  → cfgBackupReverseSoc
  CFG_SP_FAST_CHG_MAX_SOC_FIELD_NUMBER → cfgSpFastChgMaxSoc
  CFG_SP_CHARGER_CHG_POW_LIMIT_FIELD_NUMBER → cfgSpChargerChgPowLimit
  CFG_SYS_GRID_IN_PWR_LIMIT_FIELD_NUMBER   → cfgSysGridInPwrLimit

Equipment (doc/equipment.md):
  12 kW PowerOcean inverter + 2 x 5 kWh batteries + 11 kW PowerPulse
"""

from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    PARAM_BACKUP_RESERVE_SOC,
    PARAM_CHARGER_AMP_LIMIT,
    PARAM_CHARGER_POWER_LIMIT,
    PARAM_FAST_CHG_MAX_SOC,
    PARAM_GRID_IN_PWR_LIMIT,
)
from .coordinator import PowerOceanCoordinator


@dataclass(frozen=True)
class PowerOceanNumberDescription(NumberEntityDescription):
    """Extends NumberEntityDescription with the API write-parameter key."""

    param_key: str = ""
    # True = entity belongs to the PowerPulse child device
    is_powerpulse: bool = False
    # Coordinator data field name(s) used to read back the current value.
    # Searched as {device_sn}_*_{field} in coordinator.data.
    state_fields: tuple[str, ...] = field(default_factory=tuple)
    # Multiplier applied to the raw coordinator value before display (e.g. 0.1
    # converts deci-amps to amps).
    state_scale: float = 1.0


NUMBER_DESCRIPTIONS: list[PowerOceanNumberDescription] = [
    # ── Backup reserve SoC ───────────────────────────────────────────────────
    # ACTION_W_CFG_BACKUP_REVERSE_SOC — minimum battery charge kept for grid outage
    PowerOceanNumberDescription(
        key="backup_reserve_soc",
        translation_key="backup_reserve_soc",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        device_class=NumberDeviceClass.BATTERY,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:battery-lock",
        mode=NumberMode.BOX,
        param_key=PARAM_BACKUP_RESERVE_SOC,
    ),
    # ── Fast-charge upper SoC limit ──────────────────────────────────────────
    # ACTION_W_CFG_SP_FAST_CHG_MAX_SOC — ceiling for fast-charge mode
    PowerOceanNumberDescription(
        key="fast_chg_max_soc",
        translation_key="fast_chg_max_soc",
        native_min_value=50,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        device_class=NumberDeviceClass.BATTERY,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:battery-charging-100",
        mode=NumberMode.BOX,
        param_key=PARAM_FAST_CHG_MAX_SOC,
    ),
    # ── PowerPulse charger power cap ─────────────────────────────────────────
    # ACTION_W_CFG_SP_CHARGER_CHG_POW_LIMIT — max charge power for the 11 kW PowerPulse
    PowerOceanNumberDescription(
        key="charger_power_limit",
        translation_key="charger_power_limit",
        native_min_value=0,
        native_max_value=11000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:ev-station",
        mode=NumberMode.BOX,
        param_key=PARAM_CHARGER_POWER_LIMIT,
        is_powerpulse=True,
    ),
    # ── Grid import power limit ──────────────────────────────────────────────
    # ACTION_W_CFG_SYS_GRID_IN_PWR_LIMIT — caps grid draw for TOU / peak-shaving
    PowerOceanNumberDescription(
        key="grid_in_pwr_limit",
        translation_key="grid_in_pwr_limit",
        native_min_value=0,
        native_max_value=12000,
        native_step=100,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=NumberDeviceClass.POWER,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:transmission-tower-import",
        mode=NumberMode.BOX,
        param_key=PARAM_GRID_IN_PWR_LIMIT,
    ),
    # ── PowerPulse device-battery charge amp limit ───────────────────────────
    # ACTION_W_CFG_SP_CHARGER_DEV_BATT_CHG_AMP_LIMIT
    # Sets the maximum AC charging current (A) for the 11 kW PowerPulse.
    # Range 6-32 A matches IEC 61851 Mode 2/3 AC charging standards.
    # Read-back fields are stored in deci-amps (multiply by 0.1 to get A).
    PowerOceanNumberDescription(
        key="charger_amp_limit",
        translation_key="charger_amp_limit",
        native_min_value=6,
        native_max_value=32,
        native_step=1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=NumberDeviceClass.CURRENT,
        entity_category=EntityCategory.CONFIG,
        icon="mdi:current-ac",
        mode=NumberMode.BOX,
        param_key=PARAM_CHARGER_AMP_LIMIT,
        is_powerpulse=True,
        # evCurrSet (EVCHARGING_REPORT) and userCurrentSet (EDEV_PARAM_REPORT)
        # both store the value in deci-amps.
        state_fields=("evCurrSet", "userCurrentSet"),
        state_scale=0.1,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up PowerOcean number entities for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    endpoints = data["endpoints"]

    pp_sn = _find_powerpulse_sn(endpoints, coordinator.api.sn)

    entities = [
        PowerOceanNumber(coordinator, description, pp_sn=pp_sn)
        for description in NUMBER_DESCRIPTIONS
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


class PowerOceanNumber(CoordinatorEntity, NumberEntity):
    """Adjustable numeric parameter on the PowerOcean inverter or PowerPulse."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PowerOceanCoordinator,
        description: PowerOceanNumberDescription,
        pp_sn: str | None = None,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._param_key = description.param_key
        self._cached_value: float | None = None
        self._attr_unique_id = f"{coordinator.api.sn}_{description.key}"
        self._device_sn = (
            pp_sn if (description.is_powerpulse and pp_sn) else coordinator.api.sn
        )

    def _read_coordinator_value(self) -> float | None:
        """Search coordinator.data for any field matching the description's state_fields."""
        fields = self.entity_description.state_fields
        if not fields or not self._device_sn:
            return None
        data = self.coordinator.data or {}
        prefix = self._device_sn + "_"
        for f in fields:
            suffix = "_" + f
            for key, value in data.items():
                if key.startswith(prefix) and key.endswith(suffix):
                    raw = value
                    if raw is not None:
                        return float(raw) * self.entity_description.state_scale
        return None

    @property
    def native_value(self) -> float | None:
        """Return current value — live coordinator data preferred, cached as fallback."""
        live = self._read_coordinator_value()
        if live is not None:
            return live
        return self._cached_value

    async def async_set_native_value(self, value: float) -> None:
        """Write the new value to the inverter and cache it locally."""
        await self.coordinator.api.async_set_property({self._param_key: int(value)})
        self._cached_value = value
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._device_sn)})
