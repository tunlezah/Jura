"""Test the setup of the JURA Coffee Machines integration."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_MAC, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.jura.const import CONF_MACHINE_DATA, DOMAIN

from .common import (
    ADDRESS,
    ADV_D4,
    ADV_E8,
    ADV_EMPTY,
    ADV_UNKNOWN,
    FakeBleakClient,
    inject_bluetooth_service_info,
    make_service_info,
    setup_integration,
)

pytestmark = pytest.mark.usefixtures("enable_bluetooth")


async def test_setup_unload_reload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_clients: list[FakeBleakClient],
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test that the entry can be set up, unloaded and set up again."""
    inject_bluetooth_service_info(hass, make_service_info())

    assert await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, ADDRESS), mock_config_entry.entry_id
    )
    assert device is not None
    assert device.name == "Jura E8 (EB)"
    assert device.model == "E8 (EB)"
    assert (dr.CONNECTION_BLUETOOTH, ADDRESS) in device.connections

    entities = er.async_entries_for_config_entry(
        entity_registry, mock_config_entry.entry_id
    )
    # the unique IDs of the previous versions are kept
    assert {entity.unique_id for entity in entities} >= {
        "C8DF84AABBCC_connection",
        "C8DF84AABBCC_alert_fill_water",
        "C8DF84AABBCC_make",
        "C8DF84AABBCC_refresh_stats",
        "C8DF84AABBCC_water_amount",
        "C8DF84AABBCC_product",
        "C8DF84AABBCC_coffee_strength",
        "C8DF84AABBCC_total_product",
        "C8DF84AABBCC_product_espresso",
        "C8DF84AABBCC_product_hotwater_portion(normal)",
        "C8DF84AABBCC_alerts",
    }
    assert len(entities) == 35

    # the first refresh connected to the machine
    assert len(fake_clients) == 1
    assert hass.states.get("binary_sensor.jura_e8_eb_connection").state == STATE_ON
    assert hass.states.get("sensor.jura_e8_eb_total_products").state == "1234"

    coordinator = mock_config_entry.runtime_data
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED

    # the connection is closed and nothing is left running
    assert coordinator.device.client.ping_task is None
    assert coordinator.device.client.client is None
    assert fake_clients[0].disconnects == 1
    assert not coordinator.device.updates_connect
    assert not coordinator.device.updates_product
    assert (
        hass.states.get("binary_sensor.jura_e8_eb_connection").state
        == STATE_UNAVAILABLE
    )

    # a stopped client never connects again
    coordinator.device.client.ping()
    assert coordinator.device.client.ping_task is None

    # everything works again after a reload
    assert await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data is not coordinator
    assert len(fake_clients) == 2
    assert hass.states.get("binary_sensor.jura_e8_eb_connection").state == STATE_ON
    assert hass.states.get("select.jura_e8_eb_product") is not None


async def test_setup_device_not_found(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that the setup is retried while the machine isn't seen."""
    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert mock_config_entry.error_reason_translation_key == "device_not_found"


async def test_setup_machine_not_identified(hass: HomeAssistant) -> None:
    """Test that the setup is retried while the model of the machine is unknown."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, data={CONF_MAC: ADDRESS}, minor_version=2
    )
    entry.add_to_hass(hass)
    inject_bluetooth_service_info(hass, make_service_info(ADV_EMPTY))

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.error_reason_translation_key == "machine_not_identified"


@pytest.mark.usefixtures("no_connection")
async def test_setup_uses_stored_machine_data(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test the setup while the machine doesn't tell its model."""
    inject_bluetooth_service_info(hass, make_service_info(ADV_EMPTY))

    assert await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data.device.model == "E8 (EB)"
    assert mock_config_entry.data[CONF_MACHINE_DATA] == ADV_E8.hex()
    # the machine is unreachable: no data yet, but the entities are there
    assert hass.states.get("binary_sensor.jura_e8_eb_connection").state == STATE_OFF
    assert hass.states.get("sensor.jura_e8_eb_total_products").state == "unknown"
    assert hass.states.get("binary_sensor.jura_e8_eb_fill_water").state == "unknown"
    assert hass.states.get("sensor.jura_e8_eb_alerts").state == "unknown"


@pytest.mark.usefixtures("no_connection")
async def test_setup_stores_machine_data(hass: HomeAssistant) -> None:
    """Test that the model from the advertisement is stored and preferred."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Jura",
        unique_id=ADDRESS,
        data={CONF_MAC: ADDRESS, CONF_MACHINE_DATA: ADV_E8.hex()},
        minor_version=2,
    )
    entry.add_to_hass(hass)
    inject_bluetooth_service_info(hass, make_service_info(ADV_D4 + b"\x01\x02"))

    assert await setup_integration(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.device.model == "D4"
    assert entry.data == {CONF_MAC: ADDRESS, CONF_MACHINE_DATA: ADV_D4.hex()}


async def test_setup_unsupported_model(hass: HomeAssistant) -> None:
    """Test that an unknown model isn't retried."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, data={CONF_MAC: ADDRESS}, minor_version=2
    )
    entry.add_to_hass(hass)
    inject_bluetooth_service_info(hass, make_service_info(ADV_UNKNOWN))

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.error_reason_translation_key == "unsupported_model"


