"""Tests for setting up the EPH Controls Ember integration."""

from unittest.mock import MagicMock, patch

from pyephember2.pyephember2 import EphEmberError
import pytest
from pytest_homeassistant.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test the config entry loads and unloads."""
    assert init_integration.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert init_integration.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize(
    ("error", "state"),
    [
        (EphEmberError("Host is unreachable"), ConfigEntryState.SETUP_RETRY),
        (RuntimeError("Unable to login."), ConfigEntryState.SETUP_ERROR),
    ],
)
async def test_login_errors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    error: Exception,
    state: ConfigEntryState,
) -> None:
    """Test setup retries when offline and stops on rejected credentials."""
    mock_config_entry.add_to_hass(hass)
    with patch("homeassistant.components.ephember.EphEmber", side_effect=error):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is state


async def test_get_zones_error(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_ember: MagicMock
) -> None:
    """Test setup retries when the zones cannot be fetched."""
    mock_ember.get_zones.side_effect = EphEmberError("500 response code")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_live_updates_stop_on_unload(
    hass: HomeAssistant, mock_ember: MagicMock, init_integration: MockConfigEntry
) -> None:
    """Test live updates start with the entry and stop when it is unloaded."""
    mock_ember.start_listening.assert_called_once()

    await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    mock_ember.stop_listening.assert_called_once()


async def test_live_updates_stop_with_home_assistant(
    hass: HomeAssistant, mock_ember: MagicMock, init_integration: MockConfigEntry
) -> None:
    """Test the live update connection is closed when Home Assistant stops."""
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    mock_ember.stop_listening.assert_called_once()


async def test_live_updates_unavailable(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_ember: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test the integration still loads, polling only, without live updates."""
    mock_ember.start_listening.side_effect = EphEmberError("Network unreachable")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert "No live updates from EPH Ember, polling only" in caplog.text


async def test_rejected_password_starts_reauth(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test a rejected password asks the user for the new one."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "homeassistant.components.ephember.EphEmber",
        side_effect=RuntimeError("Unable to login."),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH
    assert flows[0]["context"]["entry_id"] == mock_config_entry.entry_id


async def test_local_setup_and_unload(
    hass: HomeAssistant, init_local_integration: MockConfigEntry
) -> None:
    """Test a local config entry loads and closes the broker on unload."""
    assert init_local_integration.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(init_local_integration.entry_id)
    await hass.async_block_till_done()
    assert init_local_integration.state is ConfigEntryState.NOT_LOADED


async def test_local_setup_no_zones_yet(
    hass: HomeAssistant,
    mock_local_config_entry: MockConfigEntry,
    mock_ember_local: MagicMock,
) -> None:
    """Test local setup retries until the gateway's zones arrive."""
    mock_ember_local.get_zones.return_value = [{"gatewayid": "gw", "zones": []}]
    mock_local_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_local_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_local_config_entry.state is ConfigEntryState.SETUP_RETRY
    mock_ember_local.close.assert_called_once()


async def test_local_cannot_connect(
    hass: HomeAssistant, mock_local_config_entry: MockConfigEntry
) -> None:
    """Test local setup retries when the broker is unreachable."""
    mock_local_config_entry.add_to_hass(hass)
    with patch(
        "homeassistant.components.ephember.EphEmberLocal",
        side_effect=OSError("refused"),
    ):
        await hass.config_entries.async_setup(mock_local_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_local_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_local_get_zones_error(
    hass: HomeAssistant,
    mock_local_config_entry: MockConfigEntry,
    mock_ember_local: MagicMock,
) -> None:
    """Test local setup retries and closes the broker if zones can't be read."""
    mock_ember_local.get_zones.side_effect = EphEmberError("500 response code")
    mock_local_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_local_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_local_config_entry.state is ConfigEntryState.SETUP_RETRY
    mock_ember_local.close.assert_called_once()
