"""Config flow for EPH Controls Ember."""

from collections.abc import Mapping
from typing import Any, override

import probatio
from pyephember2.pyephember2 import EphEmber, EphEmberError, EphEmberLocal

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_LOCAL_HOST,
    CONF_LOCAL_PASSWORD,
    CONF_LOCAL_PORT,
    CONF_LOCAL_USERNAME,
    DEFAULT_LOCAL_PORT,
    DOMAIN,
    LOGGER,
)

PASSWORD_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
)
STEP_USER_DATA_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="email")
        ),
        probatio.Required(probatio.Secret(CONF_PASSWORD)): PASSWORD_SELECTOR,
    }
)
STEP_REAUTH_DATA_SCHEMA = probatio.Schema(
    {probatio.Required(probatio.Secret(CONF_PASSWORD)): PASSWORD_SELECTOR}
)

STEP_LOCAL_DATA_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_LOCAL_HOST): TextSelector(),
        probatio.Required(CONF_LOCAL_PORT, default=DEFAULT_LOCAL_PORT): probatio.All(
            probatio.Coerce(int), probatio.Range(min=1, max=65535)
        ),
        probatio.Optional(CONF_LOCAL_USERNAME): TextSelector(),
        probatio.Optional(probatio.Secret(CONF_LOCAL_PASSWORD)): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


def _local_broker(data: dict[str, Any]) -> dict[str, Any]:
    """Build the pyephember2 local_broker argument from a config entry's data."""
    broker: dict[str, Any] = {
        "host": data[CONF_LOCAL_HOST],
        "port": data.get(CONF_LOCAL_PORT, DEFAULT_LOCAL_PORT),
    }
    if data.get(CONF_LOCAL_USERNAME):
        broker["username"] = data[CONF_LOCAL_USERNAME]
        broker["password"] = data.get(CONF_LOCAL_PASSWORD)
    return broker


def _get_user_id(username: str, password: str) -> tuple[str | None, dict[str, str]]:
    """Log in to EPH Ember and return the account's user ID, or errors."""
    try:
        ember = EphEmber(username, password)
        user_id = ember.messenging_credentials()["user_id"]
    except EphEmberError:
        return None, {"base": "cannot_connect"}
    except RuntimeError:
        return None, {"base": "invalid_auth"}
    except Exception:  # noqa: BLE001
        LOGGER.exception("Unexpected error logging in to EPH Ember")
        return None, {"base": "unknown"}
    return str(user_id), {}


def _get_local_gateway_id(data: dict[str, Any]) -> tuple[str | None, dict[str, str]]:
    """Connect to the local broker and return the gateway's id, or errors."""
    try:
        local = EphEmberLocal(_local_broker(data))
    except RuntimeError, OSError, ValueError:
        return None, {"base": "cannot_connect"}
    try:
        gateway_id = next(
            (home["gatewayid"] for home in local.get_zones() if home["zones"]),
            None,
        )
    finally:
        local.close()
    if gateway_id is None:
        return None, {"base": "no_zones"}
    return gateway_id, {}


class EphEmberConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for EPH Controls Ember."""

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose the cloud or a local broker."""
        return self.async_show_menu(step_id="user", menu_options=["cloud", "local"])

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up an account on the EPH Ember cloud."""
        errors: dict[str, str] = {}
        if user_input is not None:
            user_id, errors = await self.hass.async_add_executor_job(
                _get_user_id, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if not errors:
                await self.async_set_unique_id(user_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME], data=user_input
                )
        return self.async_show_form(
            step_id="cloud",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_local(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up a gateway through a local MQTT broker, without the cloud."""
        errors: dict[str, str] = {}
        if user_input is not None:
            gateway_id, errors = await self.hass.async_add_executor_job(
                _get_local_gateway_id, user_input
            )
            if not errors:
                await self.async_set_unique_id(gateway_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="EPH Ember (local)", data=user_input
                )
        return self.async_show_form(
            step_id="local",
            data_schema=self.add_suggested_values_to_schema(
                STEP_LOCAL_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Import the YAML configuration."""
        user_id, errors = await self.hass.async_add_executor_job(
            _get_user_id, import_data[CONF_USERNAME], import_data[CONF_PASSWORD]
        )
        if errors:
            return self.async_abort(reason=errors["base"])
        await self.async_set_unique_id(user_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=import_data[CONF_USERNAME],
            data={
                CONF_USERNAME: import_data[CONF_USERNAME],
                CONF_PASSWORD: import_data[CONF_PASSWORD],
            },
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle a rejected password."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            user_id, errors = await self.hass.async_add_executor_job(
                _get_user_id,
                reauth_entry.data[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            if not errors:
                await self.async_set_unique_id(user_id)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    reauth_entry, data_updates=user_input
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            description_placeholders={"username": reauth_entry.data[CONF_USERNAME]},
            errors=errors,
        )
