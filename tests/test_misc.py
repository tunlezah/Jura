"""Test the machine model and the encryption."""

from __future__ import annotations

from unittest.mock import patch

from bleak.backends.device import BLEDevice
import pytest

from custom_components.jura.core.device import (
    Device,
    EmptyModel,
    UnsupportedModel,
    get_machine,
)
from custom_components.jura.core.encryption import encdec


@pytest.fixture(autouse=True)
def socket_enabled(socket_enabled: None) -> None:
    """These tests don't need Home Assistant."""


def make_device(adv: bytes) -> Device:
    """Create the machine for the manufacturer data."""
    machine = get_machine(adv)
    ble = BLEDevice("AA:BB:CC:DD:EE:FF", None, None)
    device = Device(
        "Jura",
        machine["model"],
        machine["products"],
        machine["alerts"],
        machine["key"],
        ble,
    )
    # no connection in these tests
    device.client.ping = lambda *args: None
    return device


def test_device_e8():
    device = make_device(b"*\x05\x08\x03\xfb;")
    assert device.model == "E8 (EB)"

    # Check GUI elements list
    assert device.selects() == ["product", "coffee_strength", "temperature"]
    assert device.numbers() == [
        "water_amount",
        "milk_foam_amount",
        "bypass",
        "milk_break",
    ]

    # Check products list
    attr = device.attribute("product")
    assert attr == {
        "default": None,
        "options": [
            "Espresso",
            "Coffee",
            "Cappuccino",
            "Espresso Macchiato",
            "Latte Macchiato",
            "Milk Foam",
            "Hotwater Portion(normal)",
            "Espresso Doppio",
            "2 Espressi",
            "2 Coffee",
            "Cafe Barista",
            "Barista Lungo",
            "1 Flat White",
            "Cortado",
        ],
    }

    # Select product
    device.select_option("product", "Cafe Barista")

    cmd = device.command()
    assert cmd.hex() == "00280006120000010000090000000000002a"

    attr = device.attribute("coffee_strength")
    assert attr == {
        "options": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
        "default": "6",
    }

    device.select_option("coffee_strength", "10")

    attr = device.attribute("water_amount")
    assert attr == {"max": 240, "min": 25, "step": 5, "value": 90}

    device.set_value("water_amount", 50)

    cmd = device.command()
    assert cmd.hex() == "0028000a0a0000010000090000000000002a"

    # Select product
    device.select_option("product", "Cappuccino")
    cmd = device.command()
    assert cmd.hex() == "000400080c000e010000000000000000002a"


def test_device_d4():
    device = make_device(b"*\x05\x08\x03u;")
    assert device.model == "D4"

    # Check GUI elements list
    assert device.selects() == ["product", "coffee_strength", "temperature"]
    assert device.numbers() == ["water_amount", "bypass"]

    # Check products list
    attr = device.attribute("product")
    assert attr == {
        "default": None,
        "options": [
            "Espresso",
            "Coffee",
            "2 Espressi",
            "2 Coffee",
            "Ristretto (only JOE)",
            "Cafe Barista (only JOE)",
            "Barista Lungo (only JOE)",
            "Espresso Doppio (only JOE)",
            "2 Ristretti (only JOE)",
        ],
    }


def test_device_giga5():
    # https://github.com/AlexxIT/Jura/issues/10
    device = make_device(b"*\x05\x08\x03=5")
    assert device.model == "GIGA 5"

    assert device.selects() == [
        "product",
        "grinder_ratio",
        "coffee_strength",
        "temperature",
    ]
    assert device.numbers() == ["water_amount", "milk_amount", "milk_foam_amount"]

    # Check products list
    attr = device.attribute("product")
    assert attr == {
        "default": None,
        "options": [
            "Ristretto",
            "Espresso",
            "Coffee",
            "Cappuccino",
            "Milkcoffee",
            "Espresso Macchiato",
            "Latte Macchiato",
            "Milk Foam",
            "Milk Portion",
            "Pot",
            "Hotwater Portion",
            "2 Ristretti",
            "2 Espressi",
            "2 Coffee",
            "2 Cappuccini",
            "2 Milkcoffee",
            "2 Espresso Macchiati",
            "2 Latte Macchiati",
            "2 Milk Foam",
            "2 Portion Milk",
        ],
    }

    # Select product
    device.select_option("product", "Coffee")

    cmd = device.command()
    assert cmd.hex() == "00030203140000010000000000000000002a"

    attr = device.attribute("coffee_strength")
    assert attr == {
        "default": "Normal",
        "options": ["XMild", "Mild", "Normal", "Strong", "XStrong"],
    }

    attr = device.attribute("grinder_ratio")
    assert attr == {
        "default": "50_50",
        "options": ["100_0", "75_25", "50_50", "25_75", "0_100"],
    }

    attr = device.attribute("water_amount")
    assert attr == {"max": 240, "min": 25, "step": 5, "value": 100}

    attr = device.attribute("temperature")
    assert attr == {"default": "Normal", "options": ["Low", "Normal", "High"]}


