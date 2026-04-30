"""
Async EcoFlow PowerOcean API client.

This module provides a standalone, asyncio-based client for communicating
with the EcoFlow cloud API. It supports:

- User authentication
- Automatic region detection (EU/US)
- Fetching raw device data
- Writing device parameters via the EcoFlow Open Platform API

The module is framework-independent and can be used both inside and
outside of Home Assistant.

Classes:
    EcoflowApi: Legacy cloud API client (read-only, email/password auth).
    EcoflowOpenApi: Open Platform API client (read/write, accessKey/secretKey auth).
    EcoflowApiError: Base exception.
    AuthenticationError: Raised on login failure.
    RegionDetectionError: Raised if API region cannot be detected.
    EcoflowOpenApiError: Raised on Open API errors.
"""

import asyncio
import base64
import hashlib
import hmac
import random
import time
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


class EcoflowOpenApiError(Exception):
    """Raised when the EcoFlow Open Platform API returns an error."""


class EcoflowOpenApi:
    """
    Async client for the EcoFlow Open Platform API (accessKey/secretKey).

    Supports read and write operations via HMAC-SHA256-signed requests:

    - ``set_quota``: Write device parameters (PUT).
    - ``get_all_quotas``: Read all device quotas (GET).

    Signing algorithm (per EcoFlow Open Platform spec):
      1. Flatten the request payload to sorted dot-notation key=value pairs.
      2. Append ``&accessKey=…&nonce=…&timestamp=…``.
      3. Sign the resulting string with HMAC-SHA256 (secretKey).
      4. Transmit ``accessKey``, ``nonce``, ``timestamp``, ``sign`` as headers.
    """

    BASE_URL = "https://api.ecoflow.com"

    def __init__(
        self,
        serialnumber: str,
        access_key: str,
        secret_key: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """
        Initialize the EcoFlow Open Platform API client.

        Args:
            serialnumber: Serial number of the device.
            access_key: EcoFlow Open Platform access key.
            secret_key: EcoFlow Open Platform secret key.
            session: Optional aiohttp.ClientSession for making requests.

        """
        self.sn = serialnumber
        self.access_key = access_key
        self.secret_key = secret_key
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

    @staticmethod
    def _flatten_params(obj: Any, prefix: str = "") -> dict[str, str]:
        """
        Flatten a nested dict/list into sorted dot-notation key-value pairs.

        Dicts use dot notation (``parent.child``); lists use bracket notation
        (``parent[0]``). Leaf values are coerced to strings.
        """
        result: dict[str, str] = {}
        if isinstance(obj, dict):
            for key, val in obj.items():
                full_key = f"{prefix}.{key}" if prefix else key
                result.update(EcoflowOpenApi._flatten_params(val, full_key))
        elif isinstance(obj, list):
            for i, val in enumerate(obj):
                full_key = f"{prefix}[{i}]"
                result.update(EcoflowOpenApi._flatten_params(val, full_key))
        else:
            result[prefix] = str(obj)
        return result

    def _build_sign_headers(self, flat_params: dict[str, str]) -> dict[str, str]:
        """
        Build HMAC-SHA256 signed request headers.

        Args:
            flat_params: Flattened key-value pairs from the request payload.

        Returns:
            Dict with ``accessKey``, ``nonce``, ``timestamp``, and ``sign``.

        """
        nonce = str(random.randint(10000, 999999))
        timestamp = str(int(time.time() * 1000))

        sorted_pairs = sorted(flat_params.items())
        param_str = "&".join(f"{k}={v}" for k, v in sorted_pairs)
        auth_str = f"accessKey={self.access_key}&nonce={nonce}&timestamp={timestamp}"
        sign_str = f"{param_str}&{auth_str}" if param_str else auth_str

        signature = hmac.new(
            self.secret_key.encode(),
            sign_str.encode(),
            hashlib.sha256,
        ).hexdigest()

        return {
            "accessKey": self.access_key,
            "nonce": nonce,
            "timestamp": timestamp,
            "sign": signature,
        }

    async def set_quota(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Write device parameters via PUT /iot-open/sign/device/quota.

        Args:
            params: Command parameters, e.g.
                ``{"cmdSet": 32, "id": 66, "enabled": 1}``.

        Returns:
            Parsed JSON response from the API.

        Raises:
            EcoflowOpenApiError: On non-2xx HTTP response.

        """
        session = await self._get_session()
        url = f"{self.BASE_URL}/iot-open/sign/device/quota"

        body: dict[str, Any] = {"sn": self.sn, "params": params}
        flat = self._flatten_params(body)
        headers = self._build_sign_headers(flat)
        headers["Content-Type"] = "application/json"

        try:
            async with asyncio.timeout(30):
                async with session.put(url, json=body, headers=headers) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except aiohttp.ClientResponseError as e:
            msg = f"Open API set_quota failed: {e.status} {e.message}"
            raise EcoflowOpenApiError(msg) from e

    async def get_quota(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Read specific device quota values via POST /iot-open/sign/device/quota.

        Args:
            params: Query parameters, e.g.
                ``{"cmdSet": 32, "id": 66, "quotas": ["inv.cfgAcEnabled"]}``.

        Returns:
            Parsed JSON response from the API.

        Raises:
            EcoflowOpenApiError: On non-2xx HTTP response.

        """
        session = await self._get_session()
        url = f"{self.BASE_URL}/iot-open/sign/device/quota"

        body: dict[str, Any] = {"sn": self.sn, "params": params}
        flat = self._flatten_params(body)
        headers = self._build_sign_headers(flat)
        headers["Content-Type"] = "application/json"

        try:
            async with asyncio.timeout(30):
                async with session.post(url, json=body, headers=headers) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except aiohttp.ClientResponseError as e:
            msg = f"Open API get_quota failed: {e.status} {e.message}"
            raise EcoflowOpenApiError(msg) from e

    async def list_devices(self) -> dict[str, Any]:
        """
        Retrieve the list of devices associated with the account.

        Returns:
            Parsed JSON response from the API.

        Raises:
            EcoflowOpenApiError: On non-2xx HTTP response.

        """
        session = await self._get_session()
        url = f"{self.BASE_URL}/iot-open/sign/device/list"
        headers = self._build_sign_headers({})

        try:
            async with asyncio.timeout(30):
                async with session.get(url, headers=headers) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except aiohttp.ClientResponseError as e:
            msg = f"Open API list_devices failed: {e.status} {e.message}"
            raise EcoflowOpenApiError(msg) from e

    async def get_mqtt_certification(self) -> dict[str, Any]:
        """
        Retrieve MQTT broker credentials for real-time device updates.

        Returns:
            Parsed JSON response containing MQTT host, port, and credentials.

        Raises:
            EcoflowOpenApiError: On non-2xx HTTP response.

        """
        session = await self._get_session()
        url = f"{self.BASE_URL}/iot-open/sign/certification"
        headers = self._build_sign_headers({})

        try:
            async with asyncio.timeout(30):
                async with session.get(url, headers=headers) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except aiohttp.ClientResponseError as e:
            msg = f"Open API get_mqtt_certification failed: {e.status} {e.message}"
            raise EcoflowOpenApiError(msg) from e

    async def get_all_quotas(self) -> dict[str, Any]:
        """
        Fetch all device quotas via GET /iot-open/sign/device/quota/all.

        Returns:
            Parsed JSON response from the API.

        Raises:
            EcoflowOpenApiError: On non-2xx HTTP response.

        """
        session = await self._get_session()

        query_params: dict[str, Any] = {"sn": self.sn}
        flat = self._flatten_params(query_params)
        headers = self._build_sign_headers(flat)

        query_string = "&".join(
            f"{k}={v}" for k, v in sorted(query_params.items())
        )
        url = f"{self.BASE_URL}/iot-open/sign/device/quota/all?{query_string}"

        try:
            async with asyncio.timeout(30):
                async with session.get(url, headers=headers) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except aiohttp.ClientResponseError as e:
            msg = f"Open API get_all_quotas failed: {e.status} {e.message}"
            raise EcoflowOpenApiError(msg) from e
