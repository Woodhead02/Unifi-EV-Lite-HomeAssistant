from __future__ import annotations

from typing import Any

from aiohttp import CookieJar
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import UniFiEVAuthError, UniFiEVClient, UniFiEVError
from .const import DEFAULT_VERIFY_SSL, DOMAIN


class UniFiEVConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].rstrip("/")
            if not host.startswith(("http://", "https://")):
                host = f"https://{host}"
            user_input[CONF_HOST] = host

            session = async_create_clientsession(
                self.hass,
                verify_ssl=user_input[CONF_VERIFY_SSL],
                auto_cleanup=False,
                cookie_jar=CookieJar(unsafe=True, quote_cookie=False),
            )
            client = UniFiEVClient(
                session,
                host,
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            try:
                await client.login()
                devices = await client.get_devices()
                if not devices:
                    errors["base"] = "no_devices"
                else:
                    await self.async_set_unique_id(host.lower())
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title="UniFi EV Station", data=user_input)
            except UniFiEVAuthError:
                errors["base"] = "invalid_auth"
            except UniFiEVError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - config flow should return a useful error
                errors["base"] = "cannot_connect"
            finally:
                await session.close()

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default="https://192.168.1.1"): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
