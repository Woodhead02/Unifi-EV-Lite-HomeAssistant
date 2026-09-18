from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import UniFiEVCoordinator, _first
from .entity import UniFiEVEntity


@dataclass(frozen=True, kw_only=True)
class UniFiEVSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]


def _status(item: dict[str, Any]) -> Any:
    device = item["device"]
    status = _first(
        device,
        ("shadow", "chargingStatus"),
        ("chargingStatus",),
        ("relayShadow", "chargingStatus"),
    )
    if status is not None:
        return status

    # Connect's frontend reducer defaults a missing EV charging status to
    # Available. While live telemetry is streaming we can safely report
    # Charging even if the REST shadow omits chargingStatus.
    if item.get("power", {}).get("streaming") is True:
        return "Charging"
    return "Available"



def _live_number(item: dict[str, Any], key: str) -> float | None:
    value = item.get("power", {}).get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _power_kw(item: dict[str, Any]) -> float | None:
    value = _live_number(item, "instantKW")
    if value is not None:
        return round(value, 3)
    # Compatibility with older/historical payload naming.
    value = _live_number(item, "instantMW")
    return round(value / 1000, 3) if value is not None else None


def _current_a(item: dict[str, Any]) -> float | None:
    value = _live_number(item, "instantA")
    if value is not None:
        return round(value, 2)
    value = _live_number(item, "instantMA")
    return round(value / 1000, 2) if value is not None else None


def _last(item: dict[str, Any], key: str) -> Any:
    last = item["history"].get("last")
    return last.get(key) if isinstance(last, dict) else None


SENSORS = (
    UniFiEVSensorDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        value_fn=_power_kw,
    ),
    UniFiEVSensorDescription(
        key="current",
        translation_key="current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=2,
        value_fn=_current_a,
    ),
    UniFiEVSensorDescription(
        key="voltage",
        translation_key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=0,
        value_fn=lambda i: _live_number(i, "instantV"),
    ),
    UniFiEVSensorDescription(
        key="session_energy",
        translation_key="session_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda i: _live_number(i, "meter"),
    ),
    UniFiEVSensorDescription(
        key="session_duration",
        translation_key="session_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda i: _live_number(i, "duration"),
    ),
    UniFiEVSensorDescription(
        key="charging_status",
        translation_key="charging_status",
        value_fn=_status,
    ),
    UniFiEVSensorDescription(
        key="last_session_energy",
        translation_key="last_session_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda i: _last(i, "powerUsage"),
    ),
    UniFiEVSensorDescription(
        key="last_session_charge_time",
        translation_key="last_session_charge_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement="s",
        value_fn=lambda i: _last(i, "chargeTime"),
    ),
    UniFiEVSensorDescription(
        key="history_energy",
        translation_key="history_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda i: round(i["history"]["total_kwh"], 2),
    ),
    UniFiEVSensorDescription(
        key="sessions",
        translation_key="sessions",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda i: i["history"]["sessions"],
    ),
    UniFiEVSensorDescription(
        key="energy_today",
        translation_key="energy_today",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda i: round(i["history"]["energy_today"], 2),
    ),
    UniFiEVSensorDescription(
        key="energy_month_to_date",
        translation_key="energy_month_to_date",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda i: round(i["history"]["energy_month_to_date"], 2),
    ),
    UniFiEVSensorDescription(
        key="energy_7d",
        translation_key="energy_7d",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda i: round(i["history"]["energy_7d"], 2),
    ),
    UniFiEVSensorDescription(
        key="energy_30d",
        translation_key="energy_30d",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda i: round(i["history"]["energy_30d"], 2),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: UniFiEVCoordinator = entry.runtime_data
    async_add_entities(
        UniFiEVSensor(coordinator, device_id, description)
        for device_id in coordinator.data
        for description in SENSORS
    )


class UniFiEVSensor(UniFiEVEntity, SensorEntity):
    entity_description: UniFiEVSensorDescription

    def __init__(
        self,
        coordinator: UniFiEVCoordinator,
        device_id: str,
        description: UniFiEVSensorDescription,
    ) -> None:
        self.entity_description = description
        super().__init__(coordinator, device_id)

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.item)
