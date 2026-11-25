"""Diagnostic binary sensors that tell load-management automations whether
the integration's data and commands can be trusted."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SET_MAX_OUTPUT_ACTION, UniFiEVCoordinator, find_action
from .entity import UniFiEVEntity


@dataclass(frozen=True, kw_only=True)
class UniFiEVBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], bool | None]
    needs_setpoint_action: bool = False


BINARY_SENSORS = (
    UniFiEVBinarySensorDescription(
        key="telemetry_connected",
        translation_key="telemetry_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda item: bool(item.get("telemetry_connected")),
    ),
    UniFiEVBinarySensorDescription(
        key="maximum_output_pending",
        translation_key="maximum_output_pending",
        entity_category=EntityCategory.DIAGNOSTIC,
        needs_setpoint_action=True,
        value_fn=lambda item: bool(item.get("setpoint", {}).get("pending")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: UniFiEVCoordinator = entry.runtime_data
    async_add_entities(
        UniFiEVBinarySensor(coordinator, device_id, description)
        for device_id, item in coordinator.data.items()
        for description in BINARY_SENSORS
        if not description.needs_setpoint_action
        or find_action(item["device"], SET_MAX_OUTPUT_ACTION)
    )


class UniFiEVBinarySensor(UniFiEVEntity, BinarySensorEntity):
    entity_description: UniFiEVBinarySensorDescription

    def __init__(
        self,
        coordinator: UniFiEVCoordinator,
        device_id: str,
        description: UniFiEVBinarySensorDescription,
    ) -> None:
        self.entity_description = description
        super().__init__(coordinator, device_id)

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.item)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "maximum_output_pending":
            return None
        setpoint = self.item.get("setpoint", {})
        return {
            "desired": setpoint.get("desired"),
            "last_sent": setpoint.get("last_sent"),
            "last_error": setpoint.get("error"),
        }
