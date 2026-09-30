"""Data update coordinator."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import HostKeyMismatch, UnixClient, UnixData, UnixError, fingerprint
from .const import (
    CONF_HOST_KEY,
    CONF_INTERVAL,
    CONF_STATS_INTERVAL,
    DEFAULT_INTERVAL,
    DEFAULT_STATS_INTERVAL,
    DOMAIN,
)
from .stats import UnixStats

_LOGGER = logging.getLogger(__name__)

type UnixConfigEntry = ConfigEntry[UnixCoordinator]


class UnixCoordinator(DataUpdateCoordinator[UnixData]):
    """Polls OS version and pending updates."""

    config_entry: UnixConfigEntry
    stats: UnixStatsCoordinator  # hardware sensors, polled more often

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


class UnixStatsCoordinator(DataUpdateCoordinator[UnixStats]):
    """Polls CPU, memory, disk and temperature on a short interval."""

    config_entry: UnixConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: UnixConfigEntry, client: UnixClient
    ) -> None:
        seconds = entry.options.get(CONF_STATS_INTERVAL, DEFAULT_STATS_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title} stats",
            update_interval=timedelta(seconds=seconds),
        )
        self.client = client

    async def _async_update_data(self) -> UnixStats:
        try:
            return await self.client.async_stats()
        except HostKeyMismatch as err:
            raise ConfigEntryAuthFailed(f"host key changed: {err}") from err
        except UnixError as err:
            raise UpdateFailed(str(err)) from err
