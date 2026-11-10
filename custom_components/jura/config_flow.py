"""Config flow for the JURA Coffee Machines integration."""

from __future__ import annotations

import logging
from typing import Any, override

import probatio

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_MAC

from .const import CONF_MACHINE_DATA, DEFAULT_NAME, DOMAIN, LOCAL_NAME
from .core.device import (
    MACHINE_DATA_LEN,
    MANUFACTURER_ID,
    EmptyModel,
    UnsupportedModel,
    get_machine,
)

_LOGGER = logging.getLogger(__name__)


class JuraConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for JURA coffee machines."""

    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        # address -> (title, config entry data)
        self._discovered: dict[str, tuple[str, dict[str, Any]]] = {}

    async def _async_identify(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> tuple[str, dict[str, Any]] | None:
        """Return the title and the config entry data of a machine.

        Returns None if the device isn't a JURA coffee machine.
        """
        adv = discovery_info.manufacturer_data.get(MANUFACTURER_ID)
        if not adv:
            return None

        data: dict[str, Any] = {CONF_MAC: discovery_info.address}
        try:
            # reads the machine description from a file
            machine = await self.hass.async_add_executor_job(get_machine, adv)
        except UnsupportedModel as err:
            if discovery_info.name == LOCAL_NAME:
                _LOGGER.warning(
                    "Unsupported JURA model %s (%s)",
                    err.args[0],
                    discovery_info.address,
                )
            return None
        except EmptyModel:
            # The dongle doesn't always tell the model, the name is enough to
            # know what it is. The setup waits for the model.
            if discovery_info.name != LOCAL_NAME:
                return None
            return DEFAULT_NAME, data

        data[CONF_MACHINE_DATA] = bytes(adv[:MACHINE_DATA_LEN]).hex()
        return f"{DEFAULT_NAME} {machine['model']}", data

    @override
    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle the Bluetooth discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        # entries created before the unique ID was introduced
        self._async_abort_entries_match({CONF_MAC: discovery_info.address})

        if not (machine := await self._async_identify(discovery_info)):
            return self.async_abort(reason="not_supported")

        self._discovery_info = discovery_info
        self._discovered[discovery_info.address] = machine
        self.context["title_placeholders"] = {"name": machine[0]}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the discovery."""
        assert self._discovery_info is not None
        title, data = self._discovered[self._discovery_info.address]

        if user_input is not None:
            return self.async_create_entry(title=title, data=data)

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": title,
                "address": self._discovery_info.address,
            },
        )

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step to pick a discovered machine."""
        if user_input is not None:
            address = user_input[CONF_MAC]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._async_abort_entries_match({CONF_MAC: address})

            title, data = self._discovered[address]
            return self.async_create_entry(title=title, data=data)

        current_addresses = self._async_current_ids(include_ignore=False) | {
            entry.data.get(CONF_MAC) for entry in self._async_current_entries()
        }
        for discovery_info in async_discovered_service_info(
            self.hass, connectable=True
        ):
            address = discovery_info.address
            if address in current_addresses or address in self._discovered:
                continue
            if machine := await self._async_identify(discovery_info):
                self._discovered[address] = machine

        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_MAC): probatio.In(
                        {
                            address: f"{title} ({address})"
                            for address, (title, _) in self._discovered.items()
                        }
                    ),
                }
            ),
        )
