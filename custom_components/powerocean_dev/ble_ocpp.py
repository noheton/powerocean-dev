"""
BLE OCPP activation for EcoFlow PowerPulse (AC305) charger.

Reverse-engineered from EcoFlow Pro APK (com.ecoflow.pro):
- Protocol:  EcoOdmProtocol / EcoOdmPacket
- Service:   0000fff0-0000-1000-8000-00805f9b34fb
- Auth key:  MD5_uppercase(userId + sn) as ASCII bytes
- Cmd 513:   AUTH_STATUS  – query current auth state
- Cmd 514:   AUTH_WRITE   – first-time bind (setOdmAuthentication)
- Cmd 515:   AUTH_CHECK   – re-verify existing bind (checkOdmAuthentication)
- Cmd 770:   SETTING_NETWORK – write WiFi + OCPP URL

BLE advertisement name pattern (observed):
  "EF-" + sn[0:4] + sn[-4:]
  e.g. SN "AC31ZEH4AG130052" → "EF-AC310052"
       SN "HJ37ZDH5ZG5W0109" → "EF-HJ370109"   (inverter)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# ── GATT UUIDs ────────────────────────────────────────────────────────────────
ECOFLOW_ODM_SERVICE = "0000fff0-0000-1000-8000-00805f9b34fb"

# ── Command IDs (TreatyConstantsByOdm.java) ──────────────────────────────────
CMD_AUTH_STATUS = 513    # 0x0201
CMD_AUTH_WRITE = 514     # 0x0202  setOdmAuthentication
CMD_AUTH_CHECK = 515     # 0x0203  checkOdmAuthentication
CMD_SETTING_NETWORK = 770  # 0x0302  WiFi + OCPP URL

# ── Per-address connection lock (prevents simultaneous BLE sessions) ──────────
# Key: normalised BLE MAC address.  One asyncio.Lock per charger address so
# that two HA automations firing at the same time queue rather than race.
_BLE_LOCKS: dict[str, asyncio.Lock] = {}


def _ble_lock(address: str) -> asyncio.Lock:
    key = address.upper()
    if key not in _BLE_LOCKS:
        _BLE_LOCKS[key] = asyncio.Lock()
    return _BLE_LOCKS[key]


# ── CRC tables (CrcUtils.java) ───────────────────────────────────────────────
_CRC8_TABLE = [
    0, 7, 14, 9, 28, 27, 18, 21, 56, 63, 54, 49, 36, 35, 42, 45,
    112, 119, 126, 121, 108, 107, 98, 101, 72, 79, 70, 65, 84, 83, 90, 93,
    224, 231, 238, 233, 252, 251, 242, 245, 216, 223, 214, 209, 196, 195, 202, 205,
    144, 151, 158, 153, 140, 139, 130, 133, 168, 175, 166, 161, 180, 179, 186, 189,
    199, 192, 201, 206, 219, 220, 213, 210, 255, 248, 241, 246, 227, 228, 237, 234,
    183, 176, 185, 190, 171, 172, 165, 162, 143, 136, 129, 134, 147, 148, 157, 154,
    39, 32, 41, 46, 59, 60, 53, 50, 31, 24, 17, 22, 3, 4, 13, 10,
    87, 80, 89, 94, 75, 76, 69, 66, 111, 104, 97, 102, 115, 116, 125, 122,
    137, 142, 135, 128, 149, 146, 155, 156, 177, 182, 191, 184, 173, 170, 163, 164,
    249, 254, 247, 240, 229, 226, 235, 236, 193, 198, 207, 200, 221, 218, 211, 212,
    105, 110, 103, 96, 117, 114, 123, 124, 81, 86, 95, 88, 77, 74, 67, 68,
    25, 30, 23, 16, 5, 2, 11, 12, 33, 38, 47, 40, 61, 58, 51, 52,
    78, 73, 64, 71, 82, 85, 92, 91, 118, 113, 120, 127, 106, 109, 100, 99,
    62, 57, 48, 55, 34, 37, 44, 43, 6, 1, 8, 15, 26, 29, 20, 19,
    174, 169, 160, 167, 178, 181, 188, 187, 150, 145, 152, 159, 138, 141, 132, 131,
    222, 217, 208, 215, 194, 197, 204, 203, 230, 225, 232, 239, 250, 253, 244, 243,
]

_CRC16_TABLE = [
    0, 49345, 49537, 320, 49921, 960, 640, 49729, 50689, 1728, 1920, 51009,
    1280, 50625, 50305, 1088, 52225, 3264, 3456, 52545, 3840, 53185, 52865, 3648,
    2560, 51905, 52097, 2880, 51457, 2496, 2176, 51265, 55297, 6336, 6528, 55617,
    6912, 56257, 55937, 6720, 7680, 57025, 57217, 7936, 56577, 7616, 7296, 56385,
    5120, 54465, 54657, 5440, 55041, 6080, 5760, 54849, 53761, 4800, 4992, 54081,
    4352, 53697, 53377, 4160, 61441, 12480, 12672, 61761, 13056, 62401, 62081, 12864,
    13824, 63169, 63361, 14144, 62721, 13760, 13440, 62529, 15360, 64705, 64897, 15680,
    65281, 16320, 16000, 65089, 64001, 15040, 15232, 64321, 14592, 63937, 63617, 14400,
    10240, 59585, 59777, 10560, 60161, 11200, 10880, 59969, 60929, 11968, 12160, 61249,
    11520, 60865, 60545, 11328, 58369, 9408, 9600, 58689, 9984, 59329, 59009, 9792,
    8704, 58049, 58241, 9024, 57601, 8640, 8320, 57409, 40961, 24768, 24960, 41281,
    25344, 41921, 41601, 25152, 26112, 42689, 42881, 26432, 42241, 26048, 25728, 42049,
    27648, 44225, 44417, 27968, 44801, 28608, 28288, 44609, 43521, 27328, 27520, 43841,
    26880, 43457, 43137, 26688, 30720, 47297, 47489, 31040, 47873, 31680, 31360, 47681,
    48641, 32448, 32640, 48961, 32000, 48577, 48257, 31808, 46081, 29888, 30080, 46401,
    30464, 47041, 46721, 30272, 29184, 45761, 45953, 29504, 45313, 29120, 28800, 45121,
    20480, 37057, 37249, 20800, 37633, 21440, 21120, 37441, 38401, 22208, 22400, 38721,
    21760, 38337, 38017, 21568, 39937, 23744, 23936, 40257, 24320, 40897, 40577, 24128,
    23040, 39617, 39809, 23360, 39169, 22976, 22656, 38977, 34817, 18624, 18816, 35137,
    19200, 35777, 35457, 19008, 19968, 36545, 36737, 20288, 36097, 19904, 19584, 35905,
    17408, 33985, 34177, 17728, 34561, 18368, 18048, 34369, 33281, 17088, 17280, 33601,
    16640, 33217, 32897, 16448,
]


def _crc8(data: bytes) -> int:
    val = 0
    for b in data:
        val = _CRC8_TABLE[(val ^ b) & 0xFF]
    return val


def _crc16(data: bytes) -> int:
    val = 0
    for b in data:
        val = _CRC16_TABLE[(val ^ b) & 0xFF] ^ (val >> 8)
    return val


def build_odm_packet(cmd_id: int, payload: bytes) -> bytes:
    """
    Build a complete EcoOdmPacket wire frame.

    Frame layout (from IEcoProtocolPacket.commandToOdmByte):
      [0x7E][version=1][flag=0][len_lo][len_hi]   ← header (5 bytes)
      [CRC8(header)]                               ← 1 byte
      [seq_lo=0][seq_hi=0]                         ← 2 bytes
      [cmdId_lo][cmdId_hi]                         ← 2 bytes
      [payload ...]                                ← len bytes
      [CRC16_lo][CRC16_hi]                         ← CRC of everything above
    """
    length = len(payload)
    header = bytes([0x7E, 1, 0, length & 0xFF, (length >> 8) & 0xFF])
    mid = bytes([_crc8(header), 0x00, 0x00, cmd_id & 0xFF, (cmd_id >> 8) & 0xFF])
    body = header + mid + payload
    crc = _crc16(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def parse_odm_packet(data: bytes) -> tuple[int, bytes] | None:
    """Parse an EcoOdmPacket, returning (cmd_id, payload) or None if malformed."""
    if len(data) < 12 or data[0] != 0x7E:
        return None
    length = data[3] | (data[4] << 8)
    if len(data) < 10 + length + 2:
        return None
    cmd_id = data[8] | (data[9] << 8)
    payload = data[10 : 10 + length]
    return cmd_id, payload


def odm_auth_key(user_id: str, sn: str) -> bytes:
    """
    Compute the BLE auth secret key sent in cmd 514/515.

    Formula (from q4.r / c0.V / BlankJ MD5 utils):
        secretKey = MD5(userId + sn).hexdigest().upper().encode('ascii')
    """
    digest = hashlib.md5((user_id + sn).encode()).hexdigest().upper()
    return digest.encode("ascii")


def ble_name_for_sn(sn: str) -> str:
    """
    Return the expected BLE advertisement name for a given device SN.

    Pattern observed from advertisement monitor:
      "EF-" + sn[0:4] + sn[-4:]
    e.g. "AC31ZEH4AG130052" → "EF-AC310052"
         "HJ37ZDH5ZG5W0109" → "EF-HJ370109"
    """
    return f"EF-{sn[:4]}{sn[-4:]}"


def _sn_matches_ble_name(sn: str, ble_name: str | None) -> bool:
    """Return True if the BLE name is consistent with the SN."""
    if not ble_name or not ble_name.startswith("EF-"):
        return False
    suffix = ble_name[3:]  # strip "EF-"
    # Primary check: name == sn[:4] + sn[-4:]
    if suffix == sn[:4] + sn[-4:]:
        return True
    # Fallback: name ends with last 4 chars of SN (covers edge cases)
    if len(sn) >= 4 and suffix.endswith(sn[-4:]):
        return True
    return False


def _auth_payload(secret_key: bytes) -> bytes:
    """Prepend [0x00] (non-installer flag) before the secret key bytes."""
    return b"\x00" + secret_key


def _network_payload(
    wifi_ssid: str,
    wifi_password: str,
    ocpp_url: str,
    backup_url: str,
) -> bytes:
    """
    Build the payload for CMD_SETTING_NETWORK (cmd 770).

    Format (n.b / n.V from APK):
        [1 byte len][wifi_ssid bytes]
        [1 byte len][wifi_password bytes]
        [1 byte len][ocpp_url bytes]
        [1 byte len][backup_url bytes]
    """

    def _field(s: str) -> bytes:
        b = s.encode("utf-8")
        return bytes([len(b) & 0xFF]) + b

    return _field(wifi_ssid) + _field(wifi_password) + _field(ocpp_url) + _field(backup_url)


async def async_find_charger_address(hass: HomeAssistant, sn: str) -> str | None:
    """
    Scan HA's Bluetooth registry for the PowerPulse charger matching *sn*.

    The charger advertises as "EF-" + sn[0:4] + sn[-4:], e.g. "EF-AC310052".
    Returns the BLE MAC address string, or None if not found.
    """
    try:
        from homeassistant.components.bluetooth import (  # noqa: PLC0415
            async_scanner_devices_by_address,
            async_discovered_service_info,
        )
    except ImportError:
        return None

    expected_name = ble_name_for_sn(sn)
    _LOGGER.debug("ble_ocpp: looking for BLE device named %s (sn=%s)", expected_name, sn)

    # Iterate all currently-visible BLE advertisements
    try:
        service_infos = async_discovered_service_info(hass, connectable=True)
    except Exception:  # noqa: BLE001
        service_infos = []

    best_address: str | None = None
    best_rssi: int = -200

    for info in service_infos:
        name = info.name or ""
        if _sn_matches_ble_name(sn, name):
            rssi = getattr(info, "rssi", -200) or -200
            _LOGGER.debug(
                "ble_ocpp: candidate %s name=%s rssi=%d", info.address, name, rssi
            )
            if best_address is None or rssi > best_rssi:
                best_address = info.address
                best_rssi = rssi

    if best_address:
        _LOGGER.info(
            "ble_ocpp: auto-detected charger %s at %s (rssi=%d)",
            expected_name,
            best_address,
            best_rssi,
        )
    else:
        _LOGGER.warning(
            "ble_ocpp: charger %s not found in BLE advertisements", expected_name
        )

    return best_address


async def async_ble_set_ocpp_url(
    hass: HomeAssistant,
    ble_address: str,
    user_id: str,
    sn: str,
    ocpp_url: str,
    backup_url: str,
    wifi_ssid: str = "",
    wifi_password: str = "",
    connect_timeout: float = 15.0,
    response_timeout: float = 8.0,
) -> dict:
    """
    Authenticate and push OCPP URL to a PowerPulse charger over BLE.

    The charger is identified by its BLE MAC address.  Home Assistant's
    Bluetooth integration (or an ESPHome Bluetooth proxy) must have the
    device in range.

    A per-address asyncio.Lock serialises concurrent calls so that two
    automations firing simultaneously queue rather than race for the BLE
    connection.

    Returns a dict with auth_response and network_response summaries.
    """
    try:
        from bleak import BleakClient, BleakError  # noqa: PLC0415
        from homeassistant.components.bluetooth import (  # noqa: PLC0415
            async_ble_device_from_address,
        )
    except ImportError as exc:
        msg = "bleak or homeassistant.components.bluetooth not available"
        raise RuntimeError(msg) from exc

    lock = _ble_lock(ble_address)
    if lock.locked():
        _LOGGER.info(
            "ble_ocpp: %s is already in use — queuing (another call is active)",
            ble_address,
        )

    async with lock:
        ble_device = async_ble_device_from_address(hass, ble_address, connectable=True)
        if ble_device is None:
            msg = f"BLE device {ble_address} not found — check ESPHome proxy and range"
            raise ValueError(msg)

        secret_key = odm_auth_key(user_id, sn)
        _LOGGER.debug(
            "ble_ocpp: connecting to %s, secretKey prefix=%s",
            ble_address,
            secret_key[:8].decode(),
        )

        recv_queue: asyncio.Queue[bytes] = asyncio.Queue()

        def _on_notify(_sender: int, data: bytearray) -> None:
            _LOGGER.debug("ble_ocpp: notify %d bytes: %s", len(data), data.hex())
            recv_queue.put_nowait(bytes(data))

        async def _wait_response(timeout: float) -> tuple[int, bytes] | None:
            """Drain notify queue, accumulate bytes, return first parseable packet."""
            deadline = asyncio.get_event_loop().time() + timeout
            buf = bytearray()
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                try:
                    chunk = await asyncio.wait_for(recv_queue.get(), timeout=remaining)
                    buf.extend(chunk)
                    parsed = parse_odm_packet(bytes(buf))
                    if parsed is not None:
                        return parsed
                except TimeoutError:
                    break
            return None

        try:
            async with BleakClient(ble_device, timeout=connect_timeout) as client:
                # ── Discover FFF0 service characteristics ─────────────────
                service = client.services.get_service(ECOFLOW_ODM_SERVICE)
                if service is None:
                    msg = f"FFF0 service not found on {ble_address}"
                    raise ValueError(msg)

                write_char = None
                notify_char = None
                for char in service.characteristics:
                    props = set(char.properties)
                    if write_char is None and (
                        "write" in props or "write-without-response" in props
                    ):
                        write_char = char
                    if notify_char is None and "notify" in props:
                        notify_char = char

                if write_char is None:
                    msg = f"No writable characteristic in FFF0 service on {ble_address}"
                    raise ValueError(msg)
                if notify_char is None:
                    msg = f"No notify characteristic in FFF0 service on {ble_address}"
                    raise ValueError(msg)

                _LOGGER.debug(
                    "ble_ocpp: write=%s notify=%s",
                    write_char.uuid,
                    notify_char.uuid,
                )

                await client.start_notify(notify_char.uuid, _on_notify)
                use_response = "write" in set(write_char.properties)

                # ── Step 1: AUTH_WRITE (cmd 514) ──────────────────────────
                auth_cmd = build_odm_packet(
                    CMD_AUTH_WRITE, _auth_payload(secret_key)
                )
                _LOGGER.debug(
                    "ble_ocpp: AUTH_WRITE cmd=%d hex=%s",
                    CMD_AUTH_WRITE,
                    auth_cmd.hex(),
                )
                await client.write_gatt_char(
                    write_char.uuid, auth_cmd, response=use_response
                )

                auth_result = await _wait_response(response_timeout)
                if auth_result is None:
                    _LOGGER.warning(
                        "ble_ocpp: no auth response within %.1fs — proceeding",
                        response_timeout,
                    )
                    auth_summary = "timeout"
                else:
                    auth_summary = (
                        f"cmd=0x{auth_result[0]:04X} payload={auth_result[1].hex()}"
                    )
                    _LOGGER.debug("ble_ocpp: AUTH response: %s", auth_summary)

                # ── Step 2: SETTING_NETWORK (cmd 770) ─────────────────────
                net_payload = _network_payload(
                    wifi_ssid, wifi_password, ocpp_url, backup_url
                )
                net_cmd = build_odm_packet(CMD_SETTING_NETWORK, net_payload)
                _LOGGER.debug(
                    "ble_ocpp: SETTING_NETWORK cmd=%d hex=%s",
                    CMD_SETTING_NETWORK,
                    net_cmd.hex(),
                )
                await client.write_gatt_char(
                    write_char.uuid, net_cmd, response=use_response
                )

                net_result = await _wait_response(response_timeout)
                if net_result is None:
                    net_summary = "timeout"
                    _LOGGER.warning(
                        "ble_ocpp: no network-config response within %.1fs",
                        response_timeout,
                    )
                else:
                    net_summary = (
                        f"cmd=0x{net_result[0]:04X} payload={net_result[1].hex()}"
                    )
                    _LOGGER.debug(
                        "ble_ocpp: SETTING_NETWORK response: %s", net_summary
                    )

                await client.stop_notify(notify_char.uuid)

        except BleakError as exc:
            msg = f"BLE error communicating with {ble_address}: {exc}"
            raise RuntimeError(msg) from exc

    return {
        "ble_address": ble_address,
        "ocpp_url_sent": ocpp_url,
        "backup_url_sent": backup_url,
        "auth_response": auth_summary,
        "network_response": net_summary,
    }
