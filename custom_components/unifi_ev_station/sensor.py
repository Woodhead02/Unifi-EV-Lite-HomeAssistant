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
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import UniFiEVCoordinator, _first
from .entity import UniFiEVEntity


@dataclass(frozen=True, kw_only=True)
class UniFiEVSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]
    # Live readings come from the telemetry WebSocket. When that stream is
    # down they are unavailable rather than a misleading 0.
    live: bool = False


# Raw chargingStatus values that mean "a car is connected" rather than
# "energy is flowing right now". UniFi keeps reporting Charging for a session
# that is paused or finished (car full / scheduled), so the raw value alone
# overstates what the charger is doing.
_CONNECTED_STATES = {"charging", "chargingstopped", "cableconnected", "suspended", "suspendedev", "suspendedevse"}
_ACTIVE_POWER_KW = 0.05


def _raw_status(item: dict[str, Any]) -> Any:
    device = item["device"]
    return _first(
        device,
        ("shadow", "chargingStatus"),
        ("chargingStatus",),
        ("relayShadow", "chargingStatus"),
    )


def _status(item: dict[str, Any]) -> Any:
    raw = _raw_status(item)
    power = item.get("power", {})
    kw = _power_kw(item) or 0.0
    streaming = power.get("streaming") is True

    # Energy is actually flowing: this is the only case reported as Charging.
    if streaming and kw > _ACTIVE_POWER_KW:
        return "Charging"
    if kw > _ACTIVE_POWER_KW:
        return "Charging"

    if raw is not None:
        key = str(raw).replace("_", "").replace(" ", "").lower()
        if key in _CONNECTED_STATES:
            # Car is plugged in but not drawing power (paused, full, or
            # waiting on a schedule).
            return "Plugged in"
        return raw

    # Connect's frontend reducer defaults a missing EV charging status to
    # Available. A stream with no measurable power is a connected car that is
    # not currently drawing.
    if streaming:
        return "Plugged in"
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
        live=True,
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        value_fn=_power_kw,
    ),
    UniFiEVSensorDescription(
        key="current",
        live=True,
        translation_key="current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=2,
        value_fn=_current_a,
    ),
    UniFiEVSensorDescription(
        key="voltage",
        live=True,
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
        value_fn=lambda i: round(float(i.get("live_session_kwh") or 0.0), 3),
    ),
    UniFiEVSensorDescription(
        key="session_duration",
        live=True,
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
        key="raw_charging_status",
        translation_key="raw_charging_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_raw_status,
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
        value_fn=lambda i: round(float(i.get("energy_today_live", i["history"]["energy_today"])), 2),
    ),
    UniFiEVSensorDescription(
        key="energy_month_to_date",
        translation_key="energy_month_to_date",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda i: round(float(i.get("energy_month_to_date_live", i["history"]["energy_month_to_date"])), 2),
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
    def available(self) -> bool:
        if not super().available:
            return False
        if self.entity_description.live:
            return bool(self.item.get("telemetry_connected"))
        return True

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.item)
