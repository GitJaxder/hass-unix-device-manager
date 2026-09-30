"""Data update coordinator."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import UnixClient, UnixData, UnixError
from .const import CONF_INTERVAL, DEFAULT_INTERVAL, DOMAIN

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

    async def _async_update_data(self) -> UnixData:
        try:
            data = await self.client.async_poll()
        except UnixError as err:
            raise UpdateFailed(str(err)) from err
        self._sync_device_registry(data)
        return data

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
