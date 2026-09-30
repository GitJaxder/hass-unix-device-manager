"""Sensors: OS version and available updates."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .client import UnixData
from .const import MAX_LISTED_PACKAGES
from .coordinator import UnixConfigEntry, UnixCoordinator
from .entity import UnixEntity


@dataclass(frozen=True, kw_only=True)
class UnixSensorDescription(SensorEntityDescription):
    value_fn: Callable[[UnixData], str | int | None]
    attrs_fn: Callable[[UnixData], dict[str, Any]] | None = None


SENSORS = (
    UnixSensorDescription(
        key="os_version",
        translation_key="os_version",
        icon="mdi:linux",
        value_fn=lambda d: d.os_version,
    ),
    UnixSensorDescription(
        key="updates_available",
        translation_key="updates_available",
        icon="mdi:package-up",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(d.updates),
        attrs_fn=lambda d: {
            "package_manager": d.package_manager,
            "packages": d.updates[:MAX_LISTED_PACKAGES],
        },
    ),
    UnixSensorDescription(
        key="ip_address",
        translation_key="ip_address",
        icon="mdi:ip-network",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.ip_address,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnixConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(UnixSensor(entry.runtime_data, d) for d in SENSORS)


class UnixSensor(UnixEntity, SensorEntity):
    entity_description: UnixSensorDescription

    def __init__(self, coordinator: UnixCoordinator, description: UnixSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | int | None:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if fn := self.entity_description.attrs_fn:
            return fn(self.coordinator.data)
        return None
