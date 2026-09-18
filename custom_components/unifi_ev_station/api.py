from __future__ import annotations

import asyncio
import base64
import inspect
import json
import logging
from collections.abc import Callable
from typing import Any

from aiohttp import (
    ClientResponse,
    ClientSession,
    WSMsgType,
    WSServerHandshakeError,
)

from .const import CONNECT_BASE

_LOGGER = logging.getLogger(__name__)


class UniFiEVError(Exception):
    """Base API error."""


class UniFiEVAuthError(UniFiEVError):
    """Authentication failed."""


class UniFiEVPermissionError(UniFiEVError):
    """Request is not permitted."""


class UniFiEVUnsupportedFeatureError(UniFiEVError):
    """The device does not support an optional API feature."""


class UniFiEVClient:
    """Small UniFi OS/Connect client using local session authentication."""

    def __init__(
        self,
        session: ClientSession,
        host: str,
        username: str,
        password: str,
    ) -> None:
        self.session = session
        self.host = host.rstrip("/")
        self.username = username
        self.password = password
        self.csrf_token: str | None = None
        self._logged_in = False

    @staticmethod
    def _csrf_from_cookie(token: str | None) -> str | None:
        if not token:
            return None
        try:
            parts = token.split(".")
            if len(parts) < 2:
                return None
            payload = parts[1] + "=" * (-len(parts[1]) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(payload).decode())
            return decoded.get("csrfToken")
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _update_csrf(self, response: ClientResponse) -> None:
        token = (
            response.headers.get("X-Updated-CSRF-Token")
            or response.headers.get("X-CSRF-Token")
        )
        if token:
            self.csrf_token = token
            return

        cookies = self.session.cookie_jar.filter_cookies(self.host)
        for name in ("TOKEN", "UOS_TOKEN"):
            morsel = cookies.get(name)
            if morsel and (csrf := self._csrf_from_cookie(morsel.value)):
                self.csrf_token = csrf
                return

    async def login(self) -> None:
        """Authenticate with a local UniFi OS account."""
        async with self.session.get(self.host, allow_redirects=False) as response:
            self._update_csrf(response)
            await response.read()

        headers = {"Content-Type": "application/json"}
        if self.csrf_token:
            headers["X-CSRF-Token"] = self.csrf_token

        payload = {
            "username": self.username,
            "password": self.password,
            "remember": True,
            "rememberMe": True,
        }

        async with self.session.post(
            f"{self.host}/api/auth/login",
            json=payload,
            headers=headers,
        ) as response:
            text = await response.text()
            self._update_csrf(response)
            if response.status in (401, 403, 499):
                raise UniFiEVAuthError(
                    f"UniFi OS login failed (HTTP {response.status}): {text[:300]}"
                )
            if response.status >= 400:
                raise UniFiEVError(
                    f"UniFi OS login failed (HTTP {response.status}): {text[:300]}"
                )

        self._logged_in = True

    async def request(
        self,
        method: str,
        path: str,
        *,
        retry_auth: bool = True,
        **kwargs: Any,
    ) -> Any:
        if not self._logged_in:
            await self.login()

        headers = dict(kwargs.pop("headers", {}))
        if self.csrf_token:
            headers["X-CSRF-Token"] = self.csrf_token

        async with self.session.request(
            method,
            f"{self.host}{path}",
            headers=headers,
            **kwargs,
        ) as response:
            text = await response.text()
            self._update_csrf(response)

            if response.status == 401 and retry_auth:
                self._logged_in = False
                await self.login()
                return await self.request(method, path, retry_auth=False, **kwargs)
            if response.status == 401:
                raise UniFiEVAuthError("UniFi OS session is not authenticated")
            if response.status == 403:
                raise UniFiEVPermissionError(
                    f"UniFi OS denied {method} {path}: {text[:300]}"
                )
            if (
                response.status == 400
                and "does not support power insight" in text.lower()
            ):
                raise UniFiEVUnsupportedFeatureError(
                    f"Device does not support power insight for {path}"
                )
            if response.status >= 400:
                raise UniFiEVError(
                    f"HTTP {response.status} for {method} {path}: {text[:300]}"
                )
            if not text:
                return None
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text

    async def get_devices(self) -> list[dict[str, Any]]:
        payload = await self.request("GET", f"{CONNECT_BASE}/devices")
        return self._extract_collection(payload)

    async def get_power_stats(
        self, device_id: str, *, current: bool = False, interval: str = "15m"
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Return historical Connect power statistics when supported."""
        payload = await self.request(
            "GET",
            f"{CONNECT_BASE}/devices/{device_id}/powerStats",
            params={"interval": interval, "current": str(current).lower()},
        )

        data: Any = payload
        if isinstance(payload, dict) and "data" in payload:
            data = payload.get("data")

        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return {}

    async def get_charging_history(self, limit: int = 1000) -> list[dict[str, Any]]:
        payload = await self.request(
            "GET",
            f"{CONNECT_BASE}/stats/evs/chargingHistory",
            params={"offset": 0, "limit": limit},
        )
        return self._extract_collection(payload)

    async def run_action(
        self,
        device_id: str,
        action: dict[str, Any],
        *,
        args: dict[str, Any] | None = None,
    ) -> Any:
        body = {
            key: value
            for key, value in action.items()
            if key in {"id", "name", "category"} and value is not None
        }
        body["args"] = args if args is not None else (action.get("args") or {})
        return await self.request(
            "PATCH",
            f"{CONNECT_BASE}/devices/{device_id}/status",
            json=body,
        )

    @property
    def websocket_url(self) -> str:
        """Return the local Connect WebSocket endpoint."""
        if self.host.startswith("https://"):
            base = "wss://" + self.host[len("https://") :]
        elif self.host.startswith("http://"):
            base = "ws://" + self.host[len("http://") :]
        else:
            base = self.host
        return f"{base}/proxy/connect/"

    @staticmethod
    def decode_websocket_records(data: bytes) -> list[Any]:
        """Decode UniFi Connect's binary record envelope.

        Observed framing is an 8-byte header followed by a payload:
        byte 0: record kind, byte 1: encoding, bytes 2-7: big-endian length.
        JSON records use encoding 1.
        """
        records: list[Any] = []
        offset = 0
        while offset + 8 <= len(data):
            _kind = data[offset]
            _encoding = data[offset + 1]
            length = int.from_bytes(data[offset + 2 : offset + 8], "big")
            offset += 8
            if length < 0 or offset + length > len(data):
                _LOGGER.debug("Ignoring malformed Connect WebSocket record")
                break
            payload = data[offset : offset + length]
            offset += length
            try:
                records.append(json.loads(payload.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                _LOGGER.debug("Ignoring non-JSON Connect WebSocket record")
        return records

    @staticmethod
    def extract_ev_power_events(records: list[Any]) -> list[dict[str, Any]]:
        """Extract EV power-stat payloads from decoded WebSocket records."""
        events: list[dict[str, Any]] = []
        names = {"EV_POWER_STATS", "MULTI_EV_POWER_STATS", "WS_MULTI_EV_POWER_STATS"}

        for index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            if record.get("type") != "event" or record.get("name") not in names:
                continue
            if index + 1 >= len(records):
                continue

            payload = records[index + 1]
            if isinstance(payload, dict):
                # Some envelopes wrap event data in a data property.
                nested = payload.get("data")
                if isinstance(nested, dict):
                    events.append(nested)
                elif isinstance(nested, list):
                    events.extend(item for item in nested if isinstance(item, dict))
                else:
                    events.append(payload)
            elif isinstance(payload, list):
                events.extend(item for item in payload if isinstance(item, dict))

        return events

    async def listen_ev_power_stats(
        self,
        callback: Callable[[dict[str, Any]], Any],
    ) -> None:
        """Maintain the Connect WebSocket and emit EV_POWER_STATS events.

        This coroutine is intended to run as a Home Assistant background task.
        It reconnects automatically until cancelled.
        """
        backoff = 2
        while True:
            try:
                if not self._logged_in:
                    await self.login()

                async with self.session.ws_connect(
                    self.websocket_url,
                    origin=self.host,
                    heartbeat=30,
                    autoping=True,
                    autoclose=True,
                ) as websocket:
                    _LOGGER.debug("Connected to UniFi Connect EV telemetry WebSocket")
                    backoff = 2

                    async for message in websocket:
                        events: list[dict[str, Any]] = []
                        if message.type == WSMsgType.BINARY:
                            records = self.decode_websocket_records(message.data)
                            events = self.extract_ev_power_events(records)
                        elif message.type == WSMsgType.TEXT:
                            try:
                                decoded = json.loads(message.data)
                            except json.JSONDecodeError:
                                decoded = None
                            if isinstance(decoded, dict):
                                if decoded.get("name") in {
                                    "EV_POWER_STATS",
                                    "MULTI_EV_POWER_STATS",
                                    "WS_MULTI_EV_POWER_STATS",
                                }:
                                    payload = decoded.get("data")
                                    if isinstance(payload, dict):
                                        events = [payload]
                                    elif isinstance(payload, list):
                                        events = [
                                            item
                                            for item in payload
                                            if isinstance(item, dict)
                                        ]
                        elif message.type in (
                            WSMsgType.CLOSE,
                            WSMsgType.CLOSED,
                            WSMsgType.ERROR,
                        ):
                            break

                        for event in events:
                            result = callback(event)
                            if inspect.isawaitable(result):
                                await result

            except asyncio.CancelledError:
                raise
            except WSServerHandshakeError as err:
                if err.status in (401, 403):
                    self._logged_in = False
                _LOGGER.warning(
                    "UniFi Connect telemetry WebSocket handshake failed (HTTP %s); retrying",
                    err.status,
                )
            except (UniFiEVError, OSError) as err:
                _LOGGER.warning(
                    "UniFi Connect telemetry WebSocket disconnected: %s; retrying",
                    err,
                )
            except Exception:
                _LOGGER.exception("Unexpected UniFi Connect telemetry WebSocket error")

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    @staticmethod
    def _extract_collection(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("data", "devices", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []
