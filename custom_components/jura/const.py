"""Constants for the JURA Coffee Machines integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "jura"

# Name of the Bluetooth dongle (JURA Smart Connect)
LOCAL_NAME: Final = "TT214H BlueFrog"
DEFAULT_NAME: Final = "Jura"

# Key, dongle version and article number from the advertisement (hex), kept in
# the config entry so the machine can be set up before it is seen again
CONF_MACHINE_DATA: Final = "machine_data"

# How often the statistics and the alerts are read from the machine
UPDATE_INTERVAL: Final = timedelta(seconds=60)
