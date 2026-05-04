"""
Async EcoFlow PowerOcean API client.

This module provides a standalone, asyncio-based client for communicating
with the EcoFlow cloud API. It supports:

- User authentication
- Automatic region detection (EU/US)
- Fetching raw device data

The module is framework-independent and can be used both inside and
outside of Home Assistant.

Classes:
    EcoflowApi: Main API client class.
    EcoflowApiError: Base exception.
    AuthenticationError: Raised on login failure.
    RegionDetectionError: Raised if API region cannot be detected.
"""

import asyncio
import base64
from typing import Any, ClassVar

import aiohttp

from .const import LOGGER

HTTP_OK = 200


class EcoflowApiError(Exception):
    """Base exception for all EcoFlow API errors."""


class AuthenticationError(EcoflowApiError):
    """Raised when authentication with the EcoFlow API fails."""


class RegionDetectionError(EcoflowApiError):
    """Raised when automatic API region detection fails."""


class EcoflowApi:
    """
    Async client for the EcoFlow PowerOcean cloud API.

    This class handles:

    - Authentication against the EcoFlow cloud
    - Automatic region detection (EU / US endpoints)
    - Fetching raw device data

    The client can optionally reuse an externally provided
    aiohttp.ClientSession. If no session is provided, an internal
    session will be created automatically.

    This class is framework-agnostic and does not depend on
    Home Assistant.
    """

    REGION_HOSTS: ClassVar[dict[str, str]] = {
        "eu": "api-e.ecoflow.com",
        "us": "api-a.ecoflow.com",
    }

    def __init__(
        self,
        serialnumber: str,
        username: str,
        password: str,
        variant: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """
        Initialize the EcoFlow API client.

        Args:
            serialnumber: Serial number of the PowerOcean device.
            username: EcoFlow account username (email).
            password: EcoFlow account password.
            variant: PowerOcean device variant / model ID.
            session: Optional aiohttp.ClientSession for making requests.

        """
        self.sn = serialnumber
        self.username = username
        self.password = password
        self.variant = variant

        self.token: str | None = None
        self.api_host: str | None = None
        self.url_authorize = "https://api.ecoflow.com/auth/login"

        self._external_session = session
        self._session: aiohttp.ClientSession | None = session

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return an existing session or create a new aiohttp session."""
        if self._session:
            return self._session
        self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close internally created aiohttp session."""
        if self._session and not self._external_session:
            await self._session.close()

    async def async_authorize(self) -> None:
        """Authorize user and retrieve authentication token."""
        session = await self._get_session()

        headers = {"lang": "en_US", "content-type": "application/json"}
        data = {
            "email": self.username,
            "password": base64.b64encode(self.password.encode()).decode(),
            "scene": "IOT_APP",
            "userType": "ECOFLOW",
        }

        try:
            async with asyncio.timeout(10):
                async with session.post(
                    self.url_authorize, json=data, headers=headers
                ) as resp:
                    resp.raise_for_status()
                    response_data = await resp.json()
        except Exception as e:
            msg = "Login failed"
            raise AuthenticationError(msg) from e

        token = response_data.get("data", {}).get("token")
        if not token:
            msg = "Missing token in response"
            raise AuthenticationError(msg)

        self.token = token
        await self._detect_region()

    async def _detect_region(self) -> None:
        """Detect API region (EU or US) by probing known endpoints."""
        session = await self._get_session()

        for host in self.REGION_HOSTS.values():
            url = f"https://{host}/provider-service/user/device/detail?sn={self.sn}"

            headers = {
                "authorization": f"Bearer {self.token}",
                "product-type": self.variant,
            }

            try:
                async with asyncio.timeout(10):
                    async with session.get(url, headers=headers) as resp:
                        if resp.status == HTTP_OK:
                            self.api_host = host
                            return
            except (TimeoutError, aiohttp.ClientError) as err:
                LOGGER.debug("Region (%s) failed during detection: %s", host, err)
                continue  # Nur bekannte Netzwerk-/Timeout-Fehler abfangen

        msg = "Could not detect region"
        raise RegionDetectionError(msg)

    async def fetch_raw(self) -> dict[str, Any]:
        """Fetch data from Url (Async version)."""
        if not self.api_host:
            msg = "Region not detected"
            raise EcoflowApiError(msg)

        session = await self._get_session()

        url = (
            f"https://{self.api_host}/provider-service/user/device/detail?sn={self.sn}"
        )

        headers = {
            "authorization": f"Bearer {self.token}",
            "product-type": self.variant,
        }

        async with asyncio.timeout(30):
            async with session.get(url, headers=headers) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def async_authorize_only(self) -> None:
        """
        Authenticate without region detection.

        Use this when the serial number is not yet known (e.g. before device
        auto-detection).  Sets ``self.token`` but does NOT set ``self.api_host``.

        Raises:
            AuthenticationError: On invalid credentials or missing token.

        """
        session = await self._get_session()
        headers = {"lang": "en_US", "content-type": "application/json"}
        data = {
            "email": self.username,
            "password": base64.b64encode(self.password.encode()).decode(),
            "scene": "IOT_APP",
            "userType": "ECOFLOW",
        }
        try:
            async with asyncio.timeout(10):
                async with session.post(
                    self.url_authorize, json=data, headers=headers
                ) as resp:
                    resp.raise_for_status()
                    response_data = await resp.json()
        except Exception as e:
            msg = "Login failed"
            raise AuthenticationError(msg) from e

        token = response_data.get("data", {}).get("token")
        if not token:
            msg = "Missing token in response"
            raise AuthenticationError(msg)

        self.token = token

    async def async_list_devices(self) -> list[dict[str, Any]]:
        """
        List all PowerOcean devices linked to the authenticated account.

        Probes EU then US regions using the device-list endpoint, sets
        ``self.api_host`` for the winning region, and returns a filtered list
        of PowerOcean devices.

        Returns:
            List of dicts with keys ``sn``, ``product_type``, and ``name``.
            Returns an empty list if the endpoint is unreachable or no matching
            devices are found.

        Raises:
            EcoflowApiError: If ``async_authorize_only`` has not been called.

        """
        if not self.token:
            msg = "Not authenticated; call async_authorize_only() first"
            raise EcoflowApiError(msg)

        session = await self._get_session()
        for host in self.REGION_HOSTS.values():
            url = f"https://{host}/provider-service/user/device/list"
            headers = {"authorization": f"Bearer {self.token}"}
            try:
                async with asyncio.timeout(10):
                    async with session.get(url, headers=headers) as resp:
                        if resp.status == HTTP_OK:
                            self.api_host = host
                            payload = await resp.json()
                            return self._parse_device_list(payload)
            except (TimeoutError, aiohttp.ClientError) as err:
                LOGGER.debug("Device list on %s failed: %s", host, err)

        return []

    def _parse_device_list(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Normalise the device-list API response into a flat list.

        Handles both ``{"data": [...]}`` and ``{"data": {"devices": [...]}}``
        response shapes, and filters to known PowerOcean product-type codes.

        """
        powerocean_types = {"83", "85", "86", "87"}
        data = response.get("data", [])
        if isinstance(data, dict):
            data = data.get("devices", data.get("list", []))
        if not isinstance(data, list):
            return []

        result: list[dict[str, Any]] = []
        for device in data:
            if not isinstance(device, dict):
                continue
            sn = device.get("sn", "")
            pt = str(device.get("productType", device.get("product_type", "")))
            if sn and pt in powerocean_types:
                name = device.get("deviceName", device.get("name", sn))
                result.append({"sn": sn, "product_type": pt, "name": name})
        return result

    async def async_ocpp_list_backends(self) -> list[dict[str, Any]]:
        """List OCPP platform-config records on the EcoFlow account.

        GET /provider-service/app/ocppPlatformConfig/list
        Returns the catalog the EcoFlow app shows under "OCPP backend"; each
        record matches CPOcppPlatformBean.
        """
        if not self.api_host:
            msg = "Region not detected; cannot list OCPP backends"
            raise EcoflowApiError(msg)

        session = await self._get_session()
        url = f"https://{self.api_host}/provider-service/app/ocppPlatformConfig/list"
        headers = {"authorization": f"Bearer {self.token}"}

        async with asyncio.timeout(10):
            async with session.get(url, headers=headers) as resp:
                resp.raise_for_status()
                payload = await resp.json()

        data = payload.get("data", [])
        return data if isinstance(data, list) else []

    async def async_ocpp_post_backend(
        self, body: dict[str, Any]
    ) -> dict[str, Any]:
        """POST a CPOcppBindReq record to the EcoFlow account catalog.

        POST /provider-service/app/ocppPlatformConfig
        Body shape: CPOcppBindReq. Set isEnabled=0 to deactivate an
        existing backend (no DELETE exists).

        NOTE: this updates the EcoFlow account catalog only. The actual
        runtime handover to the new central system requires an additional
        proto write (vendorInfoSet) which is not yet implemented.
        """
        if not self.api_host:
            msg = "Region not detected; cannot write OCPP backend"
            raise EcoflowApiError(msg)

        session = await self._get_session()
        url = f"https://{self.api_host}/provider-service/app/ocppPlatformConfig"
        headers = {
            "authorization": f"Bearer {self.token}",
            "content-type": "application/json",
        }

        async with asyncio.timeout(10):
            async with session.post(url, json=body, headers=headers) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def async_get_property(
        self,
        sn: str | None = None,
        params: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Read device properties via the EcoFlow consumer API.

        Tries POST /iot-devices/device/getDeviceProperty first (the read
        companion to setDeviceProperty). On non-2xx, falls back to GET
        /iot-devices/device/acquireQuotaAll, which dumps the full quota
        map for a serial number.

        Args:
            sn: Target device serial. Defaults to ``self.sn`` (the
                inverter); pass the PowerPulse SN explicitly to read its
                properties.
            params: Optional list of camelCase keys to filter on. None or
                an empty list requests the full set.

        Returns:
            The decoded JSON response. Shape is endpoint-dependent and
            intentionally not normalised — callers inspect it directly.

        """
        if not self.api_host:
            msg = "Region not detected; cannot read property"
            raise EcoflowApiError(msg)

        target_sn = sn or self.sn
        session = await self._get_session()
        headers = {
            "authorization": f"Bearer {self.token}",
            "product-type": self.variant,
            "content-type": "application/json",
        }

        post_url = f"https://{self.api_host}/iot-devices/device/getDeviceProperty"
        payload: dict[str, Any] = {"sn": target_sn, "params": params or []}
        try:
            async with asyncio.timeout(10):
                async with session.post(
                    post_url, json=payload, headers=headers
                ) as resp:
                    if resp.status == HTTP_OK:
                        return await resp.json()
                    LOGGER.debug(
                        "getDeviceProperty %s returned %s; trying acquireQuotaAll",
                        target_sn,
                        resp.status,
                    )
        except (TimeoutError, aiohttp.ClientError) as err:
            LOGGER.debug("getDeviceProperty %s failed: %s", target_sn, err)

        get_url = (
            f"https://{self.api_host}/iot-devices/device/acquireQuotaAll"
            f"?sn={target_sn}"
        )
        try:
            async with asyncio.timeout(10):
                async with session.get(get_url, headers=headers) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except (TimeoutError, aiohttp.ClientError) as err:
            msg = f"acquireQuotaAll for {target_sn} failed: {err}"
            raise EcoflowApiError(msg) from err

    async def async_set_property(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Write a device property via the EcoFlow consumer API.

        Endpoint: /iot-devices/device/setDeviceProperty.
        Auth: bearer token from async_authorize().
        Payload: {"sn": <device_sn>, "params": {<camelCase_field>: <value>}}

        Raises:
            EcoflowApiError: If the region has not been detected yet.
            aiohttp.ClientResponseError: If the API returns a non-2xx status.

        """
        if not self.api_host:
            msg = "Region not detected; cannot write property"
            raise EcoflowApiError(msg)

        session = await self._get_session()
        url = f"https://{self.api_host}/iot-devices/device/setDeviceProperty"
        headers = {
            "authorization": f"Bearer {self.token}",
            "product-type": self.variant,
            "content-type": "application/json",
        }
        payload: dict[str, Any] = {"sn": self.sn, "params": params}

        async with asyncio.timeout(10):
            async with session.post(url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def async_set_property_for(
        self, sn: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Like async_set_property but targets an explicit SN (e.g. PowerPulse)."""
        if not self.api_host:
            msg = "Region not detected; cannot write property"
            raise EcoflowApiError(msg)

        session = await self._get_session()
        url = f"https://{self.api_host}/iot-devices/device/setDeviceProperty"
        headers = {
            "authorization": f"Bearer {self.token}",
            "product-type": self.variant,
            "content-type": "application/json",
        }
        payload: dict[str, Any] = {"sn": sn, "params": params}
        try:
            async with asyncio.timeout(10):
                async with session.post(url, json=payload, headers=headers) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except (TimeoutError, aiohttp.ClientError) as err:
            msg = f"setDeviceProperty for {sn} failed: {err}"
            raise EcoflowApiError(msg) from err

    async def async_ocpp_get_domain(self, sn: str) -> dict[str, Any]:
        """GET /iot-service/ac305/charge/ocpp/domain — current runtime OCPP URL on the charger.

        Returns OcppUrlDomain: {websocketDomain: str, websocketDomainBackup: str}
        APK source: o9/b.java:629 → o9/b.java::U()
        """
        if not self.api_host:
            msg = "Region not detected; cannot read OCPP domain"
            raise EcoflowApiError(msg)

        session = await self._get_session()
        url = f"https://{self.api_host}/iot-service/ac305/charge/ocpp/domain"
        headers = {"authorization": f"Bearer {self.token}"}
        try:
            async with asyncio.timeout(10):
                async with session.get(url, params={"sn": sn}, headers=headers) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except (TimeoutError, aiohttp.ClientError) as err:
            msg = f"ocpp/domain for {sn} failed: {err}"
            raise EcoflowApiError(msg) from err

    async def async_ocpp_set_domain(
        self,
        sn: str,
        websocket_domain: str,
        websocket_domain_backup: str,
    ) -> dict[str, Any]:
        """POST /iot-service/ac305/charge/ocpp/domain — set the runtime OCPP URL.

        Mirror of the GET /domain read. Sends the same OcppUrlDomain shape back
        as a POST to redirect the charger to a custom central system.
        """
        if not self.api_host:
            msg = "Region not detected; cannot set OCPP domain"
            raise EcoflowApiError(msg)

        session = await self._get_session()
        url = f"https://{self.api_host}/iot-service/ac305/charge/ocpp/domain"
        headers = {
            "authorization": f"Bearer {self.token}",
            "content-type": "application/json",
        }
        body = {
            "sn": sn,
            "websocketDomain": websocket_domain,
            "websocketDomainBackup": websocket_domain_backup,
        }
        try:
            async with asyncio.timeout(10):
                async with session.post(url, json=body, headers=headers) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except (TimeoutError, aiohttp.ClientError) as err:
            msg = f"ocpp/domain POST for {sn} failed: {err}"
            raise EcoflowApiError(msg) from err

    async def async_ocpp_vendor_info_set(
        self,
        sn: str,
        device_id: str,
        url: str,
        vendor: str,
        cpo_name: str,
        profile: int,
        auth_key: str,
    ) -> dict[str, Any]:
        """Send vendorInfoSet (VENDOR_INFO_SET / CmdID 0xA1) to the PowerPulse charger.

        This is the runtime handover that actually redirects the charger to a new
        OCPP central system. It is distinct from the catalog write
        (POST /provider-service/app/ocppPlatformConfig) which is account-level only.

        The command is sent via setDeviceProperty with the charger SN. If the
        REST gateway rejects the charger SN the caller should retry with the
        inverter SN — the inverter may proxy sub-device commands.

        APK source: com/ecoflow/cp307module/util/o.java:916 → method X()
        Proto: Cp307Ocpp.vendorInfoSet {device_id, url, vendor, cpo_name, profile, auth_key}
        CmdID: 0xA1 (VENDOR_INFO_SET), module=53, cmd_set=224
        """
        if not self.api_host:
            msg = "Region not detected; cannot send vendorInfoSet"
            raise EcoflowApiError(msg)

        session = await self._get_session()
        endpoint = f"https://{self.api_host}/iot-devices/device/setDeviceProperty"
        headers = {
            "authorization": f"Bearer {self.token}",
            "product-type": self.variant,
            "content-type": "application/json",
        }
        # setDeviceProperty requires a top-level "propertyNames" list — code 1006
        # ("propertyNames 不能为空") is returned when it is absent or empty.
        # Try flat field names first (what the REST gateway likely expects for
        # a proto with named fields). The nested "vendorInfoSet" key is also
        # included in case the gateway routes by message name.
        params: dict[str, Any] = {
            "vendorInfoSet": {
                "deviceId": device_id,
                "url": url,
                "vendor": vendor,
                "cpoName": cpo_name,
                "profile": profile,
                "authKey": auth_key,
            }
        }
        payload: dict[str, Any] = {
            "sn": sn,
            "propertyNames": list(params.keys()),
            "params": params,
        }
        try:
            async with asyncio.timeout(10):
                async with session.post(
                    endpoint, json=payload, headers=headers
                ) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except (TimeoutError, aiohttp.ClientError) as err:
            msg = f"vendorInfoSet for {sn} failed: {err}"
            raise EcoflowApiError(msg) from err

    async def async_ocpp_vendor_info_clr(self, sn: str) -> dict[str, Any]:
        """Send vendorInfoClr (VENDOR_INFO_CLR / CmdID 0xA3) — revert charger to EcoFlow cloud.

        APK source: VENDOR_INFO_CLR cmd in cp307_ocpp.proto. No factory reset needed.
        """
        if not self.api_host:
            msg = "Region not detected; cannot send vendorInfoClr"
            raise EcoflowApiError(msg)

        session = await self._get_session()
        endpoint = f"https://{self.api_host}/iot-devices/device/setDeviceProperty"
        headers = {
            "authorization": f"Bearer {self.token}",
            "product-type": self.variant,
            "content-type": "application/json",
        }
        payload: dict[str, Any] = {
            "sn": sn,
            "propertyNames": ["vendorInfoClr"],
            "params": {"vendorInfoClr": {}},
        }
        try:
            async with asyncio.timeout(10):
                async with session.post(
                    endpoint, json=payload, headers=headers
                ) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except (TimeoutError, aiohttp.ClientError) as err:
            msg = f"vendorInfoClr for {sn} failed: {err}"
            raise EcoflowApiError(msg) from err
