"""Test the entities of the JURA Coffee Machines integration."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.jura.core.client import UUIDs

from .common import (
    FakeBleakClient,
    inject_bluetooth_service_info,
    make_service_info,
    setup_integration,
    statistics_payload,
    status_payload,
)

pytestmark = pytest.mark.usefixtures("enable_bluetooth")

PRODUCT = "select.jura_e8_eb_product"
COFFEE_STRENGTH = "select.jura_e8_eb_coffee_strength"
TEMPERATURE = "select.jura_e8_eb_temperature"
WATER_AMOUNT = "number.jura_e8_eb_water_amount"
MILK_FOAM_AMOUNT = "number.jura_e8_eb_milk_foam_amount"
MAKE = "button.jura_e8_eb_make"
REFRESH = "button.jura_e8_eb_refresh_statistics"
CONNECTION_SWITCH = "switch.jura_e8_eb_connection"
CONNECTION = "binary_sensor.jura_e8_eb_connection"


@pytest.fixture
async def client(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_clients: list[FakeBleakClient],
) -> FakeBleakClient:
    """Set up the integration with a connected machine."""
    inject_bluetooth_service_info(hass, make_service_info())
    assert await setup_integration(hass, mock_config_entry)
    return fake_clients[0]


async def select_option(hass: HomeAssistant, entity_id: str, option: str) -> None:
    """Select an option."""
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: option},
        blocking=True,
    )


async def press(hass: HomeAssistant, entity_id: str) -> None:
    """Press a button."""
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )


async def test_make_product(hass: HomeAssistant, client: FakeBleakClient) -> None:
    """Test selecting a product, changing its settings and making it."""
    # nothing can be made or set before a product is selected
    assert hass.states.get(PRODUCT).state == STATE_UNKNOWN
    assert "Cafe Barista" in hass.states.get(PRODUCT).attributes["options"]
    assert "Powderproduct" not in hass.states.get(PRODUCT).attributes["options"]
    for entity_id in (MAKE, COFFEE_STRENGTH, TEMPERATURE, WATER_AMOUNT):
        assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    await select_option(hass, PRODUCT, "Cafe Barista")

    assert hass.states.get(PRODUCT).state == "Cafe Barista"
    assert hass.states.get(MAKE).state != STATE_UNAVAILABLE
    state = hass.states.get(COFFEE_STRENGTH)
    assert state.state == "6"
    assert state.attributes["options"] == [str(i) for i in range(1, 11)]
    state = hass.states.get(WATER_AMOUNT)
    assert state.state == "90"
    assert (state.attributes["min"], state.attributes["max"]) == (25, 240)
    assert state.attributes["step"] == 5
    # this product has no milk foam
    assert hass.states.get(MILK_FOAM_AMOUNT).state == STATE_UNAVAILABLE

    await press(hass, MAKE)
    await hass.async_block_till_done()
    assert [data.hex() for data in client.decrypted_writes(UUIDs.START_PRODUCT)] == [
        "2a280006120000010000090000000000002a"
    ]

    await select_option(hass, COFFEE_STRENGTH, "10")
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: WATER_AMOUNT, ATTR_VALUE: 50},
        blocking=True,
    )
    assert hass.states.get(COFFEE_STRENGTH).state == "10"
    assert hass.states.get(WATER_AMOUNT).state == "50"

    await press(hass, MAKE)
    await hass.async_block_till_done()
    assert client.decrypted_writes(UUIDs.START_PRODUCT)[-1].hex() == (
        "2a28000a0a0000010000090000000000002a"
    )

    # another product starts with its own defaults
    await select_option(hass, PRODUCT, "Cappuccino")
    assert hass.states.get(COFFEE_STRENGTH).state == "8"
    assert hass.states.get(MILK_FOAM_AMOUNT).state != STATE_UNAVAILABLE

    await press(hass, MAKE)
    await hass.async_block_till_done()
    assert client.decrypted_writes(UUIDs.START_PRODUCT)[-1].hex() == (
        "2a0400080c000e010000000000000000002a"
    )


async def test_select_invalid_option(
    hass: HomeAssistant, client: FakeBleakClient
) -> None:
    """Test that an option of another product is refused."""
    await select_option(hass, PRODUCT, "Cafe Barista")

    with pytest.raises(ServiceValidationError):
        await select_option(hass, COFFEE_STRENGTH, "XStrong")
    assert hass.states.get(COFFEE_STRENGTH).state == "6"


async def test_statistics_and_alerts(
    hass: HomeAssistant, client: FakeBleakClient
) -> None:
    """Test the sensors read from the machine."""
    assert hass.states.get(CONNECTION).state == STATE_ON
    state = hass.states.get("sensor.jura_e8_eb_total_products")
    assert state.state == "1234"
    assert state.attributes["unit_of_measurement"] == "products"
    assert state.attributes["state_class"] == "total_increasing"
    assert hass.states.get("sensor.jura_e8_eb_espresso_count").state == "200"
    assert hass.states.get("sensor.jura_e8_eb_coffee_count").state == "300"
    assert hass.states.get("sensor.jura_e8_eb_cappuccino_count").state == "0"
    # the machine didn't report this product
    assert hass.states.get("sensor.jura_e8_eb_cortado_count").state == STATE_UNKNOWN

    state = hass.states.get("sensor.jura_e8_eb_alerts")
    assert state.state == "ok"
    assert state.attributes["active_alerts"] == []
    assert hass.states.get("binary_sensor.jura_e8_eb_fill_water").state == STATE_OFF

    # fill water (1), heating up (12, not shown as an alert), cleaning alert (34)
    client.reads[UUIDs.MACHINE_STATUS] = status_payload(1, 12, 34)
    client.reads[UUIDs.STATS_DATA] = statistics_payload({0: 1235, 2: 201, 3: 300})
    await press(hass, REFRESH)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.jura_e8_eb_total_products").state == "1235"
    assert hass.states.get("sensor.jura_e8_eb_espresso_count").state == "201"
    state = hass.states.get("sensor.jura_e8_eb_alerts")
    assert state.state == "alert"
    assert state.attributes["active_alerts"] == [
        {"bit": 1, "name": "fill water"},
        {"bit": 34, "name": "cleaning alert"},
    ]
    assert hass.states.get("binary_sensor.jura_e8_eb_fill_water").state == STATE_ON
    assert hass.states.get("binary_sensor.jura_e8_eb_cleaning_needed").state == STATE_ON
    assert hass.states.get("binary_sensor.jura_e8_eb_empty_tray").state == STATE_OFF


async def test_read_errors_keep_last_values(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, client: FakeBleakClient
) -> None:
    """Test that the values are kept while the machine can't be read."""
    coordinator = mock_config_entry.runtime_data

    # implausible statistics are ignored
    client.reads[UUIDs.STATS_DATA] = statistics_payload({0: 0})
    await coordinator.async_refresh()
    assert hass.states.get("sensor.jura_e8_eb_total_products").state == "1234"

    client.reads[UUIDs.STATS_DATA] = b""
    await coordinator.async_refresh()
    assert hass.states.get("sensor.jura_e8_eb_total_products").state == "1234"

    # the machine was switched off
    with patch("custom_components.jura.core.client.CONNECT_TIMEOUT", 0):
        client.drop()
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert coordinator.last_update_success
    assert hass.states.get("sensor.jura_e8_eb_total_products").state == "1234"
    assert hass.states.get("sensor.jura_e8_eb_espresso_count").state == "200"
    assert hass.states.get("sensor.jura_e8_eb_alerts").state == "ok"


