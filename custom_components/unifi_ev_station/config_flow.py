from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aiohttp import CookieJar
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import UniFiEVAuthError, UniFiEVClient, UniFiEVError
from .const import (
    CONF_MAX_CURRENT,
    CONF_MIN_INCREASE_INTERVAL,
    CONF_REASSERT_INTERVAL,
    CONF_SCAN_INTERVAL,
    DEFAULT_MAX_CURRENT,
    DEFAULT_MIN_INCREASE_INTERVAL,
    DEFAULT_REASSERT_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)


async def _validate(
    hass, host: str, username: str, password: str, verify_ssl: bool
) -> str | None:
    """Try to log in and list devices. Return an error key, or None if OK."""
    session = async_create_clientsession(
        hass,
        verify_ssl=verify_ssl,
        auto_cleanup=False,
        cookie_jar=CookieJar(unsafe=True, quote_cookie=False),
    )
    client = UniFiEVClient(session, host, username, password)
    try:
        await client.login()
        devices = await client.get_devices()
        if not devices:
            return "no_devices"
    except UniFiEVAuthError:
        return "invalid_auth"
    except UniFiEVError:
        return "cannot_connect"
    except Exception:  # noqa: BLE001 - config flow should return a useful error
        return "cannot_connect"
    finally:
        await session.close()
    return None


class UniFiEVConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return UniFiEVOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].rstrip("/")
            if not host.startswith(("http://", "https://")):
                host = f"https://{host}"
            user_input[CONF_HOST] = host

            error = await _validate(
                self.hass,
                host,
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                user_input[CONF_VERIFY_SSL],
            )
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(host.lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="UniFi EV Station", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default="https://192.168.1.1"): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication after the console rejected the stored login."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            error = await _validate(
                self.hass,
                entry.data[CONF_HOST],
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_USERNAME, default=entry.data.get(CONF_USERNAME, "")
                ): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=schema, errors=errors
        )


class UniFiEVOptionsFlow(OptionsFlow):
    """Tune polling and the charging-current safety limits."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MAX_CURRENT,
                    default=options.get(CONF_MAX_CURRENT, DEFAULT_MAX_CURRENT),
                ): vol.All(vol.Coerce(int), vol.Any(0, vol.Range(min=6, max=80))),
                vol.Required(
                    CONF_MIN_INCREASE_INTERVAL,
                    default=options.get(
                        CONF_MIN_INCREASE_INTERVAL, DEFAULT_MIN_INCREASE_INTERVAL
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=3600)),
                vol.Required(
                    CONF_REASSERT_INTERVAL,
                    default=options.get(
                        CONF_REASSERT_INTERVAL, DEFAULT_REASSERT_INTERVAL
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
