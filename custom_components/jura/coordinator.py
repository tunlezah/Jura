"""Data update coordinator for the JURA Coffee Machines integration."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, UPDATE_INTERVAL
from .core.device import Device

_LOGGER = logging.getLogger(__name__)

type JuraConfigEntry = ConfigEntry[JuraCoordinator]


@dataclass(frozen=True, slots=True)
class JuraData:
    """Data polled from the machine."""

    total_products: int | None = None
    product_counts: dict[str, int] = field(default_factory=dict)
    # None until the status was read from the machine for the first time
    alerts: dict[int, str] | None = None


class JuraCoordinator(DataUpdateCoordinator[JuraData]):
    """Poll the statistics and the alerts of a machine."""

    config_entry: JuraConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: JuraConfigEntry, device: Device
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} {device.mac}",
            update_interval=UPDATE_INTERVAL,
            # the data is a value object, so listeners only run on changes
            always_update=False,
        )
        self.device = device
        self.data = JuraData()

    @override
    async def _async_update_data(self) -> JuraData:
        """Read the statistics and the alerts from the machine.

        The machine is switched off most of the day, which is not an error: the
        counters are kept and the connection sensor tells if it is reachable.
        """
        device = self.device
        try:
            await device.read_statistics()
            await device.read_alerts()
        except Exception as err:
            # we log as debug as this is expected if the device is off
            _LOGGER.debug("Error reading from %s: %r", device.mac, err)

        statistics: dict[str, Any] = device.statistics
        return JuraData(
            total_products=statistics.get("total_products"),
            product_counts=dict(statistics.get("product_counts", {})),
            alerts=None if device.active_alerts is None else dict(device.active_alerts),
        )
