from __future__ import annotations

from aiohttp import CookieJar

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import UniFiEVClient
from .const import DEFAULT_VERIFY_SSL, PLATFORMS
from .coordinator import UniFiEVCoordinator


type UniFiEVConfigEntry = ConfigEntry[UniFiEVCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: UniFiEVConfigEntry) -> bool:
    session = async_create_clientsession(
        hass,
        verify_ssl=entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
        cookie_jar=CookieJar(unsafe=True, quote_cookie=False),
    )
    client = UniFiEVClient(
        session,
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinator = UniFiEVCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await coordinator.async_start_websocket()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: UniFiEVConfigEntry) -> bool:
    await entry.runtime_data.async_stop_websocket()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