async def test_connection_switch(
    hass: HomeAssistant,
    client: FakeBleakClient,
    fake_clients: list[FakeBleakClient],
) -> None:
    """Test releasing and requesting the connection."""
    assert hass.states.get(CONNECTION_SWITCH).state == STATE_ON

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: CONNECTION_SWITCH},
        blocking=True,
    )
    assert hass.states.get(CONNECTION_SWITCH).state == STATE_OFF
    assert hass.states.get(CONNECTION).state == STATE_OFF
    assert client.disconnects == 1

    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: CONNECTION_SWITCH},
        blocking=True,
    )
    assert hass.states.get(CONNECTION_SWITCH).state == STATE_ON
    assert hass.states.get(CONNECTION).state == STATE_ON
    assert len(fake_clients) == 2


async def test_reconnect_after_connection_lost(
    hass: HomeAssistant,
    client: FakeBleakClient,
    fake_clients: list[FakeBleakClient],
) -> None:
    """Test that a dropped connection is noticed and established again."""
    with patch("custom_components.jura.core.client.RECONNECT_INTERVAL", 0):
        client.drop()
        for _ in range(10):
            await hass.async_block_till_done()
            if len(fake_clients) == 2:
                break

    assert len(fake_clients) == 2
    assert hass.states.get(CONNECTION).state == STATE_ON

    # commands go to the new connection
    await select_option(hass, PRODUCT, "Espresso")
    await press(hass, MAKE)
    await hass.async_block_till_done()
    assert not client.decrypted_writes(UUIDs.START_PRODUCT)
    assert len(fake_clients[1].decrypted_writes(UUIDs.START_PRODUCT)) == 1
