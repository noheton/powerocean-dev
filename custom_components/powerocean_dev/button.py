"""
PowerOcean button platform — momentary hardware actions.

APK sources:
  ACTION_W_ACTIVE_SYS_REBOOT   → param key activeSysReboot
  ACTION_W_ACTIVE_SYS_SELFCHECK → param key activeSysSelfcheck

Both commands are sent via async_set_property with value=1 (trigger).
"""

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PARAM_SYS_REBOOT, PARAM_SYS_SELFCHECK
from .coordinator import PowerOceanCoordinator

BUTTON_DESCRIPTIONS: list[tuple[ButtonEntityDescription, dict]] = [
    (
        ButtonEntityDescription(
            key="system_reboot",
            translation_key="system_reboot",
            entity_category=EntityCategory.CONFIG,
            icon="mdi:restart",
        ),
        {PARAM_SYS_REBOOT: 1},
    ),
    (
        ButtonEntityDescription(
            key="system_selfcheck",
            translation_key="system_selfcheck",
            entity_category=EntityCategory.CONFIG,
            icon="mdi:check-circle-outline",
        ),
        {PARAM_SYS_SELFCHECK: 1},
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up PowerOcean button entities for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    entities = [
        PowerOceanButton(coordinator, description, params)
        for description, params in BUTTON_DESCRIPTIONS
    ]
    async_add_entities(entities)


class PowerOceanButton(CoordinatorEntity, ButtonEntity):
    """Button that triggers a one-shot command on the PowerOcean inverter."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PowerOceanCoordinator,
        description: ButtonEntityDescription,
        params: dict,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._params = params
        self._attr_unique_id = f"{coordinator.api.sn}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Attach button to the main inverter device."""
        return DeviceInfo(identifiers={(DOMAIN, self.coordinator.api.sn)})

    async def async_press(self) -> None:
        """Send the trigger command to the inverter."""
        await self.coordinator.api.async_set_property(self._params)
