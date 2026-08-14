"""Select platform: TCL input-source selector (one-tap HDMI switching)."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_NAME, DOMAIN, SOURCE_LIST
from .coordinator import TCLCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the TCL source selector entity."""
    coordinator: TCLCoordinator = entry.runtime_data
    async_add_entities([TCLSourceSelect(coordinator)], update_before_add=True)


class TCLSourceSelect(SelectEntity):
    """Dropdown to switch the TV input (TV / HDMI1 / HDMI2 / HDMI3)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: TCLCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}-source"
        self._attr_translation_key = "source"
        self._attr_options = list(SOURCE_LIST)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.entry.data.get(CONF_DEVICE_NAME) or coordinator.host,
            manufacturer="TCL",
            model="T-Cast TV",
        )

    @property
    def current_option(self) -> str | None:
        return self._coordinator.current_source

    @property
    def available(self) -> bool:
        return self._coordinator.available

    async def async_select_option(self, option: str) -> None:
        if not self.available:
            raise ServiceValidationError("TCL TV is not connected")
        await self._coordinator.async_select_source(option)

    async def async_added_to_hass(self) -> None:
        self._coordinator.add_listener(self._async_updated)

    async def async_will_remove_from_hass(self) -> None:
        self._coordinator.remove_listener(self._async_updated)

    def _async_updated(self) -> None:
        self.async_write_ha_state()
