"""Switch platform for the JURA Coffee Machines integration."""

from __future__ import annotations

import asyncio
from typing import Any, override

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import JuraConfigEntry
from .entity import JuraEntity

# The switch only requests or releases the connection
PARALLEL_UPDATES = 0

# How long the switch waits for the connection to follow, in seconds
CONNECTION_TIMEOUT = 5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JuraConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switches of a machine."""
    async_add_entities([JuraConnectionSwitch(entry.runtime_data, "connection")])


class JuraConnectionSwitch(JuraEntity, SwitchEntity):
    """Switch to connect to the machine or to release the connection."""

    @callback
    @override
    def _async_update_attrs(self) -> None:
        self._attr_is_on = self.device.connected

    async def _async_wait_connected(self, connected: bool) -> None:
        for _ in range(CONNECTION_TIMEOUT):
            if self.device.connected == connected:
                return
            await asyncio.sleep(1)

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Connect to the machine."""
        self.device.client.ping()
        await self._async_wait_connected(True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Release the connection to the machine."""
        self.device.client.ping_cancel()
        await self._async_wait_connected(False)
