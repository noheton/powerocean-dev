"""
PowerOcean switch platform — on/off controllable parameters.

APK sources (CFG_*_FIELD_NUMBER → camelCase write key):
  CFG_SP_CHARGER_CHG_OPEN_FIELD_NUMBER          → cfgSpChargerChgOpen
  CFG_GRID_CHARGE_TO_BATTERY_ENABLE_FIELD_NUMBER → cfgGridChargeToBatteryEnable
  CFG_SYS_PAUSE_FIELD_NUMBER / CFG_SYS_RESUME_FIELD_NUMBER → cfgSysPause / cfgSysResume

Equipment (doc/equipment.md):
  12 kW PowerOcean, 2 x 5 kWh batteries, 11 kW PowerPulse (AC31ZEH4AG130052)
"""

from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    PARAM_BATTERY_HEAT,
    PARAM_CHARGER_AUTO_CHG,
    PARAM_CHARGER_ENABLE,
    PARAM_GRID_CHARGE_ENABLE,
    PARAM_SYS_PAUSE,
    PARAM_SYS_RESUME,
)
from .coordinator import PowerOceanCoordinator


@dataclass(frozen=True)
class PowerOceanSwitchDescription(SwitchEntityDescription):
    """Extends SwitchEntityDescription with API write keys for on/off."""

    on_params: dict[str, Any] = field(default_factory=dict)
    off_params: dict[str, Any] = field(default_factory=dict)
    # True = entity belongs to the PowerPulse child device
    is_powerpulse: bool = False
    # Simple boolean fields (1=on, 0=off) tried in order in coordinator.data.
    state_fields: tuple[str, ...] = field(default_factory=tuple)
    # Bitmask field — extract a single bit to derive the boolean state.
    state_bit_field: str = ""
    state_bit: int | None = None
    # If True, invert the boolean value read from coordinator data.
    state_inverted: bool = False


SWITCH_DESCRIPTIONS: list[PowerOceanSwitchDescription] = [
    # ── PowerPulse (SP / EV charger) enable ──────────────────────────────────
    # ACTION_W_CFG_SP_CHARGER_CHG_OPEN — enable/disable the 11 kW PowerPulse
    # Read-back: evOnoffSet (EVCHARGING_REPORT) or bit 0 of switchBits (EDEV_PARAM_REPORT)
    PowerOceanSwitchDescription(
        key="charger_enable",
        translation_key="charger_enable",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:ev-station",
        on_params={PARAM_CHARGER_ENABLE: 1},
        off_params={PARAM_CHARGER_ENABLE: 0},
        is_powerpulse=True,
        state_fields=("evOnoffSet",),
        state_bit_field="switchBits",
        state_bit=0,
    ),
    # ── Grid → battery charging enable ──────────────────────────────────────
    # ACTION_W_CFG_GRID_CHARGE_TO_BATTERY_ENABLE — allow/block grid-to-battery charging
    PowerOceanSwitchDescription(
        key="grid_charge_enable",
        translation_key="grid_charge_enable",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:battery-charging",
        on_params={PARAM_GRID_CHARGE_ENABLE: 1},
        off_params={PARAM_GRID_CHARGE_ENABLE: 0},
    ),
    # ── System pause ─────────────────────────────────────────────────────────
    # ACTION_W_CFG_SYS_PAUSE / ACTION_W_CFG_SYS_RESUME
    PowerOceanSwitchDescription(
        key="system_pause",
        translation_key="system_pause",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:pause-circle-outline",
        on_params={PARAM_SYS_PAUSE: 1},
        off_params={PARAM_SYS_RESUME: 1},
    ),
    # ── Battery cell heating ──────────────────────────────────────────────────
    # ACTION_W_CFG_BMS_BATTERY_HEAT — enables the integrated cell heater in the
    # 5 kWh battery modules.
    PowerOceanSwitchDescription(
        key="battery_heat",
        translation_key="battery_heat",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:heat-wave",
        on_params={PARAM_BATTERY_HEAT: 1},
        off_params={PARAM_BATTERY_HEAT: 0},
    ),
    # ── PowerPulse automatic charging ────────────────────────────────────────
    # ACTION_W_CFG_SP_CHARGER_AUTO_CHG_OPEN — lets the PowerPulse decide the
    # optimal charge window based on solar availability and TOU tariff.
    # Read-back: evUserManual=0 means auto is ON (inverted); bit 1 of switchBits
    # (EDEV_PARAM_REPORT) maps directly.
    PowerOceanSwitchDescription(
        key="charger_auto_chg",
        translation_key="charger_auto_chg",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:ev-station",
        on_params={PARAM_CHARGER_AUTO_CHG: 1},
        off_params={PARAM_CHARGER_AUTO_CHG: 0},
        is_powerpulse=True,
        state_fields=("evUserManual",),
        state_inverted=True,   # evUserManual=0 → auto is active → switch ON
        state_bit_field="switchBits",
        state_bit=1,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up PowerOcean switch entities for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    endpoints = data["endpoints"]

    pp_sn = _find_powerpulse_sn(endpoints, coordinator.api.sn)

    entities = [
        PowerOceanSwitch(coordinator, description, pp_sn=pp_sn)
        for description in SWITCH_DESCRIPTIONS
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


class PowerOceanSwitch(CoordinatorEntity, SwitchEntity):
    """On/off switch for a configurable PowerOcean parameter."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PowerOceanCoordinator,
        description: PowerOceanSwitchDescription,
        pp_sn: str | None = None,
    ) -> None:
        """Initialize the switch entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._on_params = description.on_params
        self._off_params = description.off_params
        self._cached_state: bool | None = None
        self._attr_unique_id = f"{coordinator.api.sn}_{description.key}"
        self._device_sn = (
            pp_sn if (description.is_powerpulse and pp_sn) else coordinator.api.sn
        )

    def _read_coordinator_state(self) -> bool | None:
        """Derive switch state from coordinator.data using configured state fields."""
        desc = self.entity_description
        if not self._device_sn:
            return None
        data = self.coordinator.data or {}
        prefix = self._device_sn + "_"

        # 1. Try simple boolean fields first (evOnoffSet etc.)
        for f in desc.state_fields:
            suffix = "_" + f
            for key, value in data.items():
                if key.startswith(prefix) and key.endswith(suffix):
                    result = bool(value)
                    return (not result) if desc.state_inverted else result

        # 2. Fall back to bitmask field (switchBits)
        if desc.state_bit_field and desc.state_bit is not None:
            suffix = "_" + desc.state_bit_field
            for key, value in data.items():
                if key.startswith(prefix) and key.endswith(suffix):
                    result = bool((int(value) >> desc.state_bit) & 1)
                    return (not result) if desc.state_inverted else result

        return None

    @property
    def is_on(self) -> bool | None:
        """Return current state — live coordinator data preferred, cached as fallback."""
        live = self._read_coordinator_state()
        if live is not None:
            return live
        return self._cached_state

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Send the ON command to the inverter."""
        await self.coordinator.api.async_set_property(self._on_params)
        self._cached_state = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Send the OFF command to the inverter."""
        await self.coordinator.api.async_set_property(self._off_params)
        self._cached_state = False
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._device_sn)})
