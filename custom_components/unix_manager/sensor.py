"""Sensors: OS version, available updates and hardware statistics."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfInformation,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import UnixData
from .const import MAX_LISTED_PACKAGES
from .coordinator import UnixConfigEntry, UnixCoordinator, UnixStatsCoordinator
from .entity import UnixEntity, device_info
from .stats import UnixStats


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



@dataclass(frozen=True, kw_only=True)
class UnixStatsSensorDescription(SensorEntityDescription):
    value_fn: Callable[[UnixStats], float | int | datetime | None]
    attrs_fn: Callable[[UnixStats], dict[str, Any]] | None = None


def _mib(kib: int | None) -> float | None:
    return None if kib is None else round(kib / 1024, 1)


def _gib(kib: int | None) -> float | None:
    return None if kib is None else round(kib / 1024**2, 2)


def _load(index: int) -> Callable[[UnixStats], float | None]:
    return lambda s: s.load[index] if s.load else None


_PERCENT = {
    "native_unit_of_measurement": PERCENTAGE,
    "state_class": SensorStateClass.MEASUREMENT,
    "suggested_display_precision": 1,
}

STATS_SENSORS = (
    UnixStatsSensorDescription(
        key="cpu_usage",
        translation_key="cpu_usage",
        icon="mdi:cpu-64-bit",
        value_fn=lambda s: s.cpu_usage,
        **_PERCENT,
    ),
    UnixStatsSensorDescription(
        key="cpu_temperature",
        translation_key="cpu_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: s.cpu_temperature,
    ),
    UnixStatsSensorDescription(
        key="memory_usage",
        translation_key="memory_usage",
        icon="mdi:memory",
        value_fn=lambda s: s.memory_usage,
        attrs_fn=lambda s: {
            "used_mib": _mib(s.memory_used),
            "total_mib": _mib(s.memory_total),
        },
        **_PERCENT,
    ),
    UnixStatsSensorDescription(
        key="memory_used",
        translation_key="memory_used",
        icon="mdi:memory",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.MEBIBYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_registry_enabled_default=False,
        value_fn=lambda s: _mib(s.memory_used),
    ),
    UnixStatsSensorDescription(
        key="swap_usage",
        translation_key="swap_usage",
        icon="mdi:harddisk",
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.swap_usage,
        **_PERCENT,
    ),
    UnixStatsSensorDescription(
        key="disk_usage",
        translation_key="disk_usage",
        icon="mdi:harddisk",
        value_fn=lambda s: s.disk_usage,
        attrs_fn=lambda s: {
            "used_gib": _gib(s.disk_used),
            "free_gib": _gib(s.disk_free),
            "total_gib": _gib(s.disk_total),
        },
        **_PERCENT,
    ),
    UnixStatsSensorDescription(
        key="disk_free",
        translation_key="disk_free",
        icon="mdi:harddisk",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: _gib(s.disk_free),
    ),
    *(
        UnixStatsSensorDescription(
            key=f"load_{minutes}m",
            translation_key=f"load_{minutes}m",
            icon="mdi:gauge",
            state_class=SensorStateClass.MEASUREMENT,
            suggested_display_precision=2,
            entity_registry_enabled_default=False,
            value_fn=_load(index),
        )
        for index, minutes in enumerate((1, 5, 15))
    ),
    UnixStatsSensorDescription(
        key="last_boot",
        translation_key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: (
            datetime.fromtimestamp(s.boot_time, timezone.utc) if s.boot_time else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: UnixConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    stats = coordinator.stats.data
    entities: list[SensorEntity] = [UnixSensor(coordinator, d) for d in SENSORS]
    # Only create sensors the host can report; a board without a thermal
    # zone gets no temperature sensor rather than one stuck on "unknown".
    entities.extend(
        UnixStatsSensor(coordinator, d)
        for d in STATS_SENSORS
        if d.value_fn(stats) is not None
    )
    async_add_entities(entities)


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


class UnixStatsSensor(CoordinatorEntity[UnixStatsCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: UnixStatsSensorDescription

    def __init__(
        self, coordinator: UnixCoordinator, description: UnixStatsSensorDescription
    ) -> None:
        super().__init__(coordinator.stats)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{description.key}"
        self._attr_device_info = device_info(coordinator)

    @property
    def native_value(self) -> float | int | datetime | None:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if fn := self.entity_description.attrs_fn:
            return fn(self.coordinator.data)
        return None
