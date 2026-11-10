"""Select platform for the JURA Coffee Machines integration."""

from __future__ import annotations

from typing import override

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import JuraConfigEntry
from .entity import JuraEntity

# The options are kept locally until the product is made
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JuraConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the selects of a machine."""
    coordinator = entry.runtime_data

    async_add_entities(
        JuraSelect(coordinator, attr) for attr in coordinator.device.selects()
    )


class JuraSelect(JuraEntity, SelectEntity):
    """Select for the product or a setting of the selected product."""

    @callback
    @override
    def _async_update_attrs(self) -> None:
        attribute = self.device.attribute(self.attr)

        self._attr_current_option = attribute.get("default")
        self._attr_options = attribute.get("options", [])
        self._attr_available = "default" in attribute

    @override
    async def async_select_option(self, option: str) -> None:
        """Select the option for the selected product."""
        try:
            self.device.select_option(self.attr, option)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_option",
                translation_placeholders={"option": option},
            ) from err

        self._async_handle_update()
