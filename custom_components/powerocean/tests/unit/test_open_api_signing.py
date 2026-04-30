"""Unit tests for EcoflowOpenApi HMAC-SHA256 signing and param flattening."""

import hashlib
import hmac
from unittest.mock import patch

import pytest

from custom_components.powerocean.api import EcoflowOpenApi


# ---------------------------------------------------------------------------
# _flatten_params
# ---------------------------------------------------------------------------


def test_flatten_flat_dict():
    result = EcoflowOpenApi._flatten_params({"sn": "ABC123"})
    assert result == {"sn": "ABC123"}


def test_flatten_nested_dict():
    result = EcoflowOpenApi._flatten_params({"params": {"cmdSet": 32, "id": 66}})
    assert result == {"params.cmdSet": "32", "params.id": "66"}


def test_flatten_list():
    result = EcoflowOpenApi._flatten_params({"items": [1, 2]})
    assert result == {"items[0]": "1", "items[1]": "2"}


def test_flatten_deeply_nested():
    obj = {"sn": "XYZ", "params": {"cmdSet": 32, "quotas": ["inv.cfgAcEnabled"]}}
    result = EcoflowOpenApi._flatten_params(obj)
    assert result == {
        "sn": "XYZ",
        "params.cmdSet": "32",
        "params.quotas[0]": "inv.cfgAcEnabled",
    }


def test_flatten_empty_prefix():
    result = EcoflowOpenApi._flatten_params({"a": "1"}, prefix="")
    assert result == {"a": "1"}


def test_flatten_with_prefix():
    result = EcoflowOpenApi._flatten_params({"b": "2"}, prefix="root")
    assert result == {"root.b": "2"}


# ---------------------------------------------------------------------------
# _build_sign_headers — deterministic with mocked random/time
# ---------------------------------------------------------------------------


@pytest.fixture
def open_api():
    return EcoflowOpenApi(
        serialnumber="TESTSERIAL",
        access_key="my_access_key",
        secret_key="my_secret_key",
    )


def _expected_signature(params: dict, access_key: str, secret_key: str, nonce: str, timestamp: str) -> str:
    """Reproduce the signing algorithm for comparison."""
    sorted_pairs = sorted(params.items())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_pairs)
    auth_str = f"accessKey={access_key}&nonce={nonce}&timestamp={timestamp}"
    sign_str = f"{param_str}&{auth_str}" if param_str else auth_str
    return hmac.new(
        secret_key.encode(),
        sign_str.encode(),
        hashlib.sha256,
    ).hexdigest()


@patch("custom_components.powerocean.api.time.time", return_value=1700000000.0)
@patch("custom_components.powerocean.api.random.randint", return_value=123456)
def test_sign_headers_with_params(mock_rand, mock_time, open_api):
    flat = {"sn": "TESTSERIAL", "params.cmdSet": "32"}
    headers = open_api._build_sign_headers(flat)

    assert headers["accessKey"] == "my_access_key"
    assert headers["nonce"] == "123456"
    assert headers["timestamp"] == "1700000000000"

    expected_sig = _expected_signature(
        flat, "my_access_key", "my_secret_key", "123456", "1700000000000"
    )
    assert headers["sign"] == expected_sig
    assert headers["sign"] == headers["sign"].lower()  # signature must be lowercase hex


@patch("custom_components.powerocean.api.time.time", return_value=1700000000.0)
@patch("custom_components.powerocean.api.random.randint", return_value=99999)
def test_sign_headers_no_params(mock_rand, mock_time, open_api):
    """When there are no payload params, sign string starts with accessKey (no leading &)."""
    headers = open_api._build_sign_headers({})

    sign_str = (
        f"accessKey=my_access_key&nonce=99999&timestamp=1700000000000"
    )
    expected_sig = hmac.new(
        b"my_secret_key",
        sign_str.encode(),
        hashlib.sha256,
    ).hexdigest()

    assert headers["sign"] == expected_sig


@patch("custom_components.powerocean.api.time.time", return_value=1700000000.0)
@patch("custom_components.powerocean.api.random.randint", return_value=500000)
def test_sign_headers_sorted_alphabetically(mock_rand, mock_time, open_api):
    """Params must be sorted alphabetically before signing."""
    flat = {"z_param": "last", "a_param": "first", "m_param": "middle"}
    headers = open_api._build_sign_headers(flat)

    # Build the expected sign string with alphabetical order
    sign_str = (
        "a_param=first&m_param=middle&z_param=last"
        "&accessKey=my_access_key&nonce=500000&timestamp=1700000000000"
    )
    expected_sig = hmac.new(
        b"my_secret_key",
        sign_str.encode(),
        hashlib.sha256,
    ).hexdigest()

    assert headers["sign"] == expected_sig