def test_device_j8():
    # https://github.com/AlexxIT/Jura/issues/27
    device = make_device(b"*\x05\x08\x03\xc9<")
    assert device.model == "J8 twin (EA)"

    # Check GUI elements list
    assert device.selects() == [
        "product",
        "grinder_ratio",
        "coffee_strength",
        "temperature",
    ]
    assert device.numbers() == [
        "water_amount",
        "milk_amount",
        "milk_foam_amount",
        "bypass",
        "milk_break",
    ]

    # Check products list
    attr = device.attribute("product")
    assert attr == {
        "default": None,
        "options": [
            "Espresso",
            "Coffee",
            "Cortado",
            "Cafe Barista / Americano",
            "Barista Lungo",
            "Cappuccino",
            "Latte Macchiato",
            "Espresso Macchiato",
            "Flat White",
            "Milkcoffee",
            "Espresso Doppio",
            "Sweet Latte",
            "Milk",
            "Milk Foam",
            "Hotwater Portion",
            "Hotwater Portion(Green tea)",
        ],
    }


def test_device_x8c():
    # https://github.com/AlexxIT/Jura/issues/33
    adv = bytes.fromhex("2a0508039c35921532006d33793201000000000000000000000000")
    device = make_device(adv)
    assert device.model == "GIGA X8c Professional"


def test_coffee_strength():
    device = make_device(b"*\x05\x08\x03\xfb;")

    # all the options of the machine are known before a product is selected
    assert device.attribute("coffee_strength") == {
        "options": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]
    }

    device.select_option("product", "Cafe Barista")

    assert device.attribute("coffee_strength") == {
        "default": "6",
        "options": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
    }

    # the selected option is kept until another product is selected
    device.select_option("coffee_strength", "10")
    assert device.attribute("coffee_strength")["default"] == "10"
    device.set_value("water_amount", 50)
    assert device.attribute("water_amount")["value"] == 50

    device.select_option("product", "Espresso")
    assert device.attribute("coffee_strength")["default"] == "8"
    assert device.attribute("water_amount")["value"] == 45


def test_default_is_not_an_option():
    # the default temperature of this product isn't one of its options
    device = make_device(b"*\x05\x08\x03" + (14000).to_bytes(2, "little"))
    assert device.model.startswith("X6")

    device.select_option("product", "2 Ristretti")

    assert device.attribute("temperature") == {
        "default": None,
        "options": ["Normal", "High"],
    }
    assert len(device.command()) == 18


def test_invalid_selection():
    device = make_device(b"*\x05\x08\x03\xfb;")

    with pytest.raises(ValueError):
        device.select_option("product", "Tea")
    with pytest.raises(ValueError):
        device.set_value("water_amount", 50)
    with pytest.raises(ValueError):
        device.select_option("coffee_strength", "10")
    with pytest.raises(ValueError):
        device.command()

    device.select_option("product", "Cafe Barista")
    with pytest.raises(ValueError):
        device.select_option("coffee_strength", "XStrong")
    # this product has no milk
    with pytest.raises(ValueError):
        device.select_option("grinder_ratio", "50_50")


def test_update_handlers():
    device = make_device(b"*\x05\x08\x03\xfb;")
    calls = []

    remove_connect = device.register_update("connection", lambda: calls.append("c"))
    remove_product = device.register_update("make", lambda: calls.append("p"))
    device.register_update("make", lambda: 1 / 0)

    device.set_connected(True)
    device.set_connected(True)
    assert calls == ["c"]

    # a failing handler doesn't stop the others
    device.select_option("product", "Espresso")
    assert calls == ["c", "p"]

    remove_connect()
    remove_product()
    remove_product()
    device.set_connected(False)
    device.select_option("product", "Coffee")
    assert calls == ["c", "p"]


def test_get_machine_errors():
    with pytest.raises(EmptyModel):
        get_machine(b"*\x05\x08\x03\x00\x00")
    with pytest.raises(EmptyModel):
        get_machine(b"")
    with pytest.raises(EmptyModel):
        get_machine(b"*\x05\x08")

    # 1358 and 20 are the beginning of other lines of the machines list
    for model_id in (1, 20, 1358, 65535):
        with pytest.raises(UnsupportedModel):
            get_machine(b"*\x05\x08\x03" + model_id.to_bytes(2, "little"))


def test_all_machines():
    """Test that every machine of the resources can be loaded."""
    from pathlib import Path
    from zipfile import ZipFile

    import custom_components.jura.core.device as device_module

    path = Path(device_module.__file__).parent / "resources.zip"
    with ZipFile(path) as f:
        lines = f.read("JOE_MACHINES.TXT").decode().splitlines()[1:]

    model_ids = [int(line.split(";")[0]) for line in lines if line.strip()]
    assert len(model_ids) > 500

    for model_id in model_ids:
        device = make_device(b"*\x05\x08\x03" + model_id.to_bytes(2, "little"))
        assert device.model
        assert device.products
        assert "product" in device.selects()

        # the command of every product can be built
        for product in device.attribute("product")["options"]:
            device.select_option("product", product)
            assert len(device.command()) == 18
            for attr in device.selects()[1:]:
                attribute = device.attribute(attr)
                if "default" in attribute:
                    # the default of some products (X6) isn't an option
                    assert attribute["default"] in [None, *attribute["options"]]
            for attr in device.numbers():
                attribute = device.attribute(attr)
                if "value" in attribute:
                    assert attribute["min"] <= attribute["value"] <= attribute["max"]


