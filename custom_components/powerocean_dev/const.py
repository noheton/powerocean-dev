"""Constants for the PowerOcean integration."""

from enum import StrEnum
from logging import Logger, getLogger
from pathlib import Path

from homeassistant.const import Platform

LOGGER: Logger = getLogger(__package__)
DOMAIN = "powerocean_dev"
DEFAULT_SCAN_INTERVAL = 10
DEFAULT_NAME = "PowerOcean"
ISSUE_URL = "https://github.com/niltrip/powerocean/issues"
ISSUE_URL_ERROR_MESSAGE = " Please log any issues here: " + ISSUE_URL
USE_MOCKED_RESPONSE = False  # Set to True to use mocked responses for testing
# Mock path to response.json file
MOCKED_RESPONSE = (
    Path(__file__).parent / "tests" / "fixtures" / "response_modified.json"
)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

ATTR_PRODUCT_DESCRIPTION = "Product Description"
ATTR_PRODUCT_SERIAL = "Vendor Product Serial"

# ── EcoFlow consumer API write endpoint (APK: /iot-devices/device/setDeviceProperty) ──
API_WRITE_ENDPOINT = "/iot-devices/device/setDeviceProperty"

# ── Write-command parameter keys (camelCase proto field names from APK analysis) ──
# Backup / energy management
PARAM_BACKUP_RESERVE_SOC = "cfgBackupReverseSoc"
PARAM_BACKUP_SOC_VPP = "cfgBackupSocVpp"
PARAM_BACKUP_BOX_MODE = "cfgBackupBoxMode"

# Grid
PARAM_GRID_CHARGE_ENABLE = "cfgGridChargeToBatteryEnable"
PARAM_GRID_IN_PWR_LIMIT = "cfgSysGridInPwrLimit"

# SP (SmartPower / EV charger)
PARAM_CHARGER_ENABLE = "cfgSpChargerChgOpen"
PARAM_CHARGER_MODE = "cfgSpChargerChgMode"
PARAM_CHARGER_POWER_LIMIT = "cfgSpChargerChgPowLimit"
PARAM_CHARGER_AMP_LIMIT = "cfgSpChargerDevBattChgAmpLimit"
PARAM_CHARGER_AUTO_CHG = "cfgSpChargerAutoChgOpen"
PARAM_FAST_CHG_MAX_SOC = "cfgSpFastChgMaxSoc"

# BMS (Battery Management System)
# ACTION_W_CFG_BMS_BATTERY_HEAT — enable/disable battery cell heating for cold climates
PARAM_BATTERY_HEAT = "cfgBmsBatteryHeat"

# System lifecycle (active commands — trigger once)
PARAM_SYS_PAUSE = "cfgSysPause"
PARAM_SYS_RESUME = "cfgSysResume"
PARAM_SYS_REBOOT = "activeSysReboot"
PARAM_SYS_SELFCHECK = "activeSysSelfcheck"

# ── Keys that must be represented as binary_sensor (not regular sensor) ──
# Sourced from EMS_HEARTBEAT and DEFAULT reports that contain boolean states/error flags
BINARY_SENSOR_KEYS: frozenset[str] = frozenset(
    {
        "online",
        "epoSwitchState",
        "autoDetectStartPowerEn",
        "isPvToInvDirectly",
        "emsBpSelfcheckState",
        "emsMpptSelfcheckState",
        "emsMpptRunState",
    }
)


class PowerOceanModel(StrEnum):
    """Enumeration of supported PowerOcean device models with their internal codes."""

    POWEROCEAN = "83"
    POWEROCEAN_DC_FIT = "85"
    POWEROCEAN_SINGLE_PHASE = "86"
    POWEROCEAN_PLUS = "87"


MODEL_NAME_MAP = {
    PowerOceanModel.POWEROCEAN: "PowerOcean",
    PowerOceanModel.POWEROCEAN_DC_FIT: "PowerOcean DC fit",
    PowerOceanModel.POWEROCEAN_SINGLE_PHASE: "PowerOcean Single Phase",
    PowerOceanModel.POWEROCEAN_PLUS: "PowerOcean Plus",
}
