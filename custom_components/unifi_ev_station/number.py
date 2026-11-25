from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .api import UniFiEVError
from .coordinator import SET_MAX_OUTPUT_ACTION, UniFiEVCoordinator, _first, find_action
from .entity import UniFiEVEntity
from .limits import ABSOLUTE_MIN_AMPS

DESCRIPTION = NumberEntityDescription(
    key="maximum_output_amps",
    translation_key="maximum_output_amps",
    device_class=NumberDeviceClass.CURRENT,
    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
    native_step=1,
)


def _action_for(item: dict[str, Any], name: str) -> dict[str, Any] | None:
    return find_action(item["device"], name)


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
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: UniFiEVCoordinator = entry.runtime_data
    entities = []
    for device_id, item in coordinator.data.items():
        if _action_for(item, SET_MAX_OUTPUT_ACTION):
            entities.append(UniFiEVMaximumOutputNumber(coordinator, device_id))
    async_add_entities(entities)


class UniFiEVMaximumOutputNumber(UniFiEVEntity, NumberEntity, RestoreEntity):
    """Desired maximum charging current.

    The value shown is what Home Assistant wants the charger limited to. The
    coordinator sends it (decreases immediately, increases rate limited) and
    re-asserts it periodically, because the EV Station Lite does not always
    report its active setpoint back.
    """

    entity_description = DESCRIPTION
    _attr_native_min_value = ABSOLUTE_MIN_AMPS
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
        desired = self.item.get("setpoint", {}).get("desired")
        if desired is not None:
            return float(desired)
        return (
            _reported_max_output(self.item)
            or _as_positive_number(self.item.get("last_set_max_output"))
            or self._restored_value
        )

    @property
    def native_max_value(self) -> float:
        return self.coordinator.max_amps_for(self.device)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        setpoint = self.item.get("setpoint", {})
        return {
            "last_sent": setpoint.get("last_sent"),
            "pending": setpoint.get("pending"),
            "last_error": setpoint.get("error"),
            "reported_by_charger": _reported_max_output(self.item),
        }

    async def async_set_native_value(self, value: float) -> None:
        rounded = int(round(value))
        if rounded < int(self.native_min_value) or rounded > int(self.native_max_value):
            raise ServiceValidationError(
                f"Requested maximum output {rounded}A is outside the supported "
                f"range {self.native_min_value:.0f}-{self.native_max_value:.0f}A"
            )
        try:
            await self.coordinator.async_request_max_output(self.device_id, rounded)
        except UniFiEVError as err:
            raise HomeAssistantError(str(err)) from err
        self._restored_value = float(rounded)
        self.async_write_ha_state()
