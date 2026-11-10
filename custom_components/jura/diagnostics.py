"""Diagnostics support for the JURA Coffee Machines integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant

from .coordinator import JuraConfigEntry

TO_REDACT = {CONF_MAC}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: JuraConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    device = coordinator.device

    conn_info = dict(device.conn_info)
    if last_seen := conn_info.get("last_seen"):
        conn_info["last_seen"] = last_seen.isoformat()

    return {
        "entry": {
            "title": entry.title,
            "version": entry.version,
            "minor_version": entry.minor_version,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
        },
        "machine": {
            "model": device.model,
            "products": [product.get("@Name") for product in device.products],
            "alerts": device.alerts,
            "selects": device.selects(),
            "numbers": device.numbers(),
        },
        "connection": {
            "connected": device.connected,
            **async_redact_data(conn_info, TO_REDACT),
        },
        "selected_product": device.product and device.product.get("@Name"),
        "data": asdict(coordinator.data),
    }
