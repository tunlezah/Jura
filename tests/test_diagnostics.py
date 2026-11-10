"""Test the diagnostics of the JURA Coffee Machines integration."""

from __future__ import annotations

import json

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.jura.diagnostics import async_get_config_entry_diagnostics

from .common import (
    ADDRESS,
    FakeBleakClient,
    inject_bluetooth_service_info,
    make_service_info,
    setup_integration,
)

pytestmark = pytest.mark.usefixtures("enable_bluetooth")


async def test_diagnostics(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_clients: list[FakeBleakClient],
) -> None:
    """Test the diagnostics of a config entry."""
    inject_bluetooth_service_info(hass, make_service_info())
    assert await setup_integration(hass, mock_config_entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    # the result can be downloaded as JSON and doesn't tell the address
    assert ADDRESS not in json.dumps(diagnostics)
    assert diagnostics["entry"]["data"] == {
        "mac": "**REDACTED**",
        "machine_data": "2a050803fb3b",
    }
    assert diagnostics["machine"]["model"] == "E8 (EB)"
    assert "Espresso" in diagnostics["machine"]["products"]
    assert diagnostics["connection"]["connected"] is True
    assert diagnostics["selected_product"] is None
    assert diagnostics["data"]["total_products"] == 1234
    assert diagnostics["data"]["alerts"] == {}
