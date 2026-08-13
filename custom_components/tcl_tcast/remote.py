"""Remote platform: TCL TV remote control entity."""
from __future__ import annotations

import logging

from homeassistant.components.remote import RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

try:  # HA >= 2024.1
    from homeassistant.components.remote import RemoteEntityFeature

    _SUPPORT_COMMANDS = RemoteEntityFeature.COMMANDS
except ImportError:  # HA < 2024.1
    from homeassistant.components.remote import SUPPORT_COMMANDS as _SUPPORT_COMMANDS

from .const import CONF_DEVICE_NAME, DOMAIN, KEY_COMMANDS
from .coordinator import TCLCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the TCL remote entity."""
    coordinator: TCLCoordinator = entry.runtime_data
    async_add_entities([TCLRemoteEntity(coordinator)], update_before_add=True)


class TCLRemoteEntity(RemoteEntity):
    """Remote entity that maps button names to TR_KEY keycodes."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: TCLCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}-remote"
        self._attr_supported_features = _SUPPORT_COMMANDS
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.entry.data.get(CONF_DEVICE_NAME) or coordinator.host,
            manufacturer="TCL",
            model="T-Cast TV",
        )

    @property
    def is_on(self) -> bool:
        return self._coordinator.available

    @property
    def available(self) -> bool:
        return self._coordinator.available

    async def async_added_to_hass(self) -> None:
        self._coordinator.add_listener(self._async_updated)

    async def async_will_remove_from_hass(self) -> None:
        self._coordinator.remove_listener(self._async_updated)

    async def _async_updated(self) -> None:
        self.async_write_ha_state()

    async def async_send_command(self, command, **kwargs) -> None:
        """Send one or more remote commands.

        Supported forms (space-or-list separated):
          power home menu ok back up down left right enter
          vol_up vol_down mute ch_up ch_down source smarttv playback
          0-9 red green yellow blue info
          key:<int>   -> arbitrary TR_KEY keycode
          raw:<text>  -> arbitrary "cmd>>param" protocol message
        """
        client = self._coordinator.client
        commands = command if isinstance(command, (list, tuple)) else [command]
        for cmd in commands:
            await self._handle_command(client, str(cmd))

    async def _handle_command(self, client, cmd: str) -> None:
        cmd = cmd.strip()
        if not cmd:
            return
        if cmd in KEY_COMMANDS:
            await client.key(KEY_COMMANDS[cmd])
        elif cmd.startswith("key:"):
            try:
                await client.key(int(cmd[4:].strip()))
            except ValueError as err:
                raise ServiceValidationError(f"Invalid key code: {cmd}") from err
        elif cmd.startswith("raw:"):
            await client.send_raw(cmd[4:].strip())
        else:
            raise ServiceValidationError(
                f"Unknown remote command '{cmd}'. Use a named button, "
                "'key:<code>' or 'raw:<message>'."
            )
