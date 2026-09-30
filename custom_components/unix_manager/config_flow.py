"""Config and options flow."""
from __future__ import annotations

import logging
from typing import Any

import asyncssh
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback

from .client import CannotConnect, InvalidAuth, UnixClient, UnsupportedSystem, load_key
from .const import CONF_INTERVAL, CONF_KEY_FILE, DEFAULT_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=22): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Required(CONF_USERNAME): str,
        vol.Optional(CONF_PASSWORD): str,
        vol.Optional(CONF_KEY_FILE): str,
    }
)


class UnixConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return UnixOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            password = user_input.get(CONF_PASSWORD) or None
            key_file = user_input.get(CONF_KEY_FILE) or None

            await self.async_set_unique_id(f"{host.lower()}:{port}")
            self._abort_if_unique_id_configured()

            if not password and not key_file:
                errors["base"] = "no_credentials"
            else:
                key = None
                try:
                    if key_file:
                        key = await self.hass.async_add_executor_job(load_key, key_file)
                except (OSError, ValueError, asyncssh.Error):  # key errors are ValueErrors
                    errors["base"] = "invalid_key"
                else:
                    client = UnixClient(host, port, user_input[CONF_USERNAME], password, key)
                    try:
                        await client.async_validate()
                    except InvalidAuth:
                        errors["base"] = "invalid_auth"
                    except CannotConnect:
                        errors["base"] = "cannot_connect"
                    except UnsupportedSystem:
                        errors["base"] = "unsupported"
                    except Exception:  # noqa: BLE001
                        _LOGGER.exception("Validation failed")
                        errors["base"] = "unknown"
                    else:
                        return self.async_create_entry(
                            title=host,
                            data={
                                CONF_HOST: host,
                                CONF_PORT: port,
                                CONF_USERNAME: user_input[CONF_USERNAME],
                                CONF_PASSWORD: password,
                                CONF_KEY_FILE: key_file,
                            },
                        )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, user_input),
            errors=errors,
        )


class UnixOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_INTERVAL, DEFAULT_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_INTERVAL, default=current): vol.All(
                        vol.Coerce(int), vol.Range(min=5, max=1440)
                    )
                }
            ),
        )
