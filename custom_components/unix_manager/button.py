"""Buttons: refresh repositories, upgrade OS."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .client import UnixClient, UnixError
from .const import OP_NAMES, OP_REFRESH, OP_UPGRADE
from .coordinator import UnixConfigEntry, UnixCoordinator
from .entity import UnixEntity


@dataclass(frozen=True, kw_only=True)
class UnixButtonDescription(ButtonEntityDescription):
    press_fn: Callable[[UnixClient], Awaitable[None]]


BUTTONS = (
    UnixButtonDescription(
        key=OP_REFRESH,
        translation_key=OP_REFRESH,
        icon="mdi:database-refresh",
        press_fn=lambda c: c.async_refresh_repositories(),
    ),
    UnixButtonDescription(
        key=OP_UPGRADE,
        translation_key=OP_UPGRADE,
        device_class=ButtonDeviceClass.UPDATE,
        press_fn=lambda c: c.async_upgrade(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnixConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(UnixButton(entry.runtime_data, d) for d in BUTTONS)


class UnixButton(UnixEntity, ButtonEntity):
    entity_description: UnixButtonDescription

    def __init__(self, coordinator: UnixCoordinator, description: UnixButtonDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        key = self.entity_description.key
        async with self.coordinator.async_operation(key):
            try:
                await self.entity_description.press_fn(self.coordinator.client)
            except UnixError as err:
                raise HomeAssistantError(
                    f"{OP_NAMES[key]} failed on {self.coordinator.config_entry.title}: {err}"
                ) from err
