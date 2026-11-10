"""Helpers for the tests of the JURA Coffee Machines integration."""

from __future__ import annotations

import time

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError
from habluetooth import BluetoothServiceInfoBleak

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.bluetooth.api import _get_manager
from homeassistant.core import HomeAssistant

from custom_components.jura.core import encryption
from custom_components.jura.core.client import UUIDs

ADDRESS = "C8:DF:84:AA:BB:CC"
LOCAL_NAME = "TT214H BlueFrog"
MANUFACTURER_ID = 171

# Manufacturer data of real machines, the first byte is the key (0x2A)
ADV_E8 = b"*\x05\x08\x03\xfb;"
ADV_D4 = b"*\x05\x08\x03u;"
ADV_GIGA5 = b"*\x05\x08\x03=5"
ADV_J8 = b"*\x05\x08\x03\xc9<"
ADV_EMPTY = b"*\x05\x08\x03\x00\x00"
ADV_UNKNOWN = b"*\x05\x08\x03\x01\x00"
KEY = 0x2A


def make_service_info(
    manufacturer_data: bytes | None = ADV_E8,
    *,
    address: str = ADDRESS,
    name: str = LOCAL_NAME,
    rssi: int = -60,
    manufacturer_id: int = MANUFACTURER_ID,
) -> BluetoothServiceInfoBleak:
    """Create the advertisement of a machine."""
    data = {} if manufacturer_data is None else {manufacturer_id: manufacturer_data}
    return BluetoothServiceInfoBleak(
        name=name,
        address=address,
        rssi=rssi,
        manufacturer_data=data,
        service_data={},
        service_uuids=[],
        source="local",
        device=BLEDevice(address, name, {}),
        advertisement=AdvertisementData(
            local_name=name,
            manufacturer_data=data,
            service_data={},
            service_uuids=[],
            tx_power=None,
            rssi=rssi,
            platform_data=(),
        ),
        connectable=True,
        time=time.monotonic(),
        tx_power=None,
    )


def inject_bluetooth_service_info(
    hass: HomeAssistant, service_info: BluetoothServiceInfoBleak
) -> None:
    """Make Home Assistant receive an advertisement."""
    _get_manager(hass).scanner_adv_received(service_info)


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> bool:
    """Set up the config entry and wait for the first refresh of the data.

    The connection to the machine is a long running background task, so the
    tests must not wait for all the background tasks.
    """
    result = await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    if result:
        # waits for the refresh started by the setup
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
    return result


def statistics_payload(counts: dict[int, int], size: int = 20) -> bytes:
    """Create encrypted statistics, position 0 is the total."""
    data = bytearray()
    for i in range(size):
        data += counts.get(i, 0xFFFF).to_bytes(3, "big")
    return encryption.encdec(data, KEY)


def status_payload(*bits: int) -> bytes:
    """Create an encrypted machine status with the alert bits set."""
    data = bytearray(20)
    data[0] = KEY
    for bit in bits:
        data[(bit >> 3) + 1] |= 1 << (7 - (bit & 0b111))
    return encryption.encdec(data, KEY)


class FakeBleakClient:
    """Stand-in for the connection to a machine."""

    def __init__(self) -> None:
        """Initialize the client."""
        self.is_connected = True
        self.writes: list[tuple[str, bytes]] = []
        self.reads: dict[str, bytes] = {
            UUIDs.STATS_COMMAND: bytes([0x00, 0x00]),
            UUIDs.STATS_DATA: statistics_payload({0: 1234, 2: 200, 3: 300}),
            UUIDs.MACHINE_STATUS: status_payload(),
        }
        self.fail_writes = False
        self.disconnects = 0
        self.disconnected_callback = None

    def decrypted_writes(self, uuid: str) -> list[bytes]:
        """Return what was written to a characteristic."""
        return [
            encryption.encdec(data, KEY) for char, data in self.writes if char == uuid
        ]

    async def write_gatt_char(self, uuid, data, response=False) -> None:
        """Write to a characteristic."""
        if not self.is_connected or self.fail_writes:
            raise BleakError("Not connected")
        self.writes.append((uuid, bytes(data)))

    async def read_gatt_char(self, uuid) -> bytearray:
        """Read from a characteristic."""
        if not self.is_connected:
            raise BleakError("Not connected")
        return bytearray(self.reads[uuid])

    async def disconnect(self) -> None:
        """Disconnect from the machine."""
        self.is_connected = False
        self.disconnects += 1

    def drop(self) -> None:
        """Simulate that the machine went away."""
        self.is_connected = False
        if self.disconnected_callback:
            self.disconnected_callback(self)
