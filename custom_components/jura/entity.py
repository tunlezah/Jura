"""Base entities for the JURA Coffee Machines integration."""

from __future__ import annotations

from typing import override

from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_NAME, DOMAIN
from .coordinator import JuraCoordinator
from .core.device import Device


def device_info(device: Device) -> DeviceInfo:
    """Return the device registry description of a machine."""
    return DeviceInfo(
        connections={(CONNECTION_BLUETOOTH, device.mac)},
        identifiers={(DOMAIN, device.mac)},
        manufacturer="Jura",
        model=device.model,
        name=device.name or DEFAULT_NAME,
    )


def unique_id(device: Device, attr: str) -> str:
    """Return the unique ID of an entity of a machine."""
    return device.mac.replace(":", "") + "_" + attr


class JuraEntity(Entity):
    """Entity which shows state held by the machine object (pushed)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: JuraCoordinator, attr: str) -> None:
        """Initialize the entity."""
        self.coordinator = coordinator
        self.device = coordinator.device
        self.attr = attr

        self._attr_device_info = device_info(self.device)
        self._attr_translation_key = attr
        self._attr_unique_id = unique_id(self.device, attr)

        self._async_update_attrs()

    @override
    async def async_added_to_hass(self) -> None:
        """Subscribe to the updates of the machine."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.device.register_update(self.attr, self._async_handle_update)
        )
        # the machine may have changed since the entity was created
        self._async_update_attrs()

    @callback
    def _async_handle_update(self) -> None:
        self._async_update_attrs()
        self.async_write_ha_state()

    @callback
    def _async_update_attrs(self) -> None:
        """Update the entity attributes from the machine."""

    @override
    async def async_update(self) -> None:
        """Wake up the connection when an update of the entity is requested."""
        self.device.client.ping()


class JuraCoordinatorEntity(CoordinatorEntity[JuraCoordinator]):
    """Entity which shows data polled from the machine."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: JuraCoordinator, attr: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.device = coordinator.device

        self._attr_device_info = device_info(self.device)
        self._attr_unique_id = unique_id(self.device, attr)
