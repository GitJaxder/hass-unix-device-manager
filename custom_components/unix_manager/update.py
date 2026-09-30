"""Update entity: pending package updates, installable with progress."""
from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .client import UnixError
from .const import OP_UPGRADE
from .coordinator import UnixConfigEntry, UnixCoordinator
from .entity import UnixEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnixConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([UnixUpdate(entry.runtime_data)])


class UnixUpdate(UnixEntity, UpdateEntity):
    """Package updates as a Home Assistant update.

    Packages have no single version, so the installed version is the OS name
    and the "latest version" is a description of what is pending. Any
    difference between the two means an update is available.
    """

    _attr_translation_key = "os_updates"
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
        | UpdateEntityFeature.RELEASE_NOTES
    )

    def __init__(self, coordinator: UnixCoordinator) -> None:
        super().__init__(coordinator, "os_updates")

    @property
    def installed_version(self) -> str:
        return self.coordinator.data.os_version

    @property
    def latest_version(self) -> str:
        count = len(self.coordinator.data.updates)
        if not count:
            return self.installed_version
        return f"{count} package update{'s' if count != 1 else ''}"

    @property
    def release_summary(self) -> str | None:
        # Home Assistant truncates this to 255 characters.
        return ", ".join(self.coordinator.data.updates) or None

    @property
    def in_progress(self) -> bool:
        # Also true while the Update OS button's upgrade runs.
        return self.coordinator.upgrading

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        # Only called when the two differ, which means updates are pending.
        return True

    async def async_release_notes(self) -> str | None:
        data = self.coordinator.data
        if not data.updates:
            return None
        lines = "\n".join(f"- {pkg}" for pkg in data.updates)
        return f"Pending {data.package_manager} updates:\n\n{lines}"

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        async with self.coordinator.async_operation(OP_UPGRADE):
            try:
                await self.coordinator.client.async_upgrade()
            except UnixError as err:
                raise HomeAssistantError(
                    f"Update OS failed on {self.coordinator.config_entry.title}: {err}"
                ) from err
