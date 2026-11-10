"""Regression coverage for saving profile edits without activation."""

from __future__ import annotations

import re
from copy import deepcopy

import pytest
from aiohttp import ClientSession
from aioresponses import aioresponses

from custom_components.v2c_cloud.v2c_cloud import V2CClient

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
