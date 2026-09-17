from __future__ import annotations

import base64
import json
from typing import Any

from aiohttp import ClientResponse, ClientSession

from .const import CONNECT_BASE


class UniFiEVError(Exception):
    """Base API error."""


class UniFiEVAuthError(UniFiEVError):
    """Authentication failed."""


class UniFiEVPermissionError(UniFiEVError):
    """Request is not permitted."""


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

        # Fallback: current UniFi OS TOKEN/UOS_TOKEN JWTs commonly carry csrfToken.
        cookies = self.session.cookie_jar.filter_cookies(self.host)
        for name in ("TOKEN", "UOS_TOKEN"):
            morsel = cookies.get(name)
            if morsel and (csrf := self._csrf_from_cookie(morsel.value)):
                self.csrf_token = csrf
                return

    async def login(self) -> None:
        """Authenticate with a local UniFi OS account."""
        # Seed any initial CSRF state exposed by the console shell.
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
                return await self.request(
                    method, path, retry_auth=False, **kwargs
                )
            if response.status == 401:
                raise UniFiEVAuthError("UniFi OS session is not authenticated")
            if response.status == 403:
                raise UniFiEVPermissionError(
                    f"UniFi OS denied {method} {path}: {text[:300]}"
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
        self, device_id: str, *, current: bool = True, interval: str = "15m"
    ) -> list[dict[str, Any]]:
        payload = await self.request(
            "GET",
            f"{CONNECT_BASE}/devices/{device_id}/powerStats",
            params={"interval": interval, "current": str(current).lower()},
        )
        return self._extract_collection(payload)

    async def get_charging_history(self, limit: int = 1000) -> list[dict[str, Any]]:
        payload = await self.request(
            "GET",
            f"{CONNECT_BASE}/stats/evs/chargingHistory",
            params={"offset": 0, "limit": limit},
        )
        return self._extract_collection(payload)

    async def run_action(self, device_id: str, action: dict[str, Any]) -> Any:
        body = {
            key: value
            for key, value in action.items()
            if key in {"id", "name", "category"} and value is not None
        }
        body["args"] = action.get("args") or {}
        return await self.request(
            "PATCH",
            f"{CONNECT_BASE}/devices/{device_id}/status",
            json=body,
        )

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
