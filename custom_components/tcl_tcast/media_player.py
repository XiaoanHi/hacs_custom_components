"""Media player platform: TCL TV volume/playback/power controls."""
from __future__ import annotations

import logging

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CMD_SET_SYSTEM_VOLUME,
    CONF_DEVICE_NAME,
    DOMAIN,
    KEY_CH_DOWN,
    KEY_CH_UP,
    KEY_MUTE,
    KEY_POWER,
    KEY_SOURCE,
    KEY_VOL_DOWN,
    KEY_VOL_UP,
    MEDIA_PAUSE,
    MEDIA_PLAY,
    MEDIA_SEEK,
    MEDIA_STOP,
)
from .coordinator import TCLCoordinator

_LOGGER = logging.getLogger(__name__)

_FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.SEEK
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the TCL media player entity."""
    coordinator: TCLCoordinator = entry.runtime_data
    async_add_entities([TCLMediaPlayer(coordinator)], update_before_add=True)


class TCLMediaPlayer(MediaPlayerEntity):
    """Media player controlling a TCL TV over the private protocol."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: TCLCoordinator) -> None:
        self._coordinator = coordinator
        self._media_state = MediaPlayerState.IDLE
        self._attr_unique_id = f"{coordinator.entry.entry_id}-media_player"
        self._attr_supported_features = _FEATURES
        self._attr_source_list = ["SOURCE"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.entry.data.get(CONF_DEVICE_NAME) or coordinator.host,
            manufacturer="TCL",
            model="T-Cast TV",
        )

    @property
    def state(self) -> MediaPlayerState:
        if not self.available:
            return MediaPlayerState.UNAVAILABLE
        return self._media_state

    @property
    def available(self) -> bool:
        return self._coordinator.available

    async def async_added_to_hass(self) -> None:
        self._coordinator.add_listener(self._async_updated)

    async def async_will_remove_from_hass(self) -> None:
        self._coordinator.remove_listener(self._async_updated)

    async def _async_updated(self) -> None:
        self.async_write_ha_state()

    # -- power ---------------------------------------------------------- #
    async def async_turn_on(self) -> None:
        """Turn on the TV. If it's off (no link) wake it with WOL first."""
        if self._coordinator.available:
            await self._coordinator.client.key(KEY_POWER)
        elif self._coordinator.mac:
            _LOGGER.debug("Waking TV via WOL (mac=%s)", self._coordinator.mac)
            await self._coordinator.client.wol_wake(self._coordinator.mac)
        else:
            _LOGGER.warning("TV offline and no MAC configured for WOL")

    async def async_turn_off(self) -> None:
        if self._coordinator.available:
            await self._coordinator.client.key(KEY_POWER)

    # -- volume --------------------------------------------------------- #
    async def async_set_volume_level(self, volume: float) -> None:
        await self._coordinator.client.send_raw(
            f"{CMD_SET_SYSTEM_VOLUME}>>{max(0, min(100, int(volume * 100)))}"
        )

    async def async_volume_up(self) -> None:
        await self._coordinator.client.key(KEY_VOL_UP)

    async def async_volume_down(self) -> None:
        await self._coordinator.client.key(KEY_VOL_DOWN)

    async def async_mute_volume(self, mute: bool) -> None:
        await self._coordinator.client.key(KEY_MUTE)

    # -- transport ------------------------------------------------------ #
    async def async_media_play(self) -> None:
        await self._coordinator.client.send_raw(f"{MEDIA_PLAY}")
        self._media_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    async def async_media_pause(self) -> None:
        await self._coordinator.client.send_raw(f"{MEDIA_PAUSE}")
        self._media_state = MediaPlayerState.PAUSED
        self.async_write_ha_state()

    async def async_media_stop(self) -> None:
        await self._coordinator.client.send_raw(f"{MEDIA_STOP}")
        self._media_state = MediaPlayerState.IDLE
        self.async_write_ha_state()

    async def async_media_play_pause(self) -> None:
        if self._media_state == MediaPlayerState.PLAYING:
            await self.async_media_pause()
        else:
            await self.async_media_play()

    async def async_media_seek(self, position: float) -> None:
        # HA passes seconds; the TCL protocol expects milliseconds.
        await self._coordinator.client.send_raw(
            f"{MEDIA_SEEK}>>{int(position * 1000)}"
        )

    # -- channels / source ---------------------------------------------- #
    async def async_channel_up(self) -> None:
        await self._coordinator.client.key(KEY_CH_UP)

    async def async_channel_down(self) -> None:
        await self._coordinator.client.key(KEY_CH_DOWN)

    async def async_select_source(self, source: str) -> None:
        # The TCL SOURCE key cycles inputs; we can't enumerate names.
        await self._coordinator.client.key(KEY_SOURCE)
