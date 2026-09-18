from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
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




def _session_period_contributions(session: dict[str, Any]) -> tuple[float, float]:
    """Return live session energy attributable to today and this month.

    UniFi's EV_POWER_STATS.meter is cumulative from the start of the charging
    session. For sessions that cross a local day/month boundary we subtract the
    meter value observed at that boundary, so Energy Today/MTD only include the
    energy delivered inside the current period.
    """
    meter = max(float(session.get("meter") or 0.0), 0.0)
    now_local = dt_util.now()
    day_key = now_local.date().isoformat()
    month_key = f"{now_local.year:04d}-{now_local.month:02d}"

    if session.get("day_key") != day_key:
        if session.get("ended"):
            live_today = 0.0
        else:
            # If Home Assistant restarted after midnight during an already
            # active session, we cannot reconstruct the pre-restart midnight
            # meter exactly. Start the new day's contribution from the first
            # meter we observe instead of incorrectly counting yesterday's use.
            session["day_key"] = day_key
            session["day_offset_meter"] = meter
            live_today = 0.0
    else:
        live_today = max(meter - float(session.get("day_offset_meter") or 0.0), 0.0)

    if session.get("month_key") != month_key:
        if session.get("ended"):
            live_month = 0.0
        else:
            session["month_key"] = month_key
            session["month_offset_meter"] = meter
            live_month = 0.0
    else:
        live_month = max(meter - float(session.get("month_offset_meter") or 0.0), 0.0)

    return live_today, live_month

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
        self._live_power_seen: dict[str, datetime] = {}
        # Tracks the live session meter separately from instantaneous telemetry.
        # UniFi only writes a session to chargingHistory after it ends, so this
        # contribution is retained until completed history catches up.
        self._session_energy: dict[str, dict[str, Any]] = {}
        # Persist the post-boundary portion of completed sessions that UniFi
        # chargingHistory attributes entirely to the session's original date.
        self._period_adjustments: dict[str, dict[str, Any]] = {}
        self._period_store: Store[dict[str, Any]] = Store(
            hass,
            1,
            f"{DOMAIN}.{entry.entry_id}.energy_period_adjustments",
        )
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

    async def async_load_period_adjustments(self) -> None:
        """Load persisted day/month split adjustments."""
        stored = await self._period_store.async_load()
        if isinstance(stored, dict):
            self._period_adjustments = {
                str(device_id): dict(values)
                for device_id, values in stored.items()
                if isinstance(values, dict)
            }

    async def _async_save_period_adjustments(self) -> None:
        await self._period_store.async_save(self._period_adjustments)

    def _period_adjustment(self, device_id: str) -> tuple[float, float]:
        """Return persisted split energy for the current local day/month."""
        values = self._period_adjustments.get(device_id, {})
        now_local = dt_util.now()
        day_key = now_local.date().isoformat()
        month_key = f"{now_local.year:04d}-{now_local.month:02d}"
        day_kwh = (
            float(values.get("day_kwh") or 0.0)
            if values.get("day_key") == day_key
            else 0.0
        )
        month_kwh = (
            float(values.get("month_kwh") or 0.0)
            if values.get("month_key") == month_key
            else 0.0
        )
        return day_kwh, month_kwh

    def _record_completed_period_split(
        self, device_id: str, session: dict[str, Any]
    ) -> bool:
        """Retain post-midnight/month energy after history absorbs a session."""
        live_today, live_month = _session_period_contributions(session)
        now_local = dt_util.now()
        day_key = now_local.date().isoformat()
        month_key = f"{now_local.year:04d}-{now_local.month:02d}"
        values = self._period_adjustments.setdefault(device_id, {})
        changed = False

        # A non-zero offset means this session began before the current period.
        # UniFi will place the whole completed history record on the old start
        # date/month, so preserve only the portion delivered in this period.
        if float(session.get("day_offset_meter") or 0.0) > 0 and live_today > 0:
            if values.get("day_key") != day_key:
                values["day_key"] = day_key
                values["day_kwh"] = 0.0
            values["day_kwh"] = float(values.get("day_kwh") or 0.0) + live_today
            changed = True

        if float(session.get("month_offset_meter") or 0.0) > 0 and live_month > 0:
            if values.get("month_key") != month_key:
                values["month_key"] = month_key
                values["month_kwh"] = 0.0
            values["month_kwh"] = float(values.get("month_kwh") or 0.0) + live_month
            changed = True

        return changed

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
                latest = dict(self._live_power.get(device_id, {}))
                seen = self._live_power_seen.get(device_id)

                # EV Station Lite only emits EV_POWER_STATS while actively
                # streaming telemetry. Treat a known charger with no recent
                # stream as idle (0 kW / 0 A) instead of unavailable. This
                # also prevents stale non-zero readings if the stream ends
                # without an explicit streaming=false frame.
                if seen is None or now - seen >= timedelta(seconds=90):
                    latest = {
                        "instantKW": 0.0,
                        "instantA": 0.0,
                        "meter": 0.0,
                        "duration": 0,
                        "streaming": False,
                    }
                    # EV Station Lite may simply stop emitting EV_POWER_STATS
                    # instead of sending an explicit streaming=false frame.
                    # Mark the retained session meter as ended after the same
                    # staleness window so it can be reconciled with history.
                    pending_session = self._session_energy.get(device_id)
                    if pending_session is not None:
                        pending_session["ended"] = True
                elif latest.get("streaming") is False:
                    latest["instantKW"] = 0.0
                    latest["instantA"] = 0.0

                power_supported = True

                mac = str(device.get("mac") or _first(device, ("shadow", "mac")) or "")
                history = summarize_history(self._history, mac)

                pending = self._session_energy.get(device_id)
                if pending and pending.get("ended"):
                    # Once completed charging history increases beyond the
                    # per-device baseline captured for this session, UniFi has
                    # persisted the session. Drop the temporary live meter in
                    # the same coordinator update so it is never double-counted.
                    baseline_total = float(pending.get("baseline_total") or 0.0)
                    meter = float(pending.get("meter") or 0.0)
                    history_gain = float(history["total_kwh"]) - baseline_total
                    threshold = min(max(meter * 0.50, 0.01), max(meter, 0.01))
                    if history_gain >= threshold:
                        adjustment_changed = self._record_completed_period_split(
                            device_id, pending
                        )
                        self._session_energy.pop(device_id, None)
                        pending = None
                        if adjustment_changed:
                            await self._async_save_period_adjustments()

                live_session_kwh = float(pending.get("meter") or 0.0) if pending else 0.0

                # EV_POWER_STATS.meter is cumulative from session start. For a
                # session spanning midnight/month-end, only the meter delta since
                # the local period boundary belongs in Energy Today/MTD.
                live_today = 0.0
                live_month = 0.0
                if pending and live_session_kwh > 0:
                    live_today, live_month = _session_period_contributions(pending)

                day_adjustment, month_adjustment = self._period_adjustment(device_id)

                result[device_id] = {
                    "device": device,
                    "power": latest,
                    "power_supported": power_supported,
                    "history": history,
                    "live_session_kwh": live_session_kwh,
                    "energy_today_live": (
                        float(history["energy_today"])
                        + day_adjustment
                        + live_today
                    ),
                    "energy_month_to_date_live": (
                        float(history["energy_month_to_date"])
                        + month_adjustment
                        + live_month
                    ),
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
        streaming = telemetry.get("streaming") is True
        if telemetry.get("streaming") is False:
            telemetry["instantA"] = 0
            telemetry["instantKW"] = 0

        self._live_power[device_id] = telemetry
        self._live_power_seen[device_id] = datetime.now(timezone.utc)

        # EV_POWER_STATS.meter is the live energy delivered for the current
        # charging session. Keep it independently from instantaneous telemetry
        # because EV Station Lite stops emitting the stream before
        # chargingHistory necessarily contains the completed session.
        meter_raw = telemetry.get("meter")
        started_raw = telemetry.get("startedAt")
        try:
            meter = max(float(meter_raw), 0.0) if meter_raw is not None else None
        except (TypeError, ValueError):
            meter = None
        try:
            started_at = int(started_raw) if started_raw is not None else 0
        except (TypeError, ValueError):
            started_at = 0

        session = self._session_energy.get(device_id)
        new_session = (
            session is None
            or (started_at > 0 and int(session.get("startedAt") or 0) != started_at)
        )
        now_local = dt_util.now()
        current_day_key = now_local.date().isoformat()
        current_month_key = f"{now_local.year:04d}-{now_local.month:02d}"

        if new_session and (streaming or (meter is not None and meter > 0)):
            baseline_total = 0.0
            if self.data and device_id in self.data:
                baseline_total = float(
                    self.data[device_id].get("history", {}).get("total_kwh") or 0.0
                )

            initial_meter = meter or 0.0
            started_local = (
                dt_util.as_local(datetime.fromtimestamp(started_at, tz=timezone.utc))
                if started_at > 0
                else now_local
            )
            session = {
                "meter": initial_meter,
                "startedAt": started_at,
                "baseline_total": baseline_total,
                "ended": False,
                "day_key": current_day_key,
                "day_offset_meter": (
                    0.0 if started_local.date() == now_local.date() else initial_meter
                ),
                "month_key": current_month_key,
                "month_offset_meter": (
                    0.0
                    if (started_local.year, started_local.month)
                    == (now_local.year, now_local.month)
                    else initial_meter
                ),
            }
            self._session_energy[device_id] = session
        elif session is not None:
            previous_meter = float(session.get("meter") or 0.0)

            # Snapshot the cumulative session meter at local day/month rollover.
            # The next meter delta then belongs to the new period instead of
            # being attributed entirely to the day/month when charging started.
            if session.get("day_key") != current_day_key:
                session["day_key"] = current_day_key
                session["day_offset_meter"] = previous_meter
            if session.get("month_key") != current_month_key:
                session["month_key"] = current_month_key
                session["month_offset_meter"] = previous_meter

            if meter is not None:
                # The session meter should be monotonic; guard against a
                # transient lower/empty frame.
                session["meter"] = max(previous_meter, meter)
            if started_at > 0:
                session["startedAt"] = started_at

        if session is not None:
            session["ended"] = not streaming

        if not self.data or device_id not in self.data:
            return

        updated = dict(self.data)
        item = dict(updated[device_id])
        item["power"] = telemetry
        item["power_supported"] = True

        if session is not None:
            live_session_kwh = float(session.get("meter") or 0.0)
            item["live_session_kwh"] = live_session_kwh

            live_today, live_month = _session_period_contributions(session)

            history = item.get("history", {})
            day_adjustment, month_adjustment = self._period_adjustment(device_id)
            item["energy_today_live"] = (
                float(history.get("energy_today") or 0.0)
                + day_adjustment
                + live_today
            )
            item["energy_month_to_date_live"] = (
                float(history.get("energy_month_to_date") or 0.0)
                + month_adjustment
                + live_month
            )

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
