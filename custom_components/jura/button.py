"""Button platform for the JURA Coffee Machines integration."""

from __future__ import annotations

from typing import override

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import JuraConfigEntry
from .entity import JuraEntity

# The commands are queued and sent by the connection of the machine. Making a
# product must not wait for a statistics refresh.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JuraConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons of a machine."""
    coordinator = entry.runtime_data

    async_add_entities(
        [
            JuraMakeButton(coordinator, "make"),
            JuraRefreshStatsButton(coordinator, "refresh_stats"),
        ]
    )


class JuraMakeButton(JuraEntity, ButtonEntity):
    """Button to make the selected product."""

    @callback
    @override
    def _async_update_attrs(self) -> None:
        self._attr_available = self.device.product is not None

    @override
    async def async_press(self) -> None:
        """Make the selected product."""
        self.device.start_product()


class JuraRefreshStatsButton(JuraEntity, ButtonEntity):
    """Button to refresh the statistics and the alerts of the machine."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @override
    async def async_press(self) -> None:
        """Read the statistics and the alerts from the machine."""
        await self.coordinator.async_request_refresh()
