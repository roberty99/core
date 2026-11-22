"""Constants for the EPH Controls Ember integration."""

import logging
from typing import Final

from homeassistant.const import Platform

LOGGER = logging.getLogger(__package__)
DOMAIN: Final = "ephember"
PLATFORMS = [Platform.CLIMATE]


def signal_zone_update(entry_id: str, zone_id: str) -> str:
    """Dispatcher signal sent when a live update for a zone arrives."""
    return f"{DOMAIN}_{entry_id}_{zone_id}_update"


# Local mode: talk to the gateway through an MQTT broker on the network
# (to which it has been redirected) instead of the EPH Ember cloud.
CONF_LOCAL_HOST: Final = "local_host"
CONF_LOCAL_PORT: Final = "local_port"
CONF_LOCAL_USERNAME: Final = "local_username"
CONF_LOCAL_PASSWORD: Final = "local_password"
DEFAULT_LOCAL_PORT: Final = 11883
