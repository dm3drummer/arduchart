"""Schema chart mapping -- maps ArduPilot pdef.json groups to chart families."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# Maps logical chart family name -> list of pdef.json group prefixes
SCHEMA_CHART_MAP: dict[str, list[str]] = {
    "ahrs":            ["AHRS_"],
    "airspeed":        ["ARSPD", "ARSPD_", "ARSPD2_", "ARSPD3_", "ARSPD4_",
                        "ARSPD5_", "ARSPD6_"],
    "arming":          ["ARMING_"],
    "barometer":       ["BARO", "BARO1_WCF_", "BARO2_WCF_", "BARO3_WCF_"],
    "battery":         ["BATT_", "BATT2_", "BATT3_", "BATT4_", "BATT5_",
                        "BATT6_", "BATT7_", "BATT8_", "BATT9_", "BATTA_",
                        "BATTB_", "BATTC_", "BATTD_", "BATTE_", "BATTF_",
                        "BATTG_"],
    "board":           ["BRD_", "BRD_RADIO", "BRD_RTC"],
    "camera":          ["CAM", "CAM1", "CAM1_RC_", "CAM2", "CAM2_RC_"],
    "can_bus":         ["CAN_", "CAN_D1_", "CAN_D1_PC_", "CAN_D1_UC_",
                        "CAN_D2_", "CAN_D2_PC_", "CAN_D2_UC_",
                        "CAN_D3_", "CAN_D3_PC_", "CAN_D3_UC_",
                        "CAN_P1_", "CAN_P2_", "CAN_P3_", "CAN_SLCAN_"],
    "compass":         ["COMPASS_", "COMPASS_PMOT"],
    "ekf":             ["EK2_", "EK3_", "EK3_SRC"],
    "fence":           ["FENCE_"],
    "flight_control":  ["Plane", "PTCH", "RLL", "YAW", "NAVL1_", "TECS_",
                        "STEER2SRV_", "GUIDED_"],
    "gps":             ["GPS", "GPS1_", "GPS1_MB_", "GPS2_", "GPS2_MB_",
                        "GPS_MB1_", "GPS_MB2_"],
    "imu":             ["INS", "INS4_", "INS4_TCAL_", "INS5_", "INS5_TCAL_",
                        "INS_HNTC2_", "INS_HNTC3_", "INS_HNTC4_",
                        "INS_HNTCH_", "INS_LOG_",
                        "INS_TCAL1_", "INS_TCAL2_", "INS_TCAL3_",
                        "FFT_", "FILT1_", "FILT2_", "FILT3_", "FILT4_",
                        "FILT5_", "FILT6_", "FILT7_", "FILT8_"],
    "landing":         ["LAND_", "LAND_DS_", "AUTOLAND_", "TKOFF_"],
    "logging":         ["LOG"],
    "mavlink":         ["MAV", "MAV1", "MAV2", "MAV3", "MAV4", "MAV5",
                        "MAV6", "MAV7", "MAV8", "MAV9", "MAV10", "MAV11",
                        "MAV12", "MAV13", "MAV14", "MAV15", "MAV16",
                        "MAV17", "MAV18", "MAV19", "MAV20", "MAV21",
                        "MAV22", "MAV23", "MAV24", "MAV25", "MAV26",
                        "MAV27", "MAV28", "MAV29", "MAV30", "MAV31",
                        "MAV32"],
    "mission":         ["MIS_", "RALLY_"],
    "mount":           ["MNT1", "MNT2"],
    "networking":      ["NET_", "NET_GWADDR", "NET_IPADDR", "NET_MACADDR",
                        "NET_P1_", "NET_P1_IP", "NET_P2_", "NET_P2_IP",
                        "NET_P3_", "NET_P3_IP", "NET_P4_", "NET_P4_IP",
                        "NET_REMPPP_IP", "NET_TEST_IP", "DDS", "DDS_IP",
                        "MSP"],
    "notifications":   ["NTF_", "FRSKY_", "BTN_"],
    "osd":             ["OSD", "OSD1_", "OSD2_", "OSD3_", "OSD4_",
                        "OSD5_", "OSD5_PARAM1", "OSD5_PARAM2", "OSD5_PARAM3",
                        "OSD5_PARAM4", "OSD5_PARAM5", "OSD5_PARAM6",
                        "OSD5_PARAM7", "OSD5_PARAM8", "OSD5_PARAM9",
                        "OSD6_", "OSD6_PARAM1", "OSD6_PARAM2", "OSD6_PARAM3",
                        "OSD6_PARAM4", "OSD6_PARAM5", "OSD6_PARAM6",
                        "OSD6_PARAM7", "OSD6_PARAM8", "OSD6_PARAM9"],
    "parachute":       ["CHUTE_"],
    "quadplane":       ["Q_", "Q_A_", "Q_AUTOTUNE_", "Q_LOIT_", "Q_M_",
                        "Q_P", "Q_TAILSIT_", "Q_TILT_", "Q_WP_", "Q_WVANE_",
                        "QWIK_"],
    "rangefinder":     ["RNGFND1_", "RNGFND2_", "RNGFND3_", "RNGFND4_",
                        "RNGFND5_", "RNGFND6_", "RNGFND7_", "RNGFND8_",
                        "RNGFND9_", "RNGFNDA_", "PLND_"],
    "rc":              ["RC", "RC1_", "RC2_", "RC3_", "RC4_", "RC5_", "RC6_",
                        "RC7_", "RC8_", "RC9_", "RC10_", "RC11_", "RC12_",
                        "RC13_", "RC14_", "RC15_", "RC16_", "RCMAP_"],
    "relay":           ["RELAY1_", "RELAY2_", "RELAY3_", "RELAY4_",
                        "RELAY5_", "RELAY6_", "RELAY7_", "RELAY8_",
                        "RELAY9_", "RELAY10_", "RELAY11_", "RELAY12_",
                        "RELAY13_", "RELAY14_", "RELAY15_", "RELAY16_"],
    "rpm":             ["RPM1_", "RPM2_", "RPM3_", "RPM4_"],
    "safety":          ["AFS_", "AVD_", "ADSB_"],
    "scheduler":       ["SCHED_"],
    "scripting":       ["SCR_"],
    "serial":          ["SERIAL"],
    "servo":           ["SERVO", "SERVO1_", "SERVO2_", "SERVO3_", "SERVO4_",
                        "SERVO5_", "SERVO6_", "SERVO7_", "SERVO8_",
                        "SERVO9_", "SERVO10_", "SERVO11_", "SERVO12_",
                        "SERVO13_", "SERVO14_", "SERVO15_", "SERVO16_",
                        "SERVO17_", "SERVO18_", "SERVO19_", "SERVO20_",
                        "SERVO21_", "SERVO22_", "SERVO23_", "SERVO24_",
                        "SERVO25_", "SERVO26_", "SERVO27_", "SERVO28_",
                        "SERVO29_", "SERVO30_", "SERVO31_", "SERVO32_",
                        "SERVO_BLH_", "SERVO_FTW_", "SERVO_ROB_",
                        "SERVO_SBUS_", "SERVO_VOLZ_"],
    "soaring":         ["SOAR_"],
    "terrain":         ["TERRAIN_"],
    "temperature":     ["TEMP", "TEMP1_", "TEMP2_", "TEMP3_", "TEMP4_",
                        "TEMP5_", "TEMP6_", "TEMP7_", "TEMP8_", "TEMP9_",
                        "TEMP10_", "TEMP11_", "TEMP12_", "TEMP13_",
                        "TEMP14_", "TEMP15_"],
    "vtx":             ["VTX_"],
    "visual_odometry": ["VISO"],
    "optical_flow":    ["FLOW"],
    "follow":          ["FOLL"],
    "engine":          ["ICE_", "EFI", "EFI_THRLIN", "GEN_", "GEN_L_",
                        "ESC_TLM"],
    "landing_gear":    ["LGR_"],
    "rssi":            ["RSSI_"],
    "ais":             ["AIS_"],
    "eahrs":           ["EAHRS"],
    "gripper":         ["GRIP_"],
    "nmea":            ["NMEA_"],
    "power_up":        ["PUP_"],
    "tuning":          ["TUNE_"],
    "statistics":      ["STAT"],
    "device_id":       ["DID_"],
    "custom_rotation": ["CUST_ROT", "CUST_ROT1_", "CUST_ROT2_"],
    "kde_esc":         ["KDE_"],
    "sid":             ["SID"],
}


def _build_pdef_group_to_family() -> dict[str, str]:
    """Build reverse map: pdef group prefix -> chart family name."""
    result: dict[str, str] = {}
    for family, groups in SCHEMA_CHART_MAP.items():
        for group in groups:
            result[group] = family
    return result


PDEF_GROUP_TO_FAMILY = _build_pdef_group_to_family()


def build_schema_charts_data(config_dir: str | Path) -> dict[str, list[str]]:
    """Read pdef.json and group params into chart families.

    Returns {family_name: [param_name, ...]} sorted within each family.
    Raises FileNotFoundError if the pdef cache is missing.
    """
    config_dir = Path(config_dir)
    cache = config_dir / ".cache" / "apm.pdef.json"
    if not cache.exists():
        raise FileNotFoundError(
            "Param schema not found. Run: arducharts schema-update"
        )

    raw: dict[str, Any] = json.loads(cache.read_text())
    families: dict[str, list[str]] = {}

    for group_name, params in raw.items():
        if not isinstance(params, dict) or not group_name:
            continue
        # Skip simulator-only params
        if group_name.startswith("SIM"):
            continue

        family = PDEF_GROUP_TO_FAMILY.get(group_name, "_unmapped")
        families.setdefault(family, []).extend(params.keys())

    # Sort and deduplicate params within each family
    for family in families:
        families[family] = sorted(set(families[family]))

    return families
