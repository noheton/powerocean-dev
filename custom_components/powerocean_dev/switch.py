"""PowerOcean switch platform — on/off controllable parameters.

APK sources (CFG_*_FIELD_NUMBER → camelCase write key):
  CFG_SP_CHARGER_CHG_OPEN_FIELD_NUMBER          → cfgSpChargerChgOpen
  CFG_GRID_CHARGE_TO_BATTERY_ENABLE_FIELD_NUMBER → cfgGridChargeToBatteryEnable
  CFG_SYS_PAUSE_FIELD_NUMBER / CFG_SYS_RESUME_FIELD_NUMBER → cfgSysPause / cfgSysResume

Equipment (doc/equipment.md):
  12 kW PowerOcean, 2 × 5 kWh batteries, 11 kW PowerPulse (AC31ZEH4AG130052)
"""

from dataclasses import dataclass
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

    # Payload written when the switch is turned ON
    on_params: dict[str, Any] = None  # type: ignore[assignment]
    # Payload written when the switch is turned OFF
    off_params: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.on_params is None:
            object.__setattr__(self, "on_params", {})
        if self.off_params is None:
            object.__setattr__(self, "off_params", {})


SWITCH_DESCRIPTIONS: list[PowerOceanSwitchDescription] = [
    # ── PowerPulse (SP / EV charger) enable ──────────────────────────────────
    # ACTION_W_CFG_SP_CHARGER_CHG_OPEN — enable/disable the 11 kW PowerPulse
    PowerOceanSwitchDescription(
        key="charger_enable",
        translation_key="charger_enable",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:ev-station",
        on_params={PARAM_CHARGER_ENABLE: 1},
        off_params={PARAM_CHARGER_ENABLE: 0},
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
    # Useful for HA energy automations that need to suspend inverter output.
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
    # 5 kWh battery modules.  Critical for cold-climate operation to maintain
    # charge acceptance and prevent degradation below 0 °C.
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
    PowerOceanSwitchDescription(
        key="charger_auto_chg",
        translation_key="charger_auto_chg",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:ev-station",
        on_params={PARAM_CHARGER_AUTO_CHG: 1},
        off_params={PARAM_CHARGER_AUTO_CHG: 0},
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up PowerOcean switch entities for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    entities = [
        PowerOceanSwitch(coordinator, description)
        for description in SWITCH_DESCRIPTIONS
    ]
    async_add_entities(entities)


class PowerOceanSwitch(CoordinatorEntity, SwitchEntity):
    """On/off switch for a configurable PowerOcean parameter."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PowerOceanCoordinator,
        description: PowerOceanSwitchDescription,
    ) -> None:
        """Initialize the switch entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._on_params = description.on_params
        self._off_params = description.off_params
        self._cached_state: bool | None = None
        self._attr_unique_id = f"{coordinator.api.sn}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return the cached switch state (None until first user interaction)."""
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
        """Attach to the main inverter device."""
        return DeviceInfo(identifiers={(DOMAIN, self.coordinator.api.sn)})