@pytest.mark.usefixtures("no_connection")
async def test_migrate_entry(hass: HomeAssistant) -> None:
    """Test the migration of an entry created by a previous version."""
    entry = MockConfigEntry(domain=DOMAIN, title="", data={CONF_MAC: ADDRESS})
    entry.add_to_hass(hass)
    assert entry.unique_id is None
    inject_bluetooth_service_info(hass, make_service_info())

    assert await setup_integration(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.minor_version == 2
    assert entry.unique_id == ADDRESS
    assert entry.title == "Jura"
    # the name of the device isn't changed by the update
    assert entry.runtime_data.device.name == "Jura"
    assert hass.states.get("binary_sensor.jura_connection") is not None


@pytest.mark.usefixtures("no_connection")
async def test_migrate_duplicated_entry(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test the migration of an entry for an already configured machine."""
    entry = MockConfigEntry(domain=DOMAIN, title="", data={CONF_MAC: ADDRESS})
    entry.add_to_hass(hass)
    inject_bluetooth_service_info(hass, make_service_info())

    assert await setup_integration(hass, entry)

    assert entry.minor_version == 2
    assert entry.unique_id is None
    assert mock_config_entry.unique_id == ADDRESS


@pytest.mark.usefixtures("no_connection")
async def test_advertisement_updates_device(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that a new advertisement updates the connection details."""
    inject_bluetooth_service_info(hass, make_service_info())
    assert await setup_integration(hass, mock_config_entry)
    device = mock_config_entry.runtime_data.device

    service_info = make_service_info(b"\x33" + ADV_E8[1:] + b"\x01", rssi=-42)
    inject_bluetooth_service_info(hass, service_info)
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.jura_e8_eb_connection")
    assert state.attributes["rssi"] == -42
    assert state.attributes["mac"] == ADDRESS
    assert "last_seen" in state.attributes
    # the latest path to the machine and its key are used
    assert device.client.device is service_info.device
    assert device.client.key == 0x33

    # the key is only taken from a complete advertisement
    inject_bluetooth_service_info(hass, make_service_info(b"\x00" * 8, rssi=-43))
    await hass.async_block_till_done()
    assert device.client.key == 0x33


@pytest.mark.usefixtures("no_connection")
async def test_existing_registry_entries_are_kept(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test that the device and the entities of a previous version are reused."""
    entry = MockConfigEntry(domain=DOMAIN, title="", data={CONF_MAC: ADDRESS})
    entry.add_to_hass(hass)
    old_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, ADDRESS)},
        identifiers={(DOMAIN, ADDRESS)},
        manufacturer="Jura",
        model="E8 (EB)",
        name="Jura",
    )
    old_entity = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "C8DF84AABBCC_total_product",
        config_entry=entry,
        device_id=old_device.id,
        suggested_object_id="c8df84aabbcc_total_product",
    )
    inject_bluetooth_service_info(hass, make_service_info())

    assert await setup_integration(hass, entry)

    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert [device.id for device in devices] == [old_device.id]
    assert devices[0].name == "Jura"

    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, "C8DF84AABBCC_total_product"
    )
    assert entity_id == old_entity.entity_id
    assert hass.states.get(entity_id) is not None
