"""Fixtures for the tests of the JURA Coffee Machines integration."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant

# Must be imported before Home Assistant looks for the custom integrations
from custom_components.jura.const import CONF_MACHINE_DATA, DOMAIN

from .common import ADDRESS, ADV_E8, FakeBleakClient


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable the custom integration in all the tests."""


@pytest.fixture
def mock_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return the config entry of a machine."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Jura E8 (EB)",
        unique_id=ADDRESS,
        data={CONF_MAC: ADDRESS, CONF_MACHINE_DATA: ADV_E8.hex()},
        minor_version=2,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def fake_clients() -> Generator[list[FakeBleakClient]]:
    """Mock the connection to the machine, returns the clients created."""
    clients: list[FakeBleakClient] = []

    async def establish_connection(
        client_class, device, name, disconnected_callback=None, **kwargs
    ) -> FakeBleakClient:
        client = FakeBleakClient()
        client.disconnected_callback = disconnected_callback
        clients.append(client)
        return client

    with patch(
        "custom_components.jura.core.client.establish_connection",
        side_effect=establish_connection,
    ):
        yield clients


@pytest.fixture
def no_connection() -> Generator[None]:
    """Make the machine unreachable."""
    with (
        patch(
            "custom_components.jura.core.client.establish_connection",
            side_effect=TimeoutError,
        ),
        patch("custom_components.jura.core.client.CONNECT_TIMEOUT", 0),
        patch("custom_components.jura.core.client.RECONNECT_INTERVAL", 0.01),
    ):
        yield
