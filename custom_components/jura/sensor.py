"""Sensor platform for the JURA Coffee Machines integration."""

from __future__ import annotations

from typing import Any, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import JuraConfigEntry, JuraCoordinator
from .entity import JuraCoordinatorEntity

# Coordinator is used to centralize the data updates
PARALLEL_UPDATES = 0

# Alert bits which are not shown as alerts
FILTERED_ALERT_BITS = frozenset({12, 13, 36, 37, 148, 149, 150, 151})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JuraConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors of a machine."""
    coordinator = entry.runtime_data

    # Create the total coffees sensor
    entities: list[SensorEntity] = [JuraTotalCoffeeSensor(coordinator)]

    # Create sensors for each product
    product_names: set[str] = set()
    for product in coordinator.device.products:
        product_name = product["@Name"]
        if product.get("@Active") != "false" and product_name not in product_names:
            product_names.add(product_name)
            entities.append(JuraProductCountSensor(coordinator, product_name))

    # Create alert sensors
    entities.append(JuraAlertSensor(coordinator))

    async_add_entities(entities)


class JuraTotalCoffeeSensor(JuraCoordinatorEntity, SensorEntity):
    """Sensor for total coffee count."""

    _attr_native_unit_of_measurement = "products"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_translation_key = "total_products"

    def __init__(self, coordinator: JuraCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "total_product")

    @property
    @override
    def native_value(self) -> int | None:
        """Return the total count of the products."""
        return self.coordinator.data.total_products


class JuraProductCountSensor(JuraCoordinatorEntity, SensorEntity):
    """Sensor for individual product count."""

    _attr_native_unit_of_measurement = "products"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_translation_key = "product_count"

    def __init__(self, coordinator: JuraCoordinator, product_name: str) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator, f"product_{product_name.lower().replace(' ', '_')}"
        )
        self.product_name = product_name
        self._attr_translation_placeholders = {"product": product_name}

    @property
    @override
    def native_value(self) -> int | None:
        """Return the count of the product."""
        return self.coordinator.data.product_counts.get(self.product_name)


class JuraAlertSensor(JuraCoordinatorEntity, SensorEntity):
    """Sensor for machine alerts."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["ok", "alert"]
    _attr_translation_key = "alerts"

    def __init__(self, coordinator: JuraCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "alerts")

    @property
    def _active_alerts(self) -> list[dict[str, Any]] | None:
        if (alerts := self.coordinator.data.alerts) is None:
            return None

        return [
            {"bit": bit, "name": name}
            for bit, name in alerts.items()
            if bit not in FILTERED_ALERT_BITS
        ]

    @property
    @override
    def native_value(self) -> str | None:
        """Return the alert status."""
        if (active_alerts := self._active_alerts) is None:
            return None
        return "alert" if active_alerts else "ok"

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the active alerts."""
        return {"active_alerts": self._active_alerts or []}
