"""Test the config flow of the JURA Coffee Machines integration."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.jura.const import CONF_MACHINE_DATA, DOMAIN

from .common import (
    ADDRESS,
    ADV_D4,
    ADV_E8,
    ADV_EMPTY,
    ADV_UNKNOWN,
    inject_bluetooth_service_info,
    make_service_info,
)

pytestmark = pytest.mark.usefixtures("enable_bluetooth")

ADDRESS_2 = "C8:DF:84:11:22:33"


@pytest.fixture(autouse=True)
def mock_setup_entry():
    """Don't set up the config entries created by the flows."""
    with patch(
        "custom_components.jura.async_setup_entry", return_value=None
    ) as mock_setup:
        yield mock_setup


async def test_user_flow(hass: HomeAssistant, mock_setup_entry) -> None:
    """Test that the user can pick a discovered machine."""
    inject_bluetooth_service_info(hass, make_service_info())
    inject_bluetooth_service_info(hass, make_service_info(ADV_D4, address=ADDRESS_2))
    # devices of other vendors are not offered
    inject_bluetooth_service_info(
        hass, make_service_info(ADV_E8, address="00:00:00:00:00:02", manufacturer_id=1)
    )
    inject_bluetooth_service_info(
        hass,
        make_service_info(ADV_UNKNOWN, address="00:00:00:00:00:03", name="Other"),
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    # the discovery flows are not what is tested here
    for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN):
        hass.config_entries.flow.async_abort(flow["flow_id"])

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["data_schema"].schema[CONF_MAC].container == {
        ADDRESS: f"Jura E8 (EB) ({ADDRESS})",
        ADDRESS_2: f"Jura D4 ({ADDRESS_2})",
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MAC: ADDRESS}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Jura E8 (EB)"
    assert result["data"] == {CONF_MAC: ADDRESS, CONF_MACHINE_DATA: ADV_E8.hex()}
    assert result["result"].unique_id == ADDRESS
    assert len(mock_setup_entry.mock_calls) == 1


async def test_user_flow_no_devices(hass: HomeAssistant) -> None:
    """Test the user flow when no machine is discovered."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_user_flow_unknown_model_by_name(hass: HomeAssistant) -> None:
    """Test that a dongle which doesn't tell the model yet can be picked."""
    inject_bluetooth_service_info(hass, make_service_info(ADV_EMPTY))
    await hass.async_block_till_done(wait_background_tasks=True)
    for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN):
        hass.config_entries.flow.async_abort(flow["flow_id"])

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MAC: ADDRESS}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Jura"
    assert result["data"] == {CONF_MAC: ADDRESS}


@pytest.mark.parametrize(
    "entry_kwargs",
    [
        {"unique_id": ADDRESS, "minor_version": 2},
        # created before the unique ID was introduced
        {"unique_id": None},
    ],
)
async def test_user_flow_already_configured(
    hass: HomeAssistant, entry_kwargs: dict
) -> None:
    """Test that a configured machine isn't offered again."""
    MockConfigEntry(
        domain=DOMAIN, data={CONF_MAC: ADDRESS}, **entry_kwargs
    ).add_to_hass(hass)
    inject_bluetooth_service_info(hass, make_service_info())
    await hass.async_block_till_done(wait_background_tasks=True)

    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_user_flow_configured_meanwhile(hass: HomeAssistant) -> None:
    """Test that the same machine can't be added twice."""
    inject_bluetooth_service_info(hass, make_service_info())
    await hass.async_block_till_done(wait_background_tasks=True)
    for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN):
        hass.config_entries.flow.async_abort(flow["flow_id"])

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, data={CONF_MAC: ADDRESS}, minor_version=2
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MAC: ADDRESS}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_bluetooth_discovery(hass: HomeAssistant, mock_setup_entry) -> None:
    """Test that a machine is discovered by its advertisement."""
    inject_bluetooth_service_info(hass, make_service_info())
    await hass.async_block_till_done(wait_background_tasks=True)

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_BLUETOOTH
    assert flows[0]["context"]["unique_id"] == ADDRESS
    assert flows[0]["context"]["title_placeholders"] == {"name": "Jura E8 (EB)"}
    assert flows[0]["step_id"] == "bluetooth_confirm"

    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Jura E8 (EB)"
    assert result["data"] == {CONF_MAC: ADDRESS, CONF_MACHINE_DATA: ADV_E8.hex()}
    assert result["result"].unique_id == ADDRESS
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize(
    "service_info",
    [
        # another device of the same Bluetooth company
        make_service_info(ADV_UNKNOWN, name="Other"),
        make_service_info(ADV_EMPTY, name="Other"),
        # a machine which isn't known
        make_service_info(ADV_UNKNOWN),
        # no JURA manufacturer data at all
        make_service_info(None),
    ],
)
async def test_bluetooth_discovery_not_supported(
    hass: HomeAssistant, service_info
) -> None:
    """Test that other devices are ignored."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


@pytest.mark.parametrize(
    "entry_kwargs",
    [
        {"unique_id": ADDRESS, "minor_version": 2},
        {"unique_id": None},
    ],
)
async def test_bluetooth_discovery_already_configured(
    hass: HomeAssistant, entry_kwargs: dict
) -> None:
    """Test that a configured machine isn't discovered again."""
    MockConfigEntry(
        domain=DOMAIN, data={CONF_MAC: ADDRESS}, **entry_kwargs
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=make_service_info()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
