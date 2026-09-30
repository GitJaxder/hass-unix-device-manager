"""Unix Device Manager: monitor and update unix hosts over SSH."""
from __future__ import annotations

import asyncssh

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .client import UnixClient, load_key
from .const import CONF_HOST_KEY, CONF_KEY_FILE
from .coordinator import UnixConfigEntry, UnixCoordinator, UnixStatsCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: UnixConfigEntry) -> bool:
    key = None
    if key_file := entry.data.get(CONF_KEY_FILE):
        try:
            key = await hass.async_add_executor_job(load_key, key_file)
        except (OSError, ValueError, asyncssh.Error) as err:
            raise ConfigEntryError(f"Cannot load SSH key {key_file}: {err}") from err

    client = UnixClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_USERNAME],
        entry.data.get(CONF_PASSWORD),
        key,
        entry.data.get(CONF_HOST_KEY),
    )
    coordinator = UnixCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    coordinator.stats = UnixStatsCoordinator(hass, entry, client)
    await coordinator.stats.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: UnixConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: UnixConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
