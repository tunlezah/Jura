"""JURA coffee machine model: products, settings, statistics and alerts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import logging
from pathlib import Path
from typing import Any, TypedDict
from zipfile import ZipFile

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
import xmltodict

from .client import Client, TaskFactory

_LOGGER = logging.getLogger(__name__)

SELECTS = [
    "product",  # 1
    "grinder_ratio",  # 2
    "coffee_strength",  # 3
    "temperature",  # 7
]

NUMBERS = [
    "water_amount",  # 4
    "milk_amount",  # 5
    "milk_foam_amount",  # 6
    "bypass",  # 10
    "milk_break",  # 11
]

# Bluetooth company identifier used in the advertisements of the BlueFrog dongle
MANUFACTURER_ID = 171
# Key (1 byte), BlueFrog version (3 bytes) and article number (2 bytes)
MACHINE_DATA_LEN = 6


class Attribute(TypedDict, total=False):
    """State of a product setting."""

    options: list[str]
    default: str | None

    min: int
    max: int
    step: int
    value: int

    is_on: bool
    extra: dict


class Machine(TypedDict):
    """Machine description from the JURA resources."""

    model: str
    products: list[dict[str, Any]]
    alerts: dict[int, str]
    key: int


class Device:
    """A JURA coffee machine."""

    def __init__(
        self,
        name: str,
        model: str,
        products: list[dict[str, Any]],
        alerts: dict[int, str],
        key: int,
        device: BLEDevice,
        create_task: TaskFactory | None = None,
    ) -> None:
        """Initialize the machine."""
        self.name = name
        self.model = model
        self.products = products
        self.alerts = alerts

        self.client = Client(device, self.set_connected, key, create_task)

        self.connected = False
        self.conn_info: dict[str, Any] = {"mac": device.address}

        self.options = get_options(self.products)

        self.product: dict[str, Any] | None = None
        self.values: dict[str, int] = {}
        self.updates_connect: list[Callable[[], None]] = []
        self.updates_product: list[Callable[[], None]] = []
        self.statistics: dict[str, Any] = {"total_products": None, "product_counts": {}}
        # None until the status was read from the machine for the first time
        self.active_alerts: dict[int, str] | None = None

    @property
    def mac(self) -> str:
        """Return the Bluetooth address of the machine."""
        return self.client.device.address

    def register_update(
        self, attr: str, handler: Callable[[], None]
    ) -> Callable[[], None]:
        """Register an update handler, returns a function to remove it."""
        if attr == "product":
            return lambda: None

        handlers = (
            self.updates_connect if attr == "connection" else self.updates_product
        )
        handlers.append(handler)

        def remove() -> None:
            if handler in handlers:
                handlers.remove(handler)

        return remove

    def update_ble(
        self, advertisement: AdvertisementData, device: BLEDevice | None = None
    ) -> None:
        """Process a new advertisement of the machine."""
        if device is not None:
            # the best path to the machine may change (adapter or proxy)
            self.client.device = device

        if model_id_from_advertisement(
            adv := advertisement.manufacturer_data.get(MANUFACTURER_ID, b"")
        ):
            # first byte is the encryption key
            self.client.key = adv[0]

        self.conn_info["last_seen"] = datetime.now(UTC)
        self.conn_info["rssi"] = advertisement.rssi

        self._dispatch(self.updates_connect)

    def set_connected(self, connected: bool) -> None:
        """Process a connection state change."""
        if self.connected == connected:
            return

        self.connected = connected

        self._dispatch(self.updates_connect)

    @staticmethod
    def _dispatch(handlers: list[Callable[[], None]]) -> None:
        for handler in list(handlers):
            try:
                handler()
            except Exception:
                _LOGGER.exception("Error in update handler")

    def selects(self) -> list[str]:
        """Return the select settings supported by the machine."""
        products = str(self.products).lower()
        return [k for k in SELECTS if k in products]

    def numbers(self) -> list[str]:
        """Return the number settings supported by the machine."""
        products = str(self.products).lower()
        return [k for k in NUMBERS if k in products]

    def attribute(self, attr: str) -> Attribute:
        """Return the state of a setting."""
        if attr == "connection":
            return Attribute(is_on=self.connected, extra=self.conn_info)

        if attr == "product":
            return Attribute(
                options=[
                    i["@Name"] for i in self.products if i.get("@Active") != "false"
                ],
                default=self.product["@Name"] if self.product else None,
            )

        attribute = self.product and self.product.get(attr.upper())
        if not attribute:
            return {"options": self.options[attr]} if attr in self.options else {}

        if "@Value" in attribute:
            return Attribute(
                min=int(attribute["@Min"]),
                max=int(attribute["@Max"]),
                step=int(attribute["@Step"]),
                value=self.values.get(attr, int(attribute["@Value"])),
            )

        value = self.values.get(attr, int(attribute["@Default"], 16))
        return Attribute(
            options=[i["@Name"] for i in attribute["ITEM"]],
            default=next(
                (
                    i["@Name"]
                    for i in attribute["ITEM"]
                    if int(i["@Value"], 16) == value
                ),
                None,
            ),
        )

    def select_option(self, attr: str, option: str) -> None:
        """Select an option of a setting, raise ValueError if it is unknown."""
        if attr == "product":
            self.select_product(option)
            return

        attribute = self.product and self.product.get(attr.upper())
        if not attribute:
            raise ValueError(f"{attr} is not supported by the selected product")

        for item in attribute["ITEM"]:
            if item["@Name"] == option:
                self.set_value(attr, int(item["@Value"], 16))
                return

        raise ValueError(f"Unknown {attr} option: {option}")

    def set_value(self, attr: str, value: int) -> None:
        """Set the value of a setting of the selected product."""
        if not self.product:
            raise ValueError("No product selected")

        self.client.ping()

        self.values[attr] = value

    def select_product(self, product: str) -> None:
        """Select a product, raise ValueError if it is unknown."""
        for item in self.products:
            if item["@Name"] == product:
                break
        else:
            raise ValueError(f"Unknown product: {product}")

        self.client.ping()

        self.product = item
        self.values = {}

        # dispatch to all listeners
        self._dispatch(self.updates_product)

    def start_product(self) -> None:
        """Make the selected product."""
        if self.product:
            self.client.send(self.command())

    def command(self) -> bytes:
        """Build the command to make the selected product."""
        if not self.product:
            raise ValueError("No product selected")

        data = bytearray(18)

        # set product
        data[1] = int(self.product["@Code"], 16)

        for attr in SELECTS + NUMBERS:
            attribute = self.product.get(attr.upper())
            if not attribute:
                continue

            if attr in self.values:
                # set user's value
                value = self.values[attr]
            elif "@Value" in attribute:
                # set default int value
                value = int(attribute["@Value"])
            else:
                # set default list value
                value = int(attribute["@Default"], 16)

            if step := int(attribute.get("@Step", 0)):
                value = int(value / step)

            pos = int(attribute["@Argument"][1:])
            data[pos] = value

        # additional data (some unknown)
        # data[0] = self.client.key
        # data[9] = 1
        # data[16] = 6
        # need to be set or the machine will go into a half broken state
        data[17] = self.client.key

        return data

    async def read_statistics(self) -> dict[str, Any]:
        """Read statistics from the machine."""
        # Read statistics data from client
        decrypted_data = await self.client.read_statistics_data()
        if not decrypted_data:
            _LOGGER.debug(
                "Failed to read statistics data, returning existing statistics"
            )
            return self.statistics

        # Convert all 3-byte chunks to integers
        product_counts_array = []
        for i in range(0, len(decrypted_data) - 2, 3):
            count = int.from_bytes(decrypted_data[i : i + 3], "big")
            if count == 0xFFFF:  # means 0 it seems
                count = 0
            product_counts_array.append(count)

        # get total_count from first 3 bytes if available
        total_count = product_counts_array[0] if product_counts_array else None
        _LOGGER.debug("Total coffee count from data: %s", total_count)

        # remove aberrant values if any
        if not total_count or total_count > 1000000:
            _LOGGER.debug(
                "total 0 or too high, something's wrong, returning existing statistics"
            )
            return self.statistics

        # get the names associated to the products counts
        codes = {int(p["@Code"], 16): p["@Name"] for p in reversed(self.products)}
        product_counts = {}
        for i, count in enumerate(product_counts_array):
            if i == 0:  # Skip the total
                continue

            if name := codes.get(i):
                product_counts[name] = count
                _LOGGER.debug("Stat entry: Position %s = %s -> %s", i, count, name)
            else:
                _LOGGER.debug("No product found for code %s with count %s", i, count)

        # Save the statistics
        self.statistics = {
            "total_products": total_count,
            "product_counts": product_counts,
        }

        return self.statistics

    async def read_alerts(self) -> dict[int, str] | None:
        """Read alerts from the machine."""
        # Read machine status data from client
        data = await self.client.read_machine_status()
        if data is None:
            _LOGGER.debug("Failed to read machine status data")
            return self.active_alerts

        # Process alert bits
        alerts = {}
        for i in range((len(data) - 1) * 8):
            offset_abs = (i >> 3) + 1
            offset_byte = 7 - (i & 0b111)
            if (data[offset_abs] >> offset_byte) & 0b1:
                alerts[i] = alert = self.alerts.get(i, f"unknown alert {i}")
                _LOGGER.debug("Alert active. Alert bit: %s - %s", i, alert)

        # Save the alerts
        self.active_alerts = alerts

        return self.active_alerts


class EmptyModel(Exception):
    """The advertisement doesn't contain a model."""


