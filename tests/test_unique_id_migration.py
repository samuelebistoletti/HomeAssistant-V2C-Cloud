"""
Regression coverage for the Active Transport sensor's unique_id scheme.

1.4.0-beta.1 introduced ``V2CTransportSensor`` with
``f"{device_id}_active_transport"`` as its unique_id — the only entity in the
integration without the ``v2c_`` prefix every other unique_id uses, an
unrequested departure from the project's descriptive ("parlante") naming
convention. Fixed by prefixing the id in code AND migrating any existing
entity registry entry in place, so upgrading users keep their entity_id,
history and automations instead of getting an orphaned entity plus a new one.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.helpers import entity_registry as er

from custom_components.v2c_cloud import _async_migrate_transport_sensor_unique_id
from custom_components.v2c_cloud.sensor import V2CTransportSensor

DEVICE_ID = "XQUXDU"
ENTRY_ID = "entry-1"


class TestTransportSensorUniqueId:
    def test_unique_id_uses_the_shared_v2c_prefix(self) -> None:
        sensor = V2CTransportSensor(MagicMock(), MagicMock(), DEVICE_ID)
        assert sensor._attr_unique_id == f"v2c_{DEVICE_ID}_active_transport"


class TestMigrateTransportSensorUniqueId:
    def _registry(self) -> er.EntityRegistry:
        registry = er.async_get(MagicMock())
        registry.entities.clear()
        return registry

    def test_renames_the_old_scheme_in_place(self) -> None:
        registry = self._registry()
        registry.entities["sensor.xquxdu_trasporto_attivo"] = er.RegistryEntry(
            entity_id="sensor.xquxdu_trasporto_attivo",
            unique_id=f"{DEVICE_ID}_active_transport",
            domain="sensor",
            config_entry_id=ENTRY_ID,
        )
        entry = MagicMock()
        entry.entry_id = ENTRY_ID

        _async_migrate_transport_sensor_unique_id(MagicMock(), entry)

        entry_after = registry.entities["sensor.xquxdu_trasporto_attivo"]
        assert entry_after.unique_id == f"v2c_{DEVICE_ID}_active_transport"

    def test_already_prefixed_is_left_alone(self) -> None:
        registry = self._registry()
        registry.entities["sensor.xquxdu_trasporto_attivo"] = er.RegistryEntry(
            entity_id="sensor.xquxdu_trasporto_attivo",
            unique_id=f"v2c_{DEVICE_ID}_active_transport",
            domain="sensor",
            config_entry_id=ENTRY_ID,
        )
        entry = MagicMock()
        entry.entry_id = ENTRY_ID

        _async_migrate_transport_sensor_unique_id(MagicMock(), entry)

        entry_after = registry.entities["sensor.xquxdu_trasporto_attivo"]
        assert entry_after.unique_id == f"v2c_{DEVICE_ID}_active_transport"

    def test_ignores_other_domains_and_other_entries(self) -> None:
        registry = self._registry()
        registry.entities["button.xquxdu_active_transport"] = er.RegistryEntry(
            entity_id="button.xquxdu_active_transport",
            unique_id=f"{DEVICE_ID}_active_transport",
            domain="button",
            config_entry_id=ENTRY_ID,
        )
        registry.entities["sensor.other_charge_power"] = er.RegistryEntry(
            entity_id="sensor.other_charge_power",
            unique_id=f"v2c_{DEVICE_ID}_charge_power",
            domain="sensor",
            config_entry_id=ENTRY_ID,
        )
        entry = MagicMock()
        entry.entry_id = ENTRY_ID

        _async_migrate_transport_sensor_unique_id(MagicMock(), entry)

        assert (
            registry.entities["button.xquxdu_active_transport"].unique_id
            == f"{DEVICE_ID}_active_transport"
        )
        assert (
            registry.entities["sensor.other_charge_power"].unique_id
            == f"v2c_{DEVICE_ID}_charge_power"
        )

    def test_ignores_entries_for_a_different_config_entry(self) -> None:
        registry = self._registry()
        registry.entities["sensor.xquxdu_trasporto_attivo"] = er.RegistryEntry(
            entity_id="sensor.xquxdu_trasporto_attivo",
            unique_id=f"{DEVICE_ID}_active_transport",
            domain="sensor",
            config_entry_id="some-other-entry",
        )
        entry = MagicMock()
        entry.entry_id = ENTRY_ID

        _async_migrate_transport_sensor_unique_id(MagicMock(), entry)

        assert (
            registry.entities["sensor.xquxdu_trasporto_attivo"].unique_id
            == f"{DEVICE_ID}_active_transport"
        )
