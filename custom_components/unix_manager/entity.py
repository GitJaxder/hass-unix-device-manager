"""Base entity."""
from __future__ import annotations

from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UnixCoordinator


class UnixEntity(CoordinatorEntity[UnixCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: UnixCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        data = coordinator.data
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        connections = (
            {(CONNECTION_NETWORK_MAC, format_mac(data.mac_address))}
            if data.mac_address
            else set()
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            connections=connections,
            name=entry.title,
            manufacturer=data.manufacturer,
            model=data.model,
            sw_version=data.os_version,
            hw_version=data.architecture,
        )
