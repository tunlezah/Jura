"""Bluetooth client for JURA coffee machines (BlueFrog dongle)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
import logging
import time
from typing import Any

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from . import encryption

_LOGGER = logging.getLogger(__name__)

# How long the connection is kept alive after the last request
ACTIVE_TIME = 120
# How long a command stays valid while waiting for the connection
COMMAND_TIME = 15
# Heartbeat interval: 10 is too late, 9 is ok
HEARTBEAT_INTERVAL = 9
# Pause between two connection attempts
RECONNECT_INTERVAL = 1
# How long a reader waits for the connection to come up
CONNECT_TIMEOUT = 20


class UUIDs:
    """BLE characteristic UUIDs."""

    # https://github.com/Jutta-Proto/protocol-bt-cpp?tab=readme-ov-file#bluetooth-characteristics
    # Start product
    START_PRODUCT = "5a401525-ab2e-2548-c435-08c300000710"
    # Heartbeat
    P_MODE = "5a401529-ab2e-2548-c435-08c300000710"
    # Statistics
    STATS_COMMAND = "5a401533-ab2e-2548-c435-08c300000710"
    STATS_DATA = "5A401534-ab2e-2548-c435-08c300000710"
    # Status
    MACHINE_STATUS = "5a401524-ab2e-2548-c435-08c300000710"


type TaskFactory = Callable[[Coroutine[Any, Any, None]], asyncio.Task[None]]


class Client:
    """Keep a connection to the machine open on demand and talk to it.

    The connection is only held while somebody needs it: every request
    extends the active window by ACTIVE_TIME seconds, after which the
    connection is dropped again.
    """

    def __init__(
        self,
        device: BLEDevice,
        callback: Callable[[bool], None] | None = None,
        key: int | None = None,
        create_task: TaskFactory | None = None,
    ) -> None:
        """Initialize the client."""
        self.device = device
        self.callback = callback
        self.key = key
        self.client: BleakClient | None = None

        self._create_task = create_task
        self._stopped = False

        self.ping_task: asyncio.Task[None] | None = None
        self.ping_time: float = 0

        # Pending commands, the latest one wins for each characteristic. A
        # statistics request must never replace a pending "start product".
        self._pending: dict[str, tuple[bytes, float]] = {}

        # Wakes the heartbeat loop before the heartbeat interval elapsed
        self._wake = asyncio.Event()
        self._connected = asyncio.Event()
        # Serialize GATT operations: the ping loop and the readers share one link
        self._gatt_lock = asyncio.Lock()

    def ping(self) -> None:
        """Request the connection and keep it open for ACTIVE_TIME seconds."""
        if self._stopped:
            return

        self.ping_time = time.monotonic() + ACTIVE_TIME

        if self.ping_task is None or self.ping_task.done():
            coro = self._ping_loop()
            if self._create_task is not None:
                self.ping_task = self._create_task(coro)
            else:
                self.ping_task = asyncio.get_running_loop().create_task(coro)

    def ping_cancel(self) -> None:
        """Release the connection."""
        # stop ping time
        self.ping_time = 0

        # cancel ping sleep timer
        self._wake.set()

    def send(self, data: bytes, uuid: str = UUIDs.START_PRODUCT) -> None:
        """Queue a command, it will be sent as soon as the machine is connected."""
        if self._stopped:
            return

        # if send loop active - we change sending data
        self._pending[uuid] = (bytes(data), time.monotonic() + COMMAND_TIME)

        # refresh ping time
        self.ping()

        # cancel ping sleep timer
        self._wake.set()

    async def stop(self) -> None:
        """Drop the connection and stop the ping loop for good."""
        self._stopped = True
        self.ping_time = 0
        self._pending.clear()
        self._wake.set()

        if (task := self.ping_task) is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _set_connected(self, connected: bool) -> None:
        if connected == self._connected.is_set():
            return

        if connected:
            self._connected.set()
        else:
            self._connected.clear()

        if self.callback:
            try:
                self.callback(connected)
            except Exception:
                _LOGGER.exception("Error in connection callback")

    def _on_disconnected(self, _client: BleakClient) -> None:
        """Handle a dropped link, called by bleak."""
        _LOGGER.debug("%s: disconnected", self.device.address)
        # cancel ping sleep timer, so the loop can reconnect at once
        self._wake.set()

    async def _ping_loop(self) -> None:
        try:
            while time.monotonic() < self.ping_time:
                try:
                    self.client = await establish_connection(
                        BleakClient,
                        self.device,
                        self.device.address,
                        disconnected_callback=self._on_disconnected,
                        ble_device_callback=lambda: self.device,
                    )
                    self._set_connected(True)

                    await self._heartbeat_loop(self.client)
                except TimeoutError as e:
                    _LOGGER.debug("ping timeout", exc_info=e)
                except BleakError as e:
                    _LOGGER.debug("ping error", exc_info=e)
                except Exception as e:
                    _LOGGER.warning("ping error", exc_info=e)
                finally:
                    # also runs when the task is cancelled (unload or shutdown)
                    await self._disconnect()

                if time.monotonic() < self.ping_time:
                    await asyncio.sleep(RECONNECT_INTERVAL)
        finally:
            self.ping_task = None

    async def _heartbeat_loop(self, client: BleakClient) -> None:
        while time.monotonic() < self.ping_time:
            if not client.is_connected:
                raise BleakError("Connection lost")

            # clear before the pending commands are checked, so a command
            # queued while we are busy below is never missed
            self._wake.clear()

            for uuid in list(self._pending):
                command = self._pending[uuid]
                data, expires = command
                if time.monotonic() < expires:
                    # if this fails the command is sent again after the
                    # reconnect, as long as it is not expired
                    async with self._gatt_lock:
                        await client.write_gatt_char(
                            uuid, data=encrypt(data, self.key), response=True
                        )
                # keep a newer command queued during the write
                if self._pending.get(uuid) is command:
                    del self._pending[uuid]

            # important dummy write to keep the connection
            # https://github.com/Jutta-Proto/protocol-bt-cpp?tab=readme-ov-file#heartbeat
            heartbeat = [0x00, 0x7F, 0x80]
            try:
                async with self._gatt_lock:
                    await client.write_gatt_char(
                        UUIDs.P_MODE,
                        data=encrypt(heartbeat, self.key),
                        response=True,
                    )
                _LOGGER.debug("heartbeat sent")
            except Exception as e:
                # we log as info as this is expected if the device is off
                _LOGGER.info("heartbeat error", exc_info=e)

            try:
                async with asyncio.timeout(HEARTBEAT_INTERVAL):
                    await self._wake.wait()
            except TimeoutError:
                pass

    async def _disconnect(self) -> None:
        client, self.client = self.client, None

        if client is not None:
            try:
                await client.disconnect()
            except Exception as e:
                _LOGGER.debug("disconnect error", exc_info=e)

        self._set_connected(False)

    async def _wait_connected(self, timeout: float | None = None) -> bool:
        """Wait for the ping loop to bring the connection up."""
        if self.client is None and not self._stopped:
            try:
                async with asyncio.timeout(
                    CONNECT_TIMEOUT if timeout is None else timeout
                ):
                    await self._connected.wait()
            except TimeoutError:
                pass

        return self.client is not None

    async def read(self, uuid: str, decrypt: bool = False) -> bytes | None:
        """Read data from a characteristic."""
        if not (client := self.client):
            _LOGGER.debug("Cannot read: No active client connection")
            return None

        try:
            async with self._gatt_lock:
                data = await client.read_gatt_char(uuid)
        except Exception as e:
            _LOGGER.info("Error reading from characteristic %s", uuid, exc_info=e)
            raise

        if decrypt and self.key is not None:
            return encryption.encdec(list(data), self.key)
        return bytes(data)

    async def read_statistics_data(
        self, timeout: float | None = None, retries: int = 30
    ) -> bytes | None:
        """Read statistics data from the device."""
        _LOGGER.debug("Reading Jura statistics...")

        # Send statistics request command
        # https://github.com/Jutta-Proto/protocol-bt-cpp?tab=readme-ov-file#writing-1
        command_bytes = [0x2A, 0x00, 0x01, 0xFF, 0xFF]
        self.send(bytes(command_bytes), uuid=UUIDs.STATS_COMMAND)

        # Wait for connection
        if not await self._wait_connected(timeout):
            _LOGGER.debug("Failed to establish connection")
            return None

        # Wait for statistics to be ready
        # https://github.com/Jutta-Proto/protocol-bt-cpp?tab=readme-ov-file#reading
        for _ in range(retries):
            status = await self.read(UUIDs.STATS_COMMAND)
            if status is None:
                _LOGGER.debug("Connection lost while waiting for statistics")
                return None
            if len(status) > 1 and status[1] != 225:  # 225 means not ready
                break
            await asyncio.sleep(0.8)
        else:
            _LOGGER.warning("Device not ready for statistics reading")
            return None

        # Read statistics data
        # https://github.com/Jutta-Proto/protocol-bt-cpp?tab=readme-ov-file#statistics-data
        return await self.read(UUIDs.STATS_DATA, decrypt=True)

    async def read_machine_status(self) -> bytes | None:
        """Read machine status from the device."""
        _LOGGER.debug("Reading Jura machine status...")

        # Wait for connection
        self.ping()
        if not await self._wait_connected():
            _LOGGER.debug("Failed to establish connection")
            return None

        data = await self.read(UUIDs.MACHINE_STATUS, decrypt=True)
        if data:
            _LOGGER.debug("Machine status data: %s", data.hex())
            return data

        return None


def encrypt(data: bytes | list[int], key: int) -> bytes:
    """Put the key into the first byte and encrypt the data."""
    data = bytearray(data)
    data[0] = key
    return encryption.encdec(data, key)
