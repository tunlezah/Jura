"""Binary sensor platform for the JURA Coffee Machines integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import JuraConfigEntry, JuraCoordinator
from .entity import JuraCoordinatorEntity, JuraEntity

# Coordinator is used to centralize the data updates
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class JuraAlertBinarySensorDescription(BinarySensorEntityDescription):
    """Describe an alert of the machine."""

    # the sensor is on if the name of an active alert contains the pattern
    name_pattern: str


# The keys are part of the unique IDs, don't change them
ALERT_SENSORS: tuple[JuraAlertBinarySensorDescription, ...] = (
    # Maintenance alerts (these are normal maintenance operations)
    JuraAlertBinarySensorDescription(
        key="insert_tray",
        translation_key="insert_tray",
        name_pattern="insert tray",
    ),
    JuraAlertBinarySensorDescription(
        key="fill_water",
        translation_key="fill_water",
        name_pattern="fill water",
    ),
    JuraAlertBinarySensorDescription(
        key="empty_grounds",
        translation_key="empty_grounds",
        name_pattern="empty grounds",
    ),
    JuraAlertBinarySensorDescription(
        key="empty_tray",
        translation_key="empty_tray",
        name_pattern="empty tray",
    ),
    # Service alerts (require cleaning or filter replacement)
    JuraAlertBinarySensorDescription(
        key="cleaning_alert",
        translation_key="cleaning_alert",
        name_pattern="cleaning alert",
    ),
    JuraAlertBinarySensorDescription(
        key="filter_alert",
        translation_key="filter_alert",
        name_pattern="filter alert",
    ),
    JuraAlertBinarySensorDescription(
        key="cappu_rinse_alert",
        translation_key="cappu_rinse_alert",
        name_pattern="cappu rinse alert",
    ),
    JuraAlertBinarySensorDescription(
        key="cappu_clean_alert",
        translation_key="cappu_clean_alert",
        name_pattern="cappu clean alert",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JuraConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors of a machine."""
    coordinator = entry.runtime_data

    async_add_entities(
        [
            JuraConnectionBinarySensor(coordinator, "connection"),
            *(
                JuraAlertBinarySensor(coordinator, description)
                for description in ALERT_SENSORS
            ),
        ]
    )


class JuraConnectionBinarySensor(JuraEntity, BinarySensorEntity):
    """Binary sensor for the Bluetooth connection to the machine."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # change with every advertisement, not worth keeping in the database
    _unrecorded_attributes = frozenset({"last_seen", "rssi"})

    @callback
    @override
    def _async_update_attrs(self) -> None:
        self._attr_is_on = self.device.connected
        self._attr_extra_state_attributes = dict(self.device.conn_info)


class JuraAlertBinarySensor(JuraCoordinatorEntity, BinarySensorEntity):
    """Binary sensor for an alert of the machine."""

    entity_description: JuraAlertBinarySensorDescription

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: JuraCoordinator,
        description: JuraAlertBinarySensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, f"alert_{description.key}")
        self.entity_description = description

    @property
    @override
    def is_on(self) -> bool | None:
        """Return True if an active alert matches the pattern."""
        if (alerts := self.coordinator.data.alerts) is None:
            return None

        pattern = self.entity_description.name_pattern
        return any(pattern in name.lower() for name in alerts.values())
