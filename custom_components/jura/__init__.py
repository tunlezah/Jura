"""The JURA Coffee Machines integration."""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothReachabilityIntent
from homeassistant.components.bluetooth.match import (
    ADDRESS,
    CONNECTABLE,
    BluetoothCallbackMatcher,
)
from homeassistant.const import CONF_MAC, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady

from .const import CONF_MACHINE_DATA, DEFAULT_NAME, DOMAIN
from .coordinator import JuraConfigEntry, JuraCoordinator
from .core.device import (
    MACHINE_DATA_LEN,
    MANUFACTURER_ID,
    Device,
    UnsupportedModel,
    get_machine,
    model_id_from_advertisement,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


@callback
def _async_machine_data(hass: HomeAssistant, entry: JuraConfigEntry) -> bytes | None:
    """Return the key and the model of the machine.

    The latest advertisement is preferred, the data kept in the config entry is
    used while the machine doesn't tell its model.
    """
    address: str = entry.data[CONF_MAC]

    if (
        (info := bluetooth.async_last_service_info(hass, address, connectable=True))
        and (adv := info.manufacturer_data.get(MANUFACTURER_ID))
        and model_id_from_advertisement(adv)
    ):
        return bytes(adv[:MACHINE_DATA_LEN])

    try:
        data = bytes.fromhex(entry.data.get(CONF_MACHINE_DATA, ""))
    except TypeError, ValueError:
        return None

    return data if model_id_from_advertisement(data) else None


async def async_setup_entry(hass: HomeAssistant, entry: JuraConfigEntry) -> None:
    """Set up a JURA coffee machine from a config entry."""
    address: str = entry.data[CONF_MAC]

    ble_device = bluetooth.async_ble_device_from_address(
        hass, address, connectable=True
    )
    if not ble_device:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={
                "address": address,
                "reason": bluetooth.async_address_reachability_diagnostics(
                    hass, address, BluetoothReachabilityIntent.CONNECTION
                ),
            },
        )

    if not (machine_data := _async_machine_data(hass, entry)):
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="machine_not_identified",
            translation_placeholders={"address": address},
        )

    try:
        # reads the machine description from a file
        machine = await hass.async_add_executor_job(get_machine, machine_data)
    except UnsupportedModel as err:
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="unsupported_model",
            translation_placeholders={"model_id": str(err.args[0])},
        ) from err

    if entry.data.get(CONF_MACHINE_DATA) != machine_data.hex():
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_MACHINE_DATA: machine_data.hex()}
        )

    device = Device(
        entry.title or DEFAULT_NAME,
        machine["model"],
        machine["products"],
        machine["alerts"],
        machine["key"],
        ble_device,
        # stopped with the config entry, never blocks the startup
        create_task=lambda coro: entry.async_create_background_task(
            hass, coro, f"{DOMAIN} {address} connection"
        ),
    )

    coordinator = JuraCoordinator(hass, entry, device)
    entry.runtime_data = coordinator

    @callback
    def _async_update_ble(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Update from a Bluetooth advertisement."""
        _LOGGER.debug("%s %s", change, service_info.advertisement)
        device.update_ble(service_info.advertisement, service_info.device)

    # https://developers.home-assistant.io/docs/core/bluetooth/api/
    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_update_ble,
            BluetoothCallbackMatcher({ADDRESS: address, CONNECTABLE: True}),
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _async_stop(event: Event) -> None:
        """Close the connection."""
        await device.client.stop()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop)
    )

    # The machine is often switched off, don't make the setup wait for it
    entry.async_create_background_task(
        hass, coordinator.async_refresh(), f"{DOMAIN} {address} first refresh"
    )


async def async_unload_entry(hass: HomeAssistant, entry: JuraConfigEntry) -> None:
    """Unload a config entry."""
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
    await entry.runtime_data.device.client.stop()


async def async_migrate_entry(hass: HomeAssistant, entry: JuraConfigEntry) -> None:
    """Migrate an old config entry."""
    if entry.minor_version < 2:
        # 1.1 -> 1.2: entries had neither a unique ID nor a title
        address: str = entry.data[CONF_MAC]
        unique_id = entry.unique_id
        if (
            unique_id is None
            and not hass.config_entries.async_entry_for_domain_unique_id(
                DOMAIN, address
            )
        ):
            unique_id = address

        hass.config_entries.async_update_entry(
            entry,
            unique_id=unique_id,
            title=entry.title or DEFAULT_NAME,
            minor_version=2,
        )

    _LOGGER.debug(
        "Migrated config entry to version %s.%s", entry.version, entry.minor_version
    )