async def test_read_statistics():
    device = make_device(b"*\x05\x08\x03\xfb;")

    data = bytearray()
    for count in (1234, 0xFFFF, 200, 300):
        data += count.to_bytes(3, "big")
    # an incomplete last value is ignored
    data += b"\x01"

    with patch.object(device.client, "read_statistics_data", return_value=bytes(data)):
        assert await device.read_statistics() == {
            "total_products": 1234,
            "product_counts": {"Espresso": 200, "Coffee": 300},
        }

    # empty, zero or implausible data keeps the last statistics
    for data in (None, b"", b"\x00\x00\x00", b"\xff\xff\xff", b"\x01"):
        with patch.object(device.client, "read_statistics_data", return_value=data):
            assert (await device.read_statistics())["total_products"] == 1234


async def test_read_alerts():
    device = make_device(b"*\x05\x08\x03\xfb;")
    assert device.active_alerts is None

    with patch.object(device.client, "read_machine_status", return_value=None):
        assert await device.read_alerts() is None

    # no bottom tray, see test_status_key2A
    data = bytes.fromhex("2a88000000040008000000000000000000000006")
    with patch.object(device.client, "read_machine_status", return_value=data):
        alerts = await device.read_alerts()
    assert alerts[0] == "insert tray"
    assert alerts[4] == "insert coffee bin"
    assert alerts[37] == "active RF filter"
    assert alerts[52] == "unknown alert 52"

    # the last alerts are kept while the machine can't be read
    with patch.object(device.client, "read_machine_status", return_value=None):
        assert await device.read_alerts() == alerts


def test_encdec():
    # mobile: 2a280006120000010001090000000000062a
    # python: 002800061200000100000900000000000000
    b = bytes.fromhex("77c23dd05e81d3dba32bf898a4a3faab45fd")
    b = encdec(b, 0x2A)
    assert b.hex() == "2a280006120000010001090000000000062a"

    # mobile: 2a0400080c000e010001000000000000062a
    # python: 000400080c000e0100000000000000000000
    b = bytes.fromhex("77ea3dd38981dadba32bfa98a4a3faab45fd")
    b = encdec(b, 0x2A)
    assert b.hex() == "2a0400080c000e010001000000000000062a"


def test_status_key2A():
    b = bytes.fromhex("77E13ED68882D3D7A323FA98A4A3FAAB4756A629")
    b = encdec(b, 0x2A)
    assert b.hex() == "2a00040000040008000000000000000000000007"

    # no bottom tray
    b = bytes.fromhex("77D23DD68882D3D7A323FA98A4A3FAAB4756A625")
    b = encdec(b, 0x2A)
    assert b.hex() == "2a88000000040008000000000000000000000006"

    # no water tray
    b = bytes.fromhex("77113DD68882D3D7A323FA98A4A3FAAB4756A625")
    b = encdec(b, 0x2A)
    assert b.hex() == "2a40000000040008000000000000000000000006"

    # no water tray + remove water from bottom tray
    b = bytes.fromhex("77913DD6888BD3D7A323FA98A4A3FAAB4756A625")
    b = encdec(b, 0x2A)
    assert b.hex() == "2a500000000c0008000000000000000000000006"


def test_status_key00():
    b = bytes.fromhex("14444CC623152D9ABFE772ED1B3F65136B888DDC")
    b = encdec(b, 0)
    assert b.hex() == "0000000000000000000000000000000000000004"

    # coffee trash
    b = bytes.fromhex("14A44CC623153D94BFE772ED1B3F65136B888DD2")
    b = encdec(b, 0)
    assert b.hex() == "0020000000004008000000000000000000000006"

    # zero water
    b = bytes.fromhex("14044CC623153D94BFE772ED1B3F65136B888DDC")
    b = encdec(b, 0)
    assert b.hex() == "0040000000004008000000000000000000000004"

    # cleaning milk and usual cleaning
    b = bytes.fromhex("144448C623753D94BFE772ED1B3F65136B888DDC")
    b = encdec(b, 0)
    assert b.hex() == "0000040000204008000000000000000000000004"

    # usual cleaning
    b = bytes.fromhex("144448C623752D94BFE772ED1B3F65136B888DD2")
    b = encdec(b, 0)
    assert b.hex() == "0000040000200008000000000000000000000006"


def test_issue52():
    adv = b"*\x05\x08\x03\xe8;\x11\xad\x04\x001?\x94>\x01\xc0A\xb6(\x00\x00\x00\x00\x00\x00\x00\x00"
    device = make_device(adv)
    assert device.model == "E8 (EB)"
