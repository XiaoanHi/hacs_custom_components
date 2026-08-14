"""TCL T-Cast integration entry point."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, SOURCE_LIST
from .coordinator import TCLCoordinator

PLATFORMS = ["remote", "media_player", "select", "button"]

_LOGGER = logging.getLogger(__name__)

SERVICE_SEND_KEY = "send_key"
SERVICE_SEND_RAW = "send_raw"
SERVICE_SET_CURRENT_SOURCE = "set_current_source"
ATTR_KEYCODE = "keycode"
ATTR_TEXT = "text"
ATTR_SOURCE = "source"
ATTR_ENTRY_ID = "entry_id"

_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
    }
)


def _coordinator_for(hass: HomeAssistant, call: ServiceCall) -> TCLCoordinator:
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(f"No {DOMAIN} config entries")
    entry_id = call.data.get(ATTR_ENTRY_ID)
    entry = next((e for e in entries if e.entry_id == entry_id), entries[0])
    return entry.runtime_data


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration's global services (once)."""

    async def _handle_send_key(call: ServiceCall) -> None:
        coordinator = _coordinator_for(hass, call)
        if not coordinator.available:
            raise ServiceValidationError("TCL TV is not connected")
        await coordinator.client.key(int(call.data[ATTR_KEYCODE]))

    async def _handle_send_raw(call: ServiceCall) -> None:
        coordinator = _coordinator_for(hass, call)
        if not coordinator.available:
            raise ServiceValidationError("TCL TV is not connected")
        await coordinator.client.send_raw(call.data[ATTR_TEXT])

    async def _handle_set_current_source(call: ServiceCall) -> None:
        await _coordinator_for(hass, call).async_set_current_source(
            call.data[ATTR_SOURCE]
        )

    hass.services.async_register(
        DOMAIN, SERVICE_SEND_KEY, _handle_send_key, vol.Schema(_SERVICE_SCHEMA.extend(
            {vol.Required(ATTR_KEYCODE): vol.Coerce(int)}
        ))
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_RAW, _handle_send_raw, vol.Schema(_SERVICE_SCHEMA.extend(
            {vol.Required(ATTR_TEXT): cv.string}
        ))
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_CURRENT_SOURCE, _handle_set_current_source,
        vol.Schema(_SERVICE_SCHEMA.extend(
            {vol.Required(ATTR_SOURCE): vol.In(SOURCE_LIST)}
        )),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a TCL TV from a config entry."""
    coordinator = TCLCoordinator(hass, entry)
    await coordinator.async_start()
    # runtime_data is the modern way; hass.data kept as a fallback for older HA.
    entry.runtime_data = coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Tear down a TCL TV entry."""
    coordinator: TCLCoordinator = entry.runtime_data
    await coordinator.async_unload()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded
