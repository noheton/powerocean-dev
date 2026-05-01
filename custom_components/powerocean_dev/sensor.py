"""PowerOcean sensor platform — 2026 EntityDescription architecture."""

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BINARY_SENSOR_KEYS, DOMAIN
from .coordinator import PowerOceanCoordinator
from .types import PowerOceanEndPoint

# ── Static EntityDescription registry ────────────────────────────────────────
# Keys that appear in REPORT_DATAPOINTS or are computed by the parser.
# Sensors not listed here fall back to regex-inferred metadata (SensorClassHelper).
# state_class is mandatory for all numeric sensors so the Statistics and
# Energy Dashboard can consume them automatically.

SENSOR_DESCRIPTIONS: dict[str, SensorEntityDescription] = {
    # ── Whole-system power (measurement, W) ──────────────────────────────────
    "sysLoadPwr": SensorEntityDescription(
        key="sysLoadPwr",
        translation_key="sys_load_pwr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "sysGridPwr": SensorEntityDescription(
        key="sysGridPwr",
        translation_key="sys_grid_pwr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "mpptPwr": SensorEntityDescription(
        key="mpptPwr",
        translation_key="mppt_pwr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "bpPwr": SensorEntityDescription(
        key="bpPwr",
        translation_key="bp_pwr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "dcdcPwr": SensorEntityDescription(
        key="dcdcPwr",
        translation_key="dcdc_pwr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "pcsActPwr": SensorEntityDescription(
        key="pcsActPwr",
        translation_key="pcs_act_pwr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "pcsMeterPower": SensorEntityDescription(
        key="pcsMeterPower",
        translation_key="pcs_meter_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    # ── Computed energy-flow sensors (measurement, W) ────────────────────────
    "housePower": SensorEntityDescription(
        key="housePower",
        translation_key="house_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "gridPower": SensorEntityDescription(
        key="gridPower",
        translation_key="grid_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "gridToBattery": SensorEntityDescription(
        key="gridToBattery",
        translation_key="grid_to_battery",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "gridToHouse": SensorEntityDescription(
        key="gridToHouse",
        translation_key="grid_to_house",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "batteryToHouse": SensorEntityDescription(
        key="batteryToHouse",
        translation_key="battery_to_house",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "solarToBattery": SensorEntityDescription(
        key="solarToBattery",
        translation_key="solar_to_battery",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "solarToGrid": SensorEntityDescription(
        key="solarToGrid",
        translation_key="solar_to_grid",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "solarToHouse": SensorEntityDescription(
        key="solarToHouse",
        translation_key="solar_to_house",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    # MPPT total PV power (computed in parser)
    "mpptPv_pwrTotal": SensorEntityDescription(
        key="mpptPv_pwrTotal",
        translation_key="mppt_pv_pwr_total",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    # ── Per-MPPT-string power (measurement, W) ───────────────────────────────
    "pv1Pwr": SensorEntityDescription(
        key="pv1Pwr",
        translation_key="pv1_pwr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "pv2Pwr": SensorEntityDescription(
        key="pv2Pwr",
        translation_key="pv2_pwr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "pv3Pwr": SensorEntityDescription(
        key="pv3Pwr",
        translation_key="pv3_pwr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "pvInvPwr": SensorEntityDescription(
        key="pvInvPwr",
        translation_key="pv_inv_pwr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "otherPvPwr": SensorEntityDescription(
        key="otherPvPwr",
        translation_key="other_pv_pwr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "loadPwr": SensorEntityDescription(
        key="loadPwr",
        translation_key="load_pwr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "heatingPower": SensorEntityDescription(
        key="heatingPower",
        translation_key="heating_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # ── Energy generation totals (total_increasing, kWh) — Energy Dashboard ──
    "todayElectricityGeneration": SensorEntityDescription(
        key="todayElectricityGeneration",
        translation_key="today_electricity_generation",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
    ),
    "monthElectricityGeneration": SensorEntityDescription(
        key="monthElectricityGeneration",
        translation_key="month_electricity_generation",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
    ),
    "yearElectricityGeneration": SensorEntityDescription(
        key="yearElectricityGeneration",
        translation_key="year_electricity_generation",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
    ),
    "totalElectricityGeneration": SensorEntityDescription(
        key="totalElectricityGeneration",
        translation_key="total_electricity_generation",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
    ),
    # ── Day-energy counters (total_increasing, Wh) — EMS heartbeat ──────────
    "gridOutDayEnergy": SensorEntityDescription(
        key="gridOutDayEnergy",
        translation_key="grid_out_day_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "gridInDayEnergy": SensorEntityDescription(
        key="gridInDayEnergy",
        translation_key="grid_in_day_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "bpInDayEnergy": SensorEntityDescription(
        key="bpInDayEnergy",
        translation_key="bp_in_day_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "bpOutDayEnergy": SensorEntityDescription(
        key="bpOutDayEnergy",
        translation_key="bp_out_day_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "loadDayEnergy": SensorEntityDescription(
        key="loadDayEnergy",
        translation_key="load_day_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "pvInDayEnergy": SensorEntityDescription(
        key="pvInDayEnergy",
        translation_key="pv_in_day_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    # ── Battery lifetime energy counters (total_increasing, Wh) ─────────────
    "bpTotalChgEnergy": SensorEntityDescription(
        key="bpTotalChgEnergy",
        translation_key="bp_total_chg_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "bpTotalDsgEnergy": SensorEntityDescription(
        key="bpTotalDsgEnergy",
        translation_key="bp_total_dsg_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "bpAccuChgEnergy": SensorEntityDescription(
        key="bpAccuChgEnergy",
        translation_key="bp_accu_chg_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "bpAccuDsgEnergy": SensorEntityDescription(
        key="bpAccuDsgEnergy",
        translation_key="bp_accu_dsg_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    # ── Battery state (measurement) ──────────────────────────────────────────
    "bpSoc": SensorEntityDescription(
        key="bpSoc",
        translation_key="bp_soc",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "bpSoh": SensorEntityDescription(
        key="bpSoh",
        translation_key="bp_soh",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "bpVol": SensorEntityDescription(
        key="bpVol",
        translation_key="bp_vol",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "bpAmp": SensorEntityDescription(
        key="bpAmp",
        translation_key="bp_amp",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "bpRemainWatth": SensorEntityDescription(
        key="bpRemainWatth",
        translation_key="bp_remain_watth",
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "bpCycles": SensorEntityDescription(
        key="bpCycles",
        translation_key="bp_cycles",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:repeat",
    ),
    "bpEnvTemp": SensorEntityDescription(
        key="bpEnvTemp",
        translation_key="bp_env_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "bpMinCellTemp": SensorEntityDescription(
        key="bpMinCellTemp",
        translation_key="bp_min_cell_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "bpMaxCellTemp": SensorEntityDescription(
        key="bpMaxCellTemp",
        translation_key="bp_max_cell_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ── Grid-connection metering (measurement) ────────────────────────────────
    "meterAVoltage": SensorEntityDescription(
        key="meterAVoltage",
        translation_key="meter_a_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "meterBVoltage": SensorEntityDescription(
        key="meterBVoltage",
        translation_key="meter_b_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "meterCVoltage": SensorEntityDescription(
        key="meterCVoltage",
        translation_key="meter_c_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "meterACurrent": SensorEntityDescription(
        key="meterACurrent",
        translation_key="meter_a_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "meterBCurrent": SensorEntityDescription(
        key="meterBCurrent",
        translation_key="meter_b_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "meterCCurrent": SensorEntityDescription(
        key="meterCCurrent",
        translation_key="meter_c_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "meterPowerFactor": SensorEntityDescription(
        key="meterPowerFactor",
        translation_key="meter_power_factor",
        device_class=SensorDeviceClass.POWER_FACTOR,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ── EV charger (PowerPulse / SP) ─────────────────────────────────────────
    "evPwr": SensorEntityDescription(
        key="evPwr",
        translation_key="ev_pwr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "evChargingEnergy": SensorEntityDescription(
        key="evChargingEnergy",
        translation_key="ev_charging_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    "chargingPwr": SensorEntityDescription(
        key="chargingPwr",
        translation_key="charging_pwr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # ── PowerPulse / EV charger — EDEV_PARAM_REPORT + EDEV_SYS_REPORT ──────────
    "chargingStatus": SensorEntityDescription(
        key="chargingStatus",
        translation_key="pp_charging_status",
        icon="mdi:ev-station",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "workMode": SensorEntityDescription(
        key="workMode",
        translation_key="pp_work_mode",
        icon="mdi:ev-station",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "chargeTarget": SensorEntityDescription(
        key="chargeTarget",
        translation_key="pp_charge_target",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "timeToUseCar": SensorEntityDescription(
        key="timeToUseCar",
        translation_key="pp_time_to_use_car",
        icon="mdi:clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "allocatedPower": SensorEntityDescription(
        key="allocatedPower",
        translation_key="pp_allocated_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "feedPwrCap": SensorEntityDescription(
        key="feedPwrCap",
        translation_key="pp_feed_pwr_cap",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "socCur": SensorEntityDescription(
        key="socCur",
        translation_key="pp_soc_cur",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # Internal / diagnostic — not useful for day-to-day dashboards
    "switchBits": SensorEntityDescription(
        key="switchBits",
        translation_key="pp_switch_bits",
        icon="mdi:toggle-switch-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "userCurrentSet": SensorEntityDescription(
        key="userCurrentSet",
        translation_key="pp_user_current_set",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "currentOuputMax": SensorEntityDescription(
        key="currentOuputMax",
        translation_key="pp_current_ouput_max",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "devSn": SensorEntityDescription(
        key="devSn",
        translation_key="pp_dev_sn",
        icon="mdi:barcode",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "startState": SensorEntityDescription(
        key="startState",
        translation_key="pp_start_state",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "realPowerLock": SensorEntityDescription(
        key="realPowerLock",
        translation_key="pp_real_power_lock",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "refPower": SensorEntityDescription(
        key="refPower",
        translation_key="pp_ref_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "pclPwrBase": SensorEntityDescription(
        key="pclPwrBase",
        translation_key="pp_pcl_pwr_base",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ── PowerPulse / EV charger — EVCHARGING_REPORT ──────────────────────────
    "evOnoffSet": SensorEntityDescription(
        key="evOnoffSet",
        translation_key="pp_ev_onoff_set",
        icon="mdi:ev-station",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "evCurrSet": SensorEntityDescription(
        key="evCurrSet",
        translation_key="pp_ev_curr_set",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "evUserManual": SensorEntityDescription(
        key="evUserManual",
        translation_key="pp_ev_user_manual",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "useGridFirst": SensorEntityDescription(
        key="useGridFirst",
        translation_key="pp_use_grid_first",
        icon="mdi:transmission-tower-import",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "evSn": SensorEntityDescription(
        key="evSn",
        translation_key="pp_ev_sn",
        icon="mdi:barcode",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "onlineBits": SensorEntityDescription(
        key="onlineBits",
        translation_key="pp_online_bits",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "chargeVehicleId": SensorEntityDescription(
        key="chargeVehicleId",
        translation_key="pp_charge_vehicle_id",
        icon="mdi:car",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    "orderStartTimestamp": SensorEntityDescription(
        key="orderStartTimestamp",
        translation_key="pp_order_start_timestamp",
        icon="mdi:clock-start",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ── Heating rod / PowerGlow ───────────────────────────────────────────────
    "hrPwr": SensorEntityDescription(
        key="hrPwr",
        translation_key="hr_pwr",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "temp": SensorEntityDescription(
        key="temp",
        translation_key="hr_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "targetTemp": SensorEntityDescription(
        key="targetTemp",
        translation_key="hr_target_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # ── Diagnostic / metadata ─────────────────────────────────────────────────
    "moduleAplSwVer": SensorEntityDescription(
        key="moduleAplSwVer",
        translation_key="module_sw_ver",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:chip",
    ),
    "systemName": SensorEntityDescription(
        key="systemName",
        translation_key="system_name",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:label-outline",
    ),
    "emsBpAliveNum": SensorEntityDescription(
        key="emsBpAliveNum",
        translation_key="ems_bp_alive_num",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:package-check",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    "bpOnlineSum": SensorEntityDescription(
        key="bpOnlineSum",
        translation_key="bp_online_sum",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:package-check",
        state_class=SensorStateClass.MEASUREMENT,
    ),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up PowerOcean sensors for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    endpoints = data["endpoints"]

    entities = [
        PowerOceanSensor(coordinator, endpoint)
        for endpoint in endpoints.values()
        if endpoint.friendly_name not in BINARY_SENSOR_KEYS
    ]

    async_add_entities(entities)


class PowerOceanSensor(CoordinatorEntity, SensorEntity):
    """Representation of a PowerOcean Sensor using DataUpdateCoordinator."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: PowerOceanCoordinator, endpoint: PowerOceanEndPoint
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.endpoint = endpoint
        self._endpoint_id = endpoint.internal_unique_id
        self._endpoint_serial = endpoint.serial
        self._endpoint_device_info = endpoint.device_info

        key = endpoint.friendly_name

        if description := SENSOR_DESCRIPTIONS.get(key):
            # Known sensor: use the static EntityDescription (full statistics support)
            self.entity_description = description
        else:
            # Unknown / dynamically-discovered sensor: fall back to regex inference
            (
                self._attr_device_class,
                self._attr_native_unit_of_measurement,
                self._attr_state_class,
            ) = getattr(endpoint, "cls", None) or (None, None, None)
            self._attr_name = key
            self._attr_icon = endpoint.icon
            if self._attr_native_unit_of_measurement is None:
                self._attr_entity_category = EntityCategory.DIAGNOSTIC

        self._attr_unique_id = self._endpoint_id

    @property
    def native_value(self) -> Any:
        """Return the current value from coordinator data."""
        return self.coordinator.data.get(self._endpoint_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return product serial as an extra attribute."""
        if self._endpoint_serial:
            return {"product_serial": self._endpoint_serial}
        return {}

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device info for Home Assistant device registry."""
        return self._endpoint_device_info