class UnsupportedModel(Exception):
    """The model is not known."""


def model_id_from_advertisement(adv: bytes) -> int:
    """Return the model (article number) from the manufacturer data, 0 if unknown."""
    if len(adv) < MACHINE_DATA_LEN:
        return 0
    return int.from_bytes(adv[4:6], "little")


def get_machine(adv: bytes) -> Machine:
    """Load the machine description for the manufacturer data.

    This reads files, so it must not be called from the event loop.
    """
    model_id = model_id_from_advertisement(adv)
    if model_id == 0:
        raise EmptyModel

    path = Path(__file__).parent / "resources.zip"
    with ZipFile(path) as f:
        prefix = f"{model_id};".encode()
        with f.open("JOE_MACHINES.TXT") as txt:
            line = next((i for i in txt if i.startswith(prefix)), None)
        if line is None:
            raise UnsupportedModel(model_id)

        items = line.decode().split(";")
        if len(items) < 3:
            raise UnsupportedModel(model_id)

        dirname = f"documents/xml/{items[2].strip().upper()}/"
        filename = next(
            (
                i.filename
                for i in f.filelist
                if i.filename.startswith(dirname) and i.filename.endswith(".xml")
            ),
            None,
        )
        if filename is None:
            raise UnsupportedModel(model_id)

        with f.open(filename) as xml:
            raw = xmltodict.parse(xml.read(), force_list=("PRODUCT", "ITEM", "ALERT"))

    try:
        products = raw["JOE"]["PRODUCTS"]["PRODUCT"]
    except (KeyError, TypeError) as e:
        raise UnsupportedModel(model_id) from e

    try:
        alerts = {int(i["@Bit"]): i["@Name"] for i in raw["JOE"]["ALERTS"]["ALERT"]}
    except KeyError, TypeError, ValueError:
        alerts = {}

    # First byte is the encryption key
    return Machine(model=items[1], products=products, alerts=alerts, key=adv[0])


def get_options(products: list[dict]) -> dict[str, list]:
    """Return all the options of the select settings over all the products."""
    return {
        attr: list(
            {
                option["@Name"]: None
                for product in products
                for option in product.get(attr.upper(), {}).get("ITEM", [])
            }.keys()  # unique keys with save order
        )
        for attr in SELECTS
    }
