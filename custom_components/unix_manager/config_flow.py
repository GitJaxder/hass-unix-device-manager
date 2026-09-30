"""Config and options flow."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import asyncssh
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback

from .client import (
    CannotConnect,
    HostKeyMismatch,
    InvalidAuth,
    UnixClient,
    UnsupportedSystem,
    fetch_host_key,
    fingerprint,
    load_key,
)
from .const import CONF_HOST_KEY, CONF_INTERVAL, CONF_KEY_FILE, DEFAULT_INTERVAL, DOMAIN

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


def _host_key_file(host_key: str) -> str:
    """Where the matching public key usually lives on the remote host."""
    algorithm = host_key.split(" ", 1)[0]
    if algorithm.startswith("ecdsa"):
        kind = "ecdsa"
    else:
        kind = {"ssh-ed25519": "ed25519", "ssh-rsa": "rsa"}.get(algorithm, "*")
    return f"/etc/ssh/ssh_host_{kind}_key.pub"


def _host_key_placeholders(host: str, host_key: str) -> dict[str, str]:
    return {
        "host": host,
        "fingerprint": fingerprint(host_key),
        "key_file": _host_key_file(host_key),
    }


async def _async_load_key(hass: HomeAssistant, key_file: str | None) -> asyncssh.SSHKey | None:
    """Load the client key; key import errors are ValueErrors."""
    if not key_file:
        return None
    return await hass.async_add_executor_job(load_key, key_file)


async def _async_validate(
    data: dict[str, Any], client_key: asyncssh.SSHKey | None, host_key: str
) -> str | None:
    """Log in with the host key pinned. Returns an error key, or None."""
    client = UnixClient(
        data[CONF_HOST], data[CONF_PORT], data[CONF_USERNAME],
        data.get(CONF_PASSWORD), client_key, host_key,
    )
    try:
        await client.async_validate()
    except HostKeyMismatch:
        return "host_key_changed"
    except InvalidAuth:
        return "invalid_auth"
    except CannotConnect:
        return "cannot_connect"
    except UnsupportedSystem:
        return "unsupported"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Validation failed")
        return "unknown"
    return None


class UnixConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._client_key: asyncssh.SSHKey | None = None
        self._host_key: str | None = None

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
                try:
                    self._client_key = await _async_load_key(self.hass, key_file)
                except (OSError, ValueError, asyncssh.Error):
                    errors["base"] = "invalid_key"
                else:
                    try:
                        # No credentials are sent until the key is confirmed.
                        self._host_key = await fetch_host_key(host, port)
                    except CannotConnect:
                        errors["base"] = "cannot_connect"
                    else:
                        self._data = {
                            CONF_HOST: host,
                            CONF_PORT: port,
                            CONF_USERNAME: user_input[CONF_USERNAME],
                            CONF_PASSWORD: password,
                            CONF_KEY_FILE: key_file,
                        }
                        return await self.async_step_host_key()

        return self._show_user_form(user_input, errors)

    async def async_step_host_key(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the host key fingerprint and pin it once confirmed."""
        assert self._host_key is not None
        if user_input is not None:
            if error := await _async_validate(self._data, self._client_key, self._host_key):
                return self._show_user_form(self._data, {"base": error})
            return self.async_create_entry(
                title=self._data[CONF_HOST],
                data={**self._data, CONF_HOST_KEY: self._host_key},
            )
        return self.async_show_form(
            step_id="host_key",
            description_placeholders=_host_key_placeholders(
                self._data[CONF_HOST], self._host_key
            ),
        )

    def _show_user_form(
        self, values: dict[str, Any] | None, errors: dict[str, str]
    ) -> ConfigFlowResult:
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, values),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Started when the host presents a different host key."""
        self._host_key = None
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the new host key and pin it once confirmed."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if self._host_key is None:
            try:
                self._host_key = await fetch_host_key(
                    entry.data[CONF_HOST], entry.data[CONF_PORT]
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
                user_input = None
        if user_input is not None and self._host_key is not None:
            try:
                client_key = await _async_load_key(self.hass, entry.data.get(CONF_KEY_FILE))
            except (OSError, ValueError, asyncssh.Error):
                errors["base"] = "invalid_key"
            else:
                error = await _async_validate(dict(entry.data), client_key, self._host_key)
                if error is None:
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_HOST_KEY: self._host_key}
                    )
                errors["base"] = error
        placeholders = (
            _host_key_placeholders(entry.data[CONF_HOST], self._host_key)
            if self._host_key
            else {"host": entry.data[CONF_HOST], "fingerprint": "unavailable", "key_file": "-"}
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders=placeholders,
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
