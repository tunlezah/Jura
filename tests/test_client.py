"""Test the Bluetooth client of the JURA Coffee Machines integration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import patch

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
import pytest

from custom_components.jura.core import client as client_module
from custom_components.jura.core.client import Client, UUIDs

from .common import ADDRESS, KEY, FakeBleakClient

HEARTBEAT = bytes([KEY, 0x7F, 0x80])
COMMAND = bytes.fromhex("002800061200000100000900000000000000")


@pytest.fixture(autouse=True)
def socket_enabled(socket_enabled: None) -> None:
    """These tests don't need Home Assistant, only an event loop."""


@pytest.fixture
async def states() -> list[bool]:
    """Return the connection states reported by the client."""
    return []


@pytest.fixture
async def client(states: list[bool]) -> AsyncGenerator[Client]:
    """Return a client which is stopped after the test."""
    client = Client(BLEDevice(ADDRESS, "TT214H BlueFrog", {}), states.append, KEY)
    yield client
    await client.stop()
    assert client.ping_task is None


async def wait_for(condition) -> None:
    """Wait until the condition is met."""
    async with asyncio.timeout(5):
        while not condition():
            await asyncio.sleep(0.001)


async def test_connect_heartbeat_and_release(
    client: Client, fake_clients: list[FakeBleakClient], states: list[bool]
) -> None:
    """Test the life cycle of the connection."""
    with patch.object(client_module, "HEARTBEAT_INTERVAL", 0.01):
        client.ping()
        await wait_for(lambda: fake_clients and len(fake_clients[0].writes) >= 3)

        assert states == [True]
        assert fake_clients[0].decrypted_writes(UUIDs.P_MODE)[0] == HEARTBEAT

        client.ping_cancel()
        await wait_for(lambda: client.ping_task is None)

    assert states == [True, False]
    assert client.client is None
    assert fake_clients[0].disconnects == 1
    assert len(fake_clients) == 1


async def test_command_is_sent_once_connected(
    client: Client, fake_clients: list[FakeBleakClient]
) -> None:
    """Test that a command wakes up the connection and is sent first."""
    client.send(COMMAND)
    await wait_for(lambda: fake_clients and len(fake_clients[0].writes) >= 2)

    assert [uuid for uuid, _ in fake_clients[0].writes] == [
        UUIDs.START_PRODUCT,
        UUIDs.P_MODE,
    ]
    assert fake_clients[0].decrypted_writes(UUIDs.START_PRODUCT) == [
        bytes([KEY]) + COMMAND[1:]
    ]


async def test_statistics_request_keeps_pending_product(
    client: Client, fake_clients: list[FakeBleakClient]
) -> None:
    """Test that the periodic statistics request doesn't drop a product."""
    client.send(COMMAND)
    # the latest command wins for the same characteristic only
    client.send(b"\x00" + COMMAND[1:-1] + b"\x01")
    data = await client.read_statistics_data()

    assert data is not None
    assert int.from_bytes(data[0:3], "big") == 1234
    assert fake_clients[0].decrypted_writes(UUIDs.START_PRODUCT) == [
        bytes([KEY]) + COMMAND[1:-1] + b"\x01"
    ]
    assert fake_clients[0].decrypted_writes(UUIDs.STATS_COMMAND) == [
        bytes([0x2A, 0x00, 0x01, 0xFF, 0xFF])
    ]


async def test_expired_command_is_dropped(
    client: Client, fake_clients: list[FakeBleakClient]
) -> None:
    """Test that an old command isn't sent when the machine shows up later."""
    with patch.object(client_module, "COMMAND_TIME", -1):
        client.send(COMMAND)
    await wait_for(lambda: fake_clients and fake_clients[0].writes)

    assert not fake_clients[0].decrypted_writes(UUIDs.START_PRODUCT)


