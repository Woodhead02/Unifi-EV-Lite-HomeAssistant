from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .api import UniFiEVError
from .coordinator import UniFiEVCoordinator, _first
from .entity import UniFiEVEntity

DESCRIPTION = NumberEntityDescription(
    key="maximum_output_amps",
    translation_key="maximum_output_amps",
    device_class=NumberDeviceClass.CURRENT,
    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
    native_step=1,
)

# EVSE continuous-load limits from the UniFi EV Station installation table.
# These are the supported circuit-breaker/output pairs shown by Ubiquiti.
BREAKER_MAX_OUTPUT: dict[int, float] = {
    20: 16.0,
    30: 24.0,
    40: 32.0,
    50: 40.0,
    60: 48.0,
    80: 64.0,
    100: 80.0,
}


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


def _as_positive_number(value: Any) -> float | None:
    """Return a positive scalar number, rejecting action schemas and containers."""
    if isinstance(value, bool) or isinstance(value, (dict, list, tuple, set)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _reported_max_output(item: dict[str, Any]) -> float | None:
    """Read only explicit device-state locations known to carry a setpoint.

    Do not recursively search for ``maxOutput``: supportedActions may contain an
    argument/schema named maxOutput, which is not the charger's current setpoint.
    """
    device = item["device"]
    for path in (
        ("shadow", "maxOutput"),
        ("relayShadow", "maxOutput"),
        ("config", "maxOutput"),
        ("extraInfo", "maxOutput"),
        ("maxOutput",),
    ):
        if (value := _as_positive_number(_first(device, path))) is not None:
            return value

    return _as_positive_number(item.get("last_set_max_output"))


def _breaker_amperage(item: dict[str, Any]) -> float | None:
    device = item["device"]
    value = _first(
        device,
        ("breakerAmperage",),
        ("extraInfo", "breakerAm"),
        ("shadow", "breakerAmperage"),
    )
    return _as_positive_number(value)


def _max_allowed(item: dict[str, Any]) -> float:
    """Return the UniFi-supported maximum output for the configured breaker."""
    breaker = _breaker_amperage(item)
    if breaker is not None:
        breaker_int = int(round(breaker))
        if breaker_int in BREAKER_MAX_OUTPUT:
            return BREAKER_MAX_OUTPUT[breaker_int]

        # For an unlisted breaker size, apply the same 80% continuous-load rule
        # rather than using unrelated derating telemetry as the UI slider cap.
        return breaker * 0.8

    # Fallback when breaker metadata is unavailable. 80A is the highest maximum
    # output in the published table (100A circuit breaker).
    return 80.0


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


class UniFiEVMaximumOutputNumber(UniFiEVEntity, NumberEntity, RestoreEntity):
    entity_description = DESCRIPTION
    _attr_native_min_value = 6.0
    _attr_native_step = 1.0

    def __init__(self, coordinator: UniFiEVCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._restored_value: float | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        restored = _as_positive_number(state.state)
        if restored is not None:
            self._restored_value = restored

    @property
    def native_value(self) -> float | None:
        return _reported_max_output(self.item) or self._restored_value

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
        # EV Station Lite does not consistently include the setpoint in the
        # polled /devices payload. Keep HA's state optimistic after a confirmed
        # successful PATCH, and RestoreEntity preserves it across restarts.
        self._restored_value = float(rounded)
        self.async_write_ha_state()
