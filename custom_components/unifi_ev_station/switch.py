from __future__ import annotations

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import UniFiEVError
from .coordinator import UniFiEVCoordinator, _first
from .entity import UniFiEVEntity

DESCRIPTION = SwitchEntityDescription(
    key="allow_charging",
    translation_key="allow_charging",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: UniFiEVCoordinator = entry.runtime_data
    entities = []
    for device_id, item in coordinator.data.items():
        actions = _first(item["device"], ("type", "supportedActions")) or []
        names = {a.get("name") for a in actions if isinstance(a, dict)}
        if "enable_charging" in names or "disable_charging" in names:
            entities.append(UniFiEVChargingSwitch(coordinator, device_id))
    async_add_entities(entities)


class UniFiEVChargingSwitch(UniFiEVEntity, SwitchEntity):
    entity_description = DESCRIPTION

    @property
    def is_on(self) -> bool | None:
        device = self.device
        value = _first(
            device,
            ("relayShadow", "enabledCharing"),
            ("relayShadow", "enabledCharging"),
            ("shadow", "enabledCharing"),
            ("shadow", "enabledCharging"),
            ("enabledCharing",),
            ("enabledCharging",),
        )
        if isinstance(value, bool):
            return value

        status = _first(device, ("chargingStatus",), ("shadow", "chargingStatus"))
        if status in {"Unavailable", "Locked"}:
            return False
        return None

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_run_named_action(
            self.device_id, "enable_charging"
        )

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_run_named_action(
            self.device_id, "disable_charging"
        )
