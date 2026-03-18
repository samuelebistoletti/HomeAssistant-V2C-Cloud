"""Tests for V2CEnumSelect entity logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


INSTALLATION_TYPES = {
    0: {"en": "Single-phase", "it": "Monofase"},
    1: {"en": "Three-phase", "it": "Trifase"},
    2: {"en": "Photovoltaic", "it": "Fotovoltaico"},
}


def _make_select(
    *,
    local_key=None,
    local_value=None,
    reported_value=None,
    options_map=None,
):
    from custom_components.v2c_cloud.select import V2CEnumSelect

    if options_map is None:
        options_map = INSTALLATION_TYPES

    reported = {}
    reported_lower = {}
    if reported_value is not None:
        reported = {"inst_type": reported_value}
        reported_lower = {"inst_type": reported_value}

    coord = MagicMock()
    coord.data = {
        "devices": {
            "dev-1": {
                "device_id": "dev-1",
                "pairing": {"deviceId": "dev-1"},
                "reported": reported,
                "additional": {
                    "reported_lower": reported_lower,
                    "static_ip": "192.168.1.1",
                },
            }
        },
        "pairings": [{"deviceId": "dev-1"}],
    }
    coord.last_update_success = True

    runtime_data = MagicMock()
    runtime_data.coordinator = coord

    if local_value is not None and local_key:
        local_coord = MagicMock()
        local_coord.data = {
            local_key: local_value,
            "_lower_index": {local_key.lower(): local_key},
        }
        local_coord.last_update_success = True
        runtime_data.local_coordinators = {"dev-1": local_coord}
    else:
        runtime_data.local_coordinators = {}

    hass = MagicMock()
    hass.config.language = "en"

    client = MagicMock()
    setter = AsyncMock()

    select = V2CEnumSelect(
        hass,
        coord,
        client,
        runtime_data,
        "dev-1",
        name_key="installation_type",
        unique_suffix="installation_type",
        options_map=options_map,
        setter=setter,
        reported_keys=("inst_type",),
        local_key=local_key,
        refresh_after_call=False,
    )
    return select, setter


class TestResolveValue:
    """Tests for V2CEnumSelect._resolve_value."""

    def test_int_in_map(self):
        select, _ = _make_select()
        assert select._resolve_value(0) == 0
        assert select._resolve_value(1) == 1

    def test_int_not_in_map_returns_none(self):
        select, _ = _make_select()
        assert select._resolve_value(99) is None

    def test_float_coerced_to_int(self):
        select, _ = _make_select()
        assert select._resolve_value(0.0) == 0

    def test_string_digit(self):
        select, _ = _make_select()
        assert select._resolve_value("1") == 1

    def test_string_label(self):
        select, _ = _make_select()
        assert select._resolve_value("single-phase") == 0

    def test_string_not_in_map_returns_none(self):
        select, _ = _make_select()
        assert select._resolve_value("unknown") is None

    def test_none_returns_none(self):
        select, _ = _make_select()
        assert select._resolve_value(None) is None


class TestCurrentOption:
    """Tests for V2CEnumSelect.current_option."""

    def test_returns_label_for_reported_value(self):
        select, _ = _make_select(reported_value=1)
        assert select.current_option == "Three-phase"

    def test_returns_none_when_no_data(self):
        select, _ = _make_select()
        assert select.current_option is None

    def test_optimistic_value_held(self):
        select, _ = _make_select(reported_value=0)
        select._optimistic_value = 2
        select._record_command()
        # Reported is 0 ("Single-phase") but optimistic is 2 ("Photovoltaic")
        result = select.current_option
        assert result == "Photovoltaic"

    def test_optimistic_cleared_when_matches(self):
        select, _ = _make_select(reported_value=1)
        select._optimistic_value = 1
        select._record_command()
        result = select.current_option
        assert result == "Three-phase"
        assert select._last_command_ts is None

    def test_options_list_is_populated(self):
        select, _ = _make_select()
        assert "Single-phase" in select._attr_options
        assert "Three-phase" in select._attr_options
        assert "Photovoltaic" in select._attr_options


class TestShouldHoldValue:
    """Tests for V2CEnumSelect._should_hold_value."""

    def test_holds_when_differs(self):
        select, _ = _make_select()
        select._optimistic_value = 1
        select._record_command()
        assert select._should_hold_value(0) is True

    def test_does_not_hold_when_same(self):
        select, _ = _make_select()
        select._optimistic_value = 1
        select._record_command()
        assert select._should_hold_value(1) is False

    def test_does_not_hold_without_optimistic(self):
        select, _ = _make_select()
        select._optimistic_value = None
        assert select._should_hold_value(0) is False


class TestLocalizedOptions:
    """Tests for _localized_options helper."""

    def test_english_options(self):
        from custom_components.v2c_cloud.select import _localized_options

        hass = MagicMock()
        hass.config.language = "en"
        result = _localized_options(INSTALLATION_TYPES, hass)
        assert result[0] == "Single-phase"
        assert result[1] == "Three-phase"

    def test_italian_options(self):
        from custom_components.v2c_cloud.select import _localized_options

        hass = MagicMock()
        hass.config.language = "it"
        result = _localized_options(INSTALLATION_TYPES, hass)
        assert result[0] == "Monofase"

    def test_unknown_language_falls_back_to_english(self):
        from custom_components.v2c_cloud.select import _localized_options

        hass = MagicMock()
        hass.config.language = "de"
        result = _localized_options(INSTALLATION_TYPES, hass)
        assert result[0] == "Single-phase"
