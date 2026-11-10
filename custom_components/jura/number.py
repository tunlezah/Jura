"""Number platform for the JURA Coffee Machines integration."""

from __future__ import annotations

from typing import override

from homeassistant.components.number import NumberEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import JuraConfigEntry
from .entity import JuraEntity

# The values are kept locally until the product is made
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JuraConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the numbers of a machine."""
    coordinator = entry.runtime_data

    async_add_entities(
        JuraNumber(coordinator, attr) for attr in coordinator.device.numbers()
    )


class JuraNumber(JuraEntity, NumberEntity):
    """Number for a setting of the selected product."""

    @callback
    @override
    def _async_update_attrs(self) -> None:
        attribute = self.device.attribute(self.attr)

        self._attr_available = "value" in attribute
        self._attr_native_min_value = attribute.get("min", 0)
        self._attr_native_max_value = attribute.get("max", 0)
        self._attr_native_step = attribute.get("step", 1)
        self._attr_native_value = attribute.get("value")

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set the value for the selected product."""
        try:
            self.device.set_value(self.attr, int(value))
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_product_selected"
            ) from err

        self._async_handle_update()
