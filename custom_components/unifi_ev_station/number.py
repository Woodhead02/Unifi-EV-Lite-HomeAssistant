from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import UniFiEVError
from .coordinator import UniFiEVCoordinator, _first, _find_key
from .entity import UniFiEVEntity

DESCRIPTION = NumberEntityDescription(
    key="maximum_output_amps",
    translation_key="maximum_output_amps",
    device_class=NumberDeviceClass.CURRENT,
    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
    native_step=1,
)


def _action_for(item: dict[str, Any], name: str) -> dict[str, Any] | None:
    actions = _first(item["device"], ("type", "supportedActions")) or []
    return next(
        (
            action
            for action in actions
            if isinstance(action, dict) and action.get("name") == name
        ),
        None,
    )


def _reported_max_output(item: dict[str, Any]) -> float | None:
    """Find a current max-output value wherever this firmware exposes it."""
    device = item["device"]
    value = _first(
        device,
        ("maxOutput",),
        ("shadow", "maxOutput"),
        ("relayShadow", "maxOutput"),
        ("config", "maxOutput"),
        ("extraInfo", "maxOutput"),
    )
    if value is None:
        value = _find_key(device, "maxOutput")
    if value is None:
        value = item.get("last_set_max_output")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _breaker_amperage(item: dict[str, Any]) -> float | None:
    device = item["device"]
    value = _first(
        device,
        ("breakerAmperage",),
        ("extraInfo", "breakerAm"),
        ("shadow", "breakerAmperage"),
    )
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _max_allowed(item: dict[str, Any]) -> float:
    """Best available upper bound, without hardcoding one charger model."""
    device = item["device"]

    # Prefer explicit limits advertised by Connect when present.
    for key in ("deratingMaxCurrent", "maxOutputAmp", "maximumOutput"):
        value = _find_key(device, key)
        try:
            if value is not None and float(value) > 0:
                return float(value)
        except (TypeError, ValueError):
            pass

    # EV charging is a continuous load. Connect's UI uses breaker-aware limits;
    # 80% of breaker rating matches common 60A -> 48A installations. Cap at 50A
    # because the currently observed Connect frontend table tops out there.
    breaker = _breaker_amperage(item)
    if breaker and breaker > 0:
        return min(50.0, breaker * 0.8)

    # Conservative fallback for an EV Station Lite when no metadata is exposed.
    return 50.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: UniFiEVCoordinator = entry.runtime_data
    entities = []
    for device_id, item in coordinator.data.items():
        if _action_for(item, "set_max_output_amp"):
            entities.append(UniFiEVMaximumOutputNumber(coordinator, device_id))
    async_add_entities(entities)


class UniFiEVMaximumOutputNumber(UniFiEVEntity, NumberEntity):
    entity_description = DESCRIPTION
    _attr_native_min_value = 6.0
    _attr_native_step = 1.0

    @property
    def native_value(self) -> float | None:
        return _reported_max_output(self.item)

    @property
    def native_max_value(self) -> float:
        return _max_allowed(self.item)

    async def async_set_native_value(self, value: float) -> None:
        rounded = int(round(value))
        if rounded < int(self.native_min_value) or rounded > int(self.native_max_value):
            raise UniFiEVError(
                f"Requested maximum output {rounded}A is outside the supported "
                f"range {self.native_min_value:.0f}-{self.native_max_value:.0f}A"
            )

        await self.coordinator.async_run_named_action(
            self.device_id,
            "set_max_output_amp",
            args={"maxOutput": rounded},
        )
