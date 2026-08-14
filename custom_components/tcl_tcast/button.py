"""Button platform: one one-tap source-switch button per input (HDMI1/2)."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_NAME, DOMAIN, SOURCE_BUTTONS
from .coordinator import TCLCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one source-switch button per configured input."""
    coordinator: TCLCoordinator = entry.runtime_data
    async_add_entities(
        [TCLSourceButton(coordinator, source) for source in SOURCE_BUTTONS],
        update_before_add=True,
    )


class TCLSourceButton(ButtonEntity):
    """A button that switches the TV to one fixed input."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: TCLCoordinator, source: str) -> None:
        self._coordinator = coordinator
        self._source = source
        self._attr_unique_id = f"{coordinator.entry.entry_id}-source-{source.lower()}"
        self._attr_name = source
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.entry.data.get(CONF_DEVICE_NAME) or coordinator.host,
            manufacturer="TCL",
            model="T-Cast TV",
        )

    @property
    def available(self) -> bool:
        return self._coordinator.available

    async def async_press(self) -> None:
        if not self.available:
            raise ServiceValidationError("TCL TV is not connected")
        await self._coordinator.async_select_source(self._source)
