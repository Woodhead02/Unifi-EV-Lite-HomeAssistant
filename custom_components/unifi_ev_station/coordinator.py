from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    UniFiEVAuthError,
    UniFiEVClient,
    UniFiEVError,
)
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


def _find_key(value: Any, wanted: str) -> Any:
    """Recursively return the first value for a key in nested API data."""
    if isinstance(value, dict):
        if wanted in value and value[wanted] is not None:
            return value[wanted]
        for child in value.values():
            found = _find_key(child, wanted)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_key(child, wanted)
            if found is not None:
                return found
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

    now_local = dt_util.now()
    now_timestamp = now_local.timestamp()

    def energy_since(days: int) -> float:
        cutoff = now_timestamp - days * 86400
        return sum(
            float(row.get("powerUsage") or 0)
            for row in rows
            if float(row.get("date") or 0) >= cutoff
        )

    def session_local_datetime(row: dict[str, Any]) -> datetime | None:
        timestamp = float(row.get("date") or 0)
        if timestamp <= 0:
            return None
        return dt_util.as_local(datetime.fromtimestamp(timestamp, tz=timezone.utc))

    energy_today = 0.0
    energy_month_to_date = 0.0
    for row in rows:
        session_dt = session_local_datetime(row)
        if session_dt is None:
            continue
        energy = float(row.get("powerUsage") or 0)
        if session_dt.date() == now_local.date():
            energy_today += energy
        if (session_dt.year, session_dt.month) == (now_local.year, now_local.month):
            energy_month_to_date += energy

    return {
        "sessions": len(rows),
        "total_kwh": sum(float(row.get("powerUsage") or 0) for row in rows),
        "energy_today": energy_today,
        "energy_month_to_date": energy_month_to_date,
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
        self._last_set_max_output: dict[str, int] = {}
        self._live_power: dict[str, dict[str, Any]] = {}
        self._websocket_task: asyncio.Task[None] | None = None

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

                # Live EV telemetry is delivered over the Connect WebSocket as
                # EV_POWER_STATS. The Lite models return HTTP 400 for
                # powerStats?current=true, so do not poll that endpoint here.
                latest = self._live_power.get(device_id, {})
                power_supported = bool(latest)

                mac = str(device.get("mac") or _first(device, ("shadow", "mac")) or "")

                result[device_id] = {
                    "device": device,
                    "power": latest,
                    "power_supported": power_supported,
                    "history": summarize_history(self._history, mac),
                    "last_set_max_output": self._last_set_max_output.get(device_id),
                }

            return result
        except UniFiEVAuthError as err:
            raise ConfigEntryAuthFailed from err
        except UniFiEVError as err:
            raise UpdateFailed(str(err)) from err

    async def async_start_websocket(self) -> None:
        """Start the background EV telemetry listener."""
        if self._websocket_task and not self._websocket_task.done():
            return
        self._websocket_task = self.hass.async_create_task(
            self.client.listen_ev_power_stats(self._async_handle_power_event),
            "UniFi EV Station telemetry",
        )

    async def async_stop_websocket(self) -> None:
        """Stop the background EV telemetry listener."""
        if self._websocket_task is None:
            return
        self._websocket_task.cancel()
        try:
            await self._websocket_task
        except asyncio.CancelledError:
            pass
        self._websocket_task = None

    async def _async_handle_power_event(self, event: dict[str, Any]) -> None:
        """Apply one EV_POWER_STATS WebSocket event to coordinator data."""
        device_id = str(event.get("id") or "")
        if not device_id:
            event_mac = normalize_mac(str(event.get("mac") or ""))
            if self.data and event_mac:
                for candidate_id, item in self.data.items():
                    device_mac = normalize_mac(
                        str(item["device"].get("mac") or _first(item["device"], ("shadow", "mac")) or "")
                    )
                    if device_mac == event_mac:
                        device_id = candidate_id
                        break
        if not device_id:
            return

        telemetry = dict(event)
        if telemetry.get("streaming") is False:
            telemetry["instantA"] = 0
            telemetry["instantKW"] = 0

        self._live_power[device_id] = telemetry

        if not self.data or device_id not in self.data:
            return

        updated = dict(self.data)
        item = dict(updated[device_id])
        item["power"] = telemetry
        item["power_supported"] = True
        updated[device_id] = item
        self.async_set_updated_data(updated)

    async def async_run_named_action(
        self,
        device_id: str,
        action_name: str,
        *,
        args: dict[str, Any] | None = None,
    ) -> None:
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

        await self.client.run_action(device_id, action, args=args)
        if action_name == "set_max_output_amp" and args and "maxOutput" in args:
            self._last_set_max_output[device_id] = int(args["maxOutput"])
        await self.async_request_refresh()
