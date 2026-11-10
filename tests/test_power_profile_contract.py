"""Public profile transport preserves payloads and never retries mutations.

Synthetic payloads cover observed portal fields without claiming live support
for creation, deletion or firmware-specific settings.
"""

from __future__ import annotations

import re
from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import ClientConnectionError, ClientSession
from aioresponses import aioresponses

from custom_components.v2c_cloud.local_api import (
    V2CLocalApiError,
    async_write_keyword,
)
from custom_components.v2c_cloud.v2c_cloud import V2CClient, V2CRequestError

BASE_URL = "https://v2c.cloud/kong/v2c_service"
DEVICE_ID = "test-device"
UPDATED_AT = "2026-11-08T12:00:00Z"


@pytest.fixture
def profile():
    return {
        "powers": [
            {
                "type": 0,
                "tram": [
                    {
                        "hourStart": 0,
                        "hourEnd": 12,
                        "charge_fv_mode": 0,
                        "power": 46,
                        "bat_mode": 1,
                        "intensity": {"l1": 16, "l2": 20, "l3": 24},
                    },
                    {
                        "hourStart": 12,
                        "hourEnd": 24,
                        "charge_fv_mode": 4,
                        "power": 5,
                    },
                ],
            },
            {
                "type": 1,
                "tram": [
                    {
                        "hourStart": 0,
                        "hourEnd": 24,
                        "charge_fv_mode": 2,
                        "power": 69,
                        "bat_mode": 0,
                    }
                ],
            },
        ],
        # Intentionally synthetic: unknown fields must survive opaque transport.
        "__test_extension__": {"nested": [False, None, {"text": "unchanged"}]},
    }


@pytest.fixture
async def client():
    async with ClientSession() as session:
        yield V2CClient(session, "test-api-key")


async def test_profile_save_preserves_complete_payload(client, profile):
    path = "/device/savepersonalicepower/v2"
    original = deepcopy(profile)
    with aioresponses() as http:
        http.post(re.compile(re.escape(BASE_URL + path) + r"\?.*"), payload={})
        await client.async_save_personal_power_profile(
            DEVICE_ID, "Solar", UPDATED_AT, profile
        )

        assert len(http.requests) == 1
        (method, _url), calls = next(iter(http.requests.items()))
        assert method == "POST"
        assert len(calls) == 1
        assert calls[0].kwargs["params"] == {
            "deviceId": DEVICE_ID,
            "name": "Solar",
            "updateAt": UPDATED_AT,
        }
        assert calls[0].kwargs["json"] == original
    assert profile == original


async def test_profile_update_keeps_signature_and_payload_but_uses_save_endpoint(
    client, profile
):
    original = deepcopy(profile)
    with aioresponses() as http:
        http.post(
            re.compile(
                re.escape(BASE_URL + "/device/savepersonalicepower/v2") + r"\?.*"
            ),
            payload={"ok": True},
        )
        result = await client.async_update_personal_power_profile(
            DEVICE_ID, "Solar", UPDATED_AT, profile
        )
        assert len(http.requests) == 1
        (method, _url), calls = next(iter(http.requests.items()))
        assert method == "POST"
        assert calls[0].kwargs["params"] == {
            "deviceId": DEVICE_ID,
            "name": "Solar",
            "updateAt": UPDATED_AT,
        }
        assert calls[0].kwargs["json"] == original
    assert result == {"ok": True}
    assert profile == original


@pytest.mark.parametrize("list_all", [False, True])
async def test_profile_reads_preserve_payload_without_writing(
    client, profile, list_all
):
    path = "/device/personalicepower/all" if list_all else "/device/personalicepower/v2"
    payload = [profile] if list_all else profile
    with aioresponses() as http:
        http.get(re.compile(re.escape(BASE_URL + path) + r"\?.*"), payload=payload)
        if list_all:
            result = await client.async_list_personal_power_profiles(DEVICE_ID)
        else:
            result = await client.async_get_personal_power_profile(
                DEVICE_ID, UPDATED_AT
            )

        assert result == payload
        assert len(http.requests) == 1
        (method, _url), calls = next(iter(http.requests.items()))
        assert method == "GET"
        assert len(calls) == 1


async def test_missing_profile_does_not_create_or_activate_one(client):
    with aioresponses() as http:
        http.get(
            re.compile(re.escape(BASE_URL + "/device/personalicepower/v2") + r"\?.*"),
            status=404,
        )
        with pytest.raises(V2CRequestError) as error:
            await client.async_get_personal_power_profile(DEVICE_ID, UPDATED_AT)
        assert error.value.status == 404
        assert len(http.requests) == 1
        assert next(iter(http.requests))[0] == "GET"


async def test_battery_telemetry_cannot_be_used_as_a_local_control():
    with (
        patch(
            "custom_components.v2c_cloud.local_api.resolve_static_ip",
            return_value="192.168.1.100",
        ),
        patch(
            "custom_components.v2c_cloud.local_api.async_get_clientsession"
        ) as session,
        pytest.raises(V2CLocalApiError, match="unknown keyword"),
    ):
        await async_write_keyword(
            MagicMock(), MagicMock(), DEVICE_ID, "BatteryPower", 500
        )
    session.assert_not_called()


PROFILE_MUTATIONS = [
    ("async_save_personal_power_profile", "/device/savepersonalicepower/v2", "post"),
    ("async_update_personal_power_profile", "/device/savepersonalicepower/v2", "post"),
    ("async_activate_personal_power_profile", "/device/personalicepower/v2", "post"),
    ("async_delete_personal_power_profile", "/device/personalicepower/v2", "delete"),
]


async def _mutate(client, method_name, profile):
    method = getattr(client, method_name)
    if method_name == "async_delete_personal_power_profile":
        return await method(DEVICE_ID, "Solar", UPDATED_AT)
    return await method(DEVICE_ID, "Solar", "1794220000000", profile)


@pytest.mark.parametrize("error", [TimeoutError(), ClientConnectionError("lost")])
@pytest.mark.parametrize(("method_name", "path", "verb"), PROFILE_MUTATIONS)
async def test_profile_mutation_does_not_retry_uncertain_response(
    client, profile, *, error, method_name, path, verb
):
    with aioresponses() as http:
        getattr(http, verb)(
            re.compile(re.escape(BASE_URL + path) + r"\?.*"),
            exception=error,
        )
        with pytest.raises(V2CRequestError):
            await _mutate(client, method_name, profile)
        assert sum(len(calls) for calls in http.requests.values()) == 1


@pytest.mark.parametrize(("method_name", "path", "verb"), PROFILE_MUTATIONS)
async def test_profile_mutation_cannot_follow_a_redirect(
    client, profile, method_name, path, verb
):
    with aioresponses() as http:
        getattr(http, verb)(
            re.compile(re.escape(BASE_URL + path) + r"\?.*"),
            status=307,
            headers={"Location": "https://example.com/another-api"},
        )
        with pytest.raises(V2CRequestError) as error:
            await _mutate(client, method_name, profile)
        assert error.value.status == 307
        assert len(http.requests) == 1
        calls = next(iter(http.requests.values()))
        assert calls[0].kwargs["allow_redirects"] is False
