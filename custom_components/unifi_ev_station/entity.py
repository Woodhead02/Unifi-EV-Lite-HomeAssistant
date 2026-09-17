from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UniFiEVCoordinator, _first


class UniFiEVEntity(CoordinatorEntity[UniFiEVCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: UniFiEVCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_{self.entity_description.key}"

    @property
    def item(self) -> dict[str, Any]:
        return self.coordinator.data[self.device_id]

    @property
    def device(self) -> dict[str, Any]:
        return self.item["device"]

    @property
    def device_info(self) -> DeviceInfo:
        name = (
            self.device.get("name")
            or _first(self.device, ("shadow", "name"))
            or "UniFi EV Station"
        )
        model = self.device.get("model") or "EV Station"
        mac = self.device.get("mac")
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            manufacturer="Ubiquiti",
            name=str(name),
            model=str(model),
            serial_number=str(mac) if mac else None,
        )