async def test_command_is_sent_again_after_failed_write(
    client: Client, fake_clients: list[FakeBleakClient]
) -> None:
    """Test that a command survives a connection which breaks while sending."""
    with patch.object(client_module, "RECONNECT_INTERVAL", 0):
        client.ping()
        await wait_for(lambda: fake_clients and fake_clients[0].writes)

        fake_clients[0].fail_writes = True
        client.send(COMMAND)
        await wait_for(lambda: len(fake_clients) == 2 and fake_clients[1].writes)

    assert not fake_clients[0].decrypted_writes(UUIDs.START_PRODUCT)
    assert len(fake_clients[1].decrypted_writes(UUIDs.START_PRODUCT)) == 1


async def test_reconnect_on_connection_lost(
    client: Client, fake_clients: list[FakeBleakClient], states: list[bool]
) -> None:
    """Test that a dropped connection is established again."""
    with patch.object(client_module, "RECONNECT_INTERVAL", 0):
        client.ping()
        await wait_for(lambda: fake_clients and fake_clients[0].writes)

        fake_clients[0].drop()
        await wait_for(lambda: len(fake_clients) == 2 and fake_clients[1].writes)

    assert states == [True, False, True]
    assert client.client is fake_clients[1]


async def test_heartbeat_error_keeps_connection(
    client: Client, fake_clients: list[FakeBleakClient], states: list[bool]
) -> None:
    """Test that a failed heartbeat is tolerated while the link is up."""
    with patch.object(client_module, "HEARTBEAT_INTERVAL", 0.01):
        client.ping()
        await wait_for(lambda: fake_clients and fake_clients[0].writes)
        fake_clients[0].fail_writes = True
        await asyncio.sleep(0.05)
        fake_clients[0].fail_writes = False
        writes = len(fake_clients[0].writes)
        await wait_for(lambda: len(fake_clients[0].writes) > writes)

    assert states == [True]
    assert len(fake_clients) == 1


async def test_connection_errors_are_retried(
    client: Client, states: list[bool]
) -> None:
    """Test that the connection is retried while it is requested."""
    attempts = 0

    async def establish_connection(*args, **kwargs) -> FakeBleakClient:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError
        if attempts == 2:
            raise BleakError("Device not found")
        if attempts == 3:
            raise RuntimeError("Unexpected")
        return FakeBleakClient()

    with (
        patch.object(client_module, "establish_connection", establish_connection),
        patch.object(client_module, "RECONNECT_INTERVAL", 0),
    ):
        client.ping()
        await wait_for(lambda: client.client is not None)

    assert attempts == 4
    assert states == [True]


async def test_read_without_connection(client: Client) -> None:
    """Test reading while the machine is unreachable."""
    with (
        patch.object(client_module, "establish_connection", side_effect=TimeoutError),
        patch.object(client_module, "CONNECT_TIMEOUT", 0.01),
    ):
        assert await client.read_statistics_data() is None
        assert await client.read_machine_status() is None
        assert await client.read(UUIDs.MACHINE_STATUS) is None


async def test_statistics_not_ready(
    client: Client, fake_clients: list[FakeBleakClient]
) -> None:
    """Test that the client gives up if the statistics never get ready."""
    client.ping()
    await wait_for(lambda: bool(fake_clients))
    fake_clients[0].reads[UUIDs.STATS_COMMAND] = bytes([0x00, 225])

    with patch.object(client_module.asyncio, "sleep", return_value=None):
        assert await client.read_statistics_data(retries=3) is None


async def test_stop_while_connecting(client: Client, states: list[bool]) -> None:
    """Test that the client can be stopped during a connection attempt."""
    started = asyncio.Event()

    async def establish_connection(*args, **kwargs) -> FakeBleakClient:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError

    with patch.object(client_module, "establish_connection", establish_connection):
        client.ping()
        await started.wait()
        await client.stop()

    assert client.ping_task is None
    assert states == []

    # a stopped client ignores requests
    client.ping()
    client.send(COMMAND)
    assert client.ping_task is None
    assert await client.read_machine_status() is None


async def test_stop_disconnects(
    client: Client, fake_clients: list[FakeBleakClient], states: list[bool]
) -> None:
    """Test that stopping the client closes the connection."""
    client.ping()
    await wait_for(lambda: fake_clients and fake_clients[0].writes)

    await client.stop()

    assert fake_clients[0].disconnects == 1
    assert states == [True, False]
    assert client.client is None
