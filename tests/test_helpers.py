"""Tests for pure helper functions in v2c_cloud.py."""

from __future__ import annotations

import pytest

from custom_components.v2c_cloud.v2c_cloud import (
    V2CDeviceState,
    _coerce_scalar,
    _extract_static_ip,
    _normalize_bool,
)


class TestNormalizeBool:
    """Tests for _normalize_bool."""

    @pytest.mark.parametrize(
        "value",
        [True, 1, 1.0, "true", "True", "TRUE", "1", "yes", "on", "online"],
    )
    def test_truthy_values(self, value):
        assert _normalize_bool(value) is True

    @pytest.mark.parametrize(
        "value",
        [False, 0, 0.0, "false", "False", "FALSE", "0", "no", "off", "offline"],
    )
    def test_falsy_values(self, value):
        assert _normalize_bool(value) is False

    @pytest.mark.parametrize(
        "value",
        [None, "unknown", "maybe", "2", "yes please", [], {}],
    )
    def test_unknown_values_return_none(self, value):
        assert _normalize_bool(value) is None

    def test_strips_whitespace_from_strings(self):
        assert _normalize_bool("  true  ") is True
        assert _normalize_bool("  off  ") is False

    def test_bool_true_not_confused_with_int(self):
        result = _normalize_bool(True)
        assert result is True
        assert isinstance(result, bool)

    def test_bool_false_not_confused_with_int(self):
        result = _normalize_bool(False)
        assert result is False
        assert isinstance(result, bool)


class TestCoerceScalar:
    """Tests for _coerce_scalar."""

    def test_empty_string_returns_none(self):
        assert _coerce_scalar("") is None

    def test_whitespace_only_returns_none(self):
        assert _coerce_scalar("   ") is None

    def test_integer_string(self):
        result = _coerce_scalar("42")
        assert result == 42
        assert isinstance(result, int)

    def test_negative_integer(self):
        assert _coerce_scalar("-5") == -5

    def test_zero(self):
        assert _coerce_scalar("0") == 0

    def test_float_string(self):
        result = _coerce_scalar("3.14")
        assert result == pytest.approx(3.14)
        assert isinstance(result, float)

    def test_true_string(self):
        assert _coerce_scalar("true") is True

    def test_false_string(self):
        assert _coerce_scalar("false") is False

    def test_json_object(self):
        result = _coerce_scalar('{"key": "value", "num": 1}')
        assert result == {"key": "value", "num": 1}

    def test_json_array(self):
        result = _coerce_scalar("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_invalid_json_object_returns_string(self):
        result = _coerce_scalar("{not valid json}")
        assert result == "{not valid json}"

    def test_plain_string(self):
        assert _coerce_scalar("hello") == "hello"

    def test_mixed_case_bool_is_coerced(self):
        # _coerce_scalar lowercases before matching, so "True"/"False" also become bool
        assert _coerce_scalar("True") is True
        assert _coerce_scalar("False") is False


class TestExtractStaticIp:
    """Tests for _extract_static_ip."""

    def test_direct_ip_string(self):
        assert _extract_static_ip("192.168.1.100") == "192.168.1.100"

    def test_dict_with_static_ip_key(self):
        assert _extract_static_ip({"static_ip": "10.0.0.1"}) == "10.0.0.1"

    def test_dict_with_ip_key(self):
        assert _extract_static_ip({"ip": "172.16.0.5"}) == "172.16.0.5"

    def test_dict_with_address_key(self):
        assert _extract_static_ip({"address": "192.168.0.1"}) == "192.168.0.1"

    def test_json_encoded_string_with_ip(self):
        assert _extract_static_ip('{"ip": "192.168.1.200"}') == "192.168.1.200"

    def test_json_encoded_string_with_static_ip(self):
        assert _extract_static_ip('{"static_ip": "10.10.10.1"}') == "10.10.10.1"

    def test_invalid_ip_string_returns_none(self):
        assert _extract_static_ip("not-an-ip") is None

    def test_none_returns_none(self):
        assert _extract_static_ip(None) is None

    def test_empty_string_returns_none(self):
        assert _extract_static_ip("") is None

    def test_multiple_args_returns_first_valid(self):
        result = _extract_static_ip(None, "192.168.1.1", "10.0.0.1")
        assert result == "192.168.1.1"

    def test_skips_none_to_find_valid(self):
        result = _extract_static_ip(None, None, "10.0.0.1")
        assert result == "10.0.0.1"

    def test_all_invalid_returns_none(self):
        assert _extract_static_ip(None, "", "not-valid") is None

    def test_dict_with_no_ip_keys_returns_none(self):
        assert _extract_static_ip({"foo": "bar", "baz": 1}) is None

    def test_no_args_returns_none(self):
        assert _extract_static_ip() is None

    def test_nested_dict_with_ip(self):
        # wifi_info or similar nested payloads
        assert _extract_static_ip({"static_ip": {"ip": "192.168.50.1"}}) == "192.168.50.1"


class TestV2CDeviceState:
    """Tests for V2CDeviceState dataclass."""

    def test_as_dict_contains_all_keys(self):
        state = V2CDeviceState(
            device_id="dev-1",
            pairing={"deviceId": "dev-1"},
            connected=True,
            current_state={"ChargeState": 2},
            reported={"ChargeState": 2},
            version="1.2.3",
        )
        d = state.as_dict()
        assert d["device_id"] == "dev-1"
        assert d["connected"] is True
        assert d["version"] == "1.2.3"
        assert d["pairing"] == {"deviceId": "dev-1"}
        assert d["reported"] == {"ChargeState": 2}
        assert d["current_state"] == {"ChargeState": 2}

    def test_defaults_are_none(self):
        state = V2CDeviceState(device_id="dev-1", pairing={})
        d = state.as_dict()
        assert d["connected"] is None
        assert d["current_state"] is None
        assert d["rfid_cards"] is None
        assert d["version"] is None
        assert d["reported"] is None
        assert d["reported_raw"] is None

    def test_additional_defaults_to_empty_dict(self):
        state = V2CDeviceState(device_id="dev-1", pairing={})
        assert state.additional == {}
        assert state.as_dict()["additional"] == {}

    def test_rfid_cards_can_be_list(self):
        cards = [{"code": "abc123", "tag": "My Card"}]
        state = V2CDeviceState(device_id="dev-1", pairing={}, rfid_cards=cards)
        assert state.as_dict()["rfid_cards"] == cards
