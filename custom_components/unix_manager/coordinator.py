"""Data update coordinator."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import HostKeyMismatch, UnixClient, UnixData, UnixError, fingerprint
from .const import (
    CONF_HOST_KEY,
    CONF_INTERVAL,
    DEFAULT_INTERVAL,
    DOMAIN,
    OP_NAMES,
    OP_UPGRADE,
)

_LOGGER = logging.getLogger(__name__)

type UnixConfigEntry = ConfigEntry[UnixCoordinator]


class UnixCoordinator(DataUpdateCoordinator[UnixData]):
    """Polls OS version and pending updates."""

    config_entry: UnixConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: UnixConfigEntry, client: UnixClient
    ) -> None:
        minutes = entry.options.get(CONF_INTERVAL, DEFAULT_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(minutes=minutes),
        )
        self.client = client
        # Key of the button/update action running on the host, if any.
        self.operation: str | None = None

    @property
    def upgrading(self) -> bool:
        return self.operation == OP_UPGRADE

    @asynccontextmanager
    async def async_operation(self, key: str) -> AsyncIterator[None]:
        """Mark a refresh or upgrade as running, rejecting overlapping ones.

        Entities are told when it starts and ends so the UI can show it. The
        data is re-polled before it ends, so an update entity doesn't flash
        "update available" between the upgrade finishing and the next poll.
        """
        if self.operation is not None:
            raise HomeAssistantError(
                f"{OP_NAMES[self.operation]} is already running on "
                f"{self.config_entry.title}; wait for it to finish"
            )
        self.operation = key
        self.async_update_listeners()
        try:
            yield
            await self.async_refresh()
        finally:
            self.operation = None
            self.async_update_listeners()

    async def _async_update_data(self) -> UnixData:
        try:
            data = await self.client.async_poll()
        except HostKeyMismatch as err:
            raise ConfigEntryAuthFailed(f"host key changed: {err}") from err
        except UnixError as err:
            raise UpdateFailed(str(err)) from err
        self._pin_host_key()
        self._sync_device_registry(data)
        return data

    def _pin_host_key(self) -> None:
        """Store the key seen on first contact (entries created before pinning)."""
        entry = self.config_entry
        if entry.data.get(CONF_HOST_KEY) or not self.client.host_key:
            return
        _LOGGER.warning(
            "Pinned SSH host key for %s: %s",
            entry.title,
            fingerprint(self.client.host_key),
        )
        self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_HOST_KEY: self.client.host_key}
        )

    def _sync_device_registry(self, data: UnixData) -> None:
        """Keep the device page current, e.g. after an OS upgrade."""
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(
            identifiers={(DOMAIN, self.config_entry.entry_id)}
        )
        if device is None:  # first refresh: entities haven't created it yet
            return
        if (device.sw_version, device.hw_version) != (data.os_version, data.architecture):
            registry.async_update_device(
                device.id, sw_version=data.os_version, hw_version=data.architecture
            )
