"""The EPH Controls Ember integration."""

from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from pyephember2.pyephember2 import EphEmber, EphEmberError, EphEmberLocal

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.dispatcher import dispatcher_send

from .config_flow import _local_broker
from .const import CONF_LOCAL_HOST, LOGGER, PLATFORMS, signal_zone_update


@dataclass
class EphEmberData:
    """Ember client and the homes (with their zones) found at setup."""

    ember: EphEmber
    homes: list[dict[str, Any]]


type EphEmberConfigEntry = ConfigEntry[EphEmberData]


def _connect_cloud(entry: EphEmberConfigEntry) -> EphEmber:
    """Log in to the EPH Ember cloud."""
    try:
        return EphEmber(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    except EphEmberError as err:
        raise ConfigEntryNotReady(f"Cannot connect to EPH Ember: {err}") from err
    except RuntimeError as err:
        raise ConfigEntryAuthFailed("Invalid username or password") from err


def _connect_local(hass: HomeAssistant, entry: EphEmberConfigEntry) -> EphEmberLocal:
    """Connect to the local broker the gateway is redirected to; no cloud."""
    try:
        return EphEmberLocal(
            _local_broker(entry.data), tz=ZoneInfo(hass.config.time_zone)
        )
    except (RuntimeError, OSError, ValueError) as err:
        raise ConfigEntryNotReady(f"Cannot connect to the local broker: {err}") from err


async def async_setup_entry(hass: HomeAssistant, entry: EphEmberConfigEntry) -> None:
    """Set up EPH Controls Ember from a config entry."""
    local = CONF_LOCAL_HOST in entry.data
    if local:
        ember = await hass.async_add_executor_job(_connect_local, hass, entry)
    else:
        ember = await hass.async_add_executor_job(_connect_cloud, entry)

    try:
        homes = await hass.async_add_executor_job(ember.get_zones)
    except RuntimeError as err:
        if local:
            await hass.async_add_executor_job(ember.close)
        raise ConfigEntryNotReady(f"Cannot get zones from EPH Ember: {err}") from err

    if local and not any(home["zones"] for home in homes):
        await hass.async_add_executor_job(ember.close)
        raise ConfigEntryNotReady("No EPH Ember zones on the local broker yet")

    entry.runtime_data = EphEmberData(ember, homes)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    def zone_updated(zone: dict[str, Any]) -> None:
        """Pass a live update from the listener thread to the zone's entity."""
        dispatcher_send(hass, signal_zone_update(entry.entry_id, zone["zoneid"]), zone)

    try:
        await hass.async_add_executor_job(ember.start_listening, zone_updated)
    except RuntimeError as err:
        LOGGER.warning("No live updates from EPH Ember, polling only: %s", err)

    async def stop(_: Event | None = None) -> None:
        await hass.async_add_executor_job(ember.stop_listening)
        if local:
            await hass.async_add_executor_job(ember.close)

    entry.async_on_unload(stop)
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop))


async def async_unload_entry(hass: HomeAssistant, entry: EphEmberConfigEntry) -> None:
    """Unload a config entry."""
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
