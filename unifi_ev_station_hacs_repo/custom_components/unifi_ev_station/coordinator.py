from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import UniFiEVAuthError, UniFiEVClient, UniFiEVError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _first(obj: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        value: Any = obj
        for key in path:
            if not isinstance(value, dict) or key not in value:
                value = None
                break
            value = value[key]
        if value is not None:
            return value
    return None


def normalize_mac(value: str | None) -> str:
    return (value or "").replace(":", "").replace("-", "").lower()


def is_ev_station(device: dict[str, Any]) -> bool:
    text = " ".join(
        str(device.get(key, ""))
        for key in ("model", "name", "deviceType", "typeName", "productLine")
    ).lower()
    if "ev station" in text or "evstation" in text:
        return True

    actions = _first(device, ("type", "supportedActions")) or []
    return any(
        isinstance(action, dict)
        and "charging" in str(action.get("name", "")).lower()
        for action in actions
    )


def summarize_history(
    sessions: list[dict[str, Any]], mac: str | None
) -> dict[str, Any]:
    normalized = normalize_mac(mac)
    rows = [
        row
        for row in sessions
        if normalize_mac(str(row.get("mac", ""))) == normalized
    ]
    rows.sort(key=lambda row: row.get("date") or 0, reverse=True)

    now = datetime.now(timezone.utc).timestamp()

    def energy_since(days: int) -> float:
        cutoff = now - days * 86400
        return sum(
            float(row.get("powerUsage") or 0)
            for row in rows
            if float(row.get("date") or 0) >= cutoff
        )

    return {
        "sessions": len(rows),
        "total_kwh": sum(float(row.get("powerUsage") or 0) for row in rows),
        "energy_7d": energy_since(7),
        "energy_30d": energy_since(30),
        "last": rows[0] if rows else None,
    }


class UniFiEVCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate UniFi Connect EV Station data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: UniFiEVClient,
    ) -> None:
        self.client = client
        self.entry = entry
        self._history: list[dict[str, Any]] = []
        self._history_updated: datetime | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(
                seconds=int(entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL))
            ),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            devices = [d for d in await self.client.get_devices() if is_ev_station(d)]

            now = datetime.now(timezone.utc)
            if (
                self._history_updated is None
                or now - self._history_updated >= timedelta(minutes=5)
            ):
                self._history = await self.client.get_charging_history(limit=1000)
                self._history_updated = now

            result: dict[str, Any] = {}
            for device in devices:
                device_id = str(device.get("id") or device.get("_id") or "")
                if not device_id:
                    continue

                power_stats = await self.client.get_power_stats(device_id, current=True)
                latest = power_stats[-1] if power_stats else {}
                mac = str(device.get("mac") or _first(device, ("shadow", "mac")) or "")

                result[device_id] = {
                    "device": device,
                    "power": latest,
                    "history": summarize_history(self._history, mac),
                }

            return result
        except UniFiEVAuthError as err:
            raise ConfigEntryAuthFailed from err
        except UniFiEVError as err:
            raise UpdateFailed(str(err)) from err

    async def async_run_named_action(self, device_id: str, action_name: str) -> None:
        item = self.data.get(device_id) if self.data else None
        if not item:
            raise UniFiEVError(f"Unknown device {device_id}")

        actions = _first(item["device"], ("type", "supportedActions")) or []
        action = next(
            (
                a
                for a in actions
                if isinstance(a, dict) and a.get("name") == action_name
            ),
            None,
        )
        if not action:
            raise UniFiEVError(
                f"Device does not advertise supported action {action_name!r}"
            )

        await self.client.run_action(device_id, action)
        await self.async_request_refresh()
