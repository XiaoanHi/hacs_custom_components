"""Connection coordinator: keeps the TCL TV link alive and notifies entities."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_HOST,
    CONF_MAC,
    CONNECT_TIMEOUT,
    HEARTBEAT_INTERVAL,
    KEY_DOWN,
    KEY_OK,
    KEY_SOURCE,
    KEY_UP,
    RECONNECT_DELAY,
    SOURCE_LIST,
)
from .tcl_client import TCLClient

_LOGGER = logging.getLogger(__name__)

Listener = Callable[[], None]


class TCLCoordinator:
    """Owns the TCLClient connection; auto-reconnects and pushes state changes.

    Entities subscribe via :meth:`add_listener` and re-render on notify.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.host: str = entry.data[CONF_HOST]
        self.mac: str = entry.data.get(CONF_MAC, "")

        self.client = TCLClient(
            host=self.host,
            phone_name="HA-TCast",
            uuid=str(entry.entry_id),
        )
        self.connected = False
        self._current_source = SOURCE_LIST[0]  # input the SOURCE key cycles from
        self._listeners: list[Listener] = []
        self._run_task: asyncio.Task | None = None
        self._read_task: asyncio.Task | None = None
        self._hb_task: asyncio.Task | None = None
        self._shutdown = False

    # -- lifecycle ------------------------------------------------------ #
    async def async_start(self) -> None:
        self._shutdown = False
        self._run_task = asyncio.create_task(self._run(), name="tcl_tcast_connect")

    async def async_unload(self) -> None:
        self._shutdown = True
        tasks = [t for t in (self._run_task, self._read_task, self._hb_task) if t]
        for task in tasks:
            task.cancel()
        await self.client.close()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._listeners.clear()

    async def _run(self) -> None:
        """Connect loop: connect -> monitor read task -> reconnect on drop."""
        while not self._shutdown:
            if self.connected:
                if self._read_task:
                    try:
                        await self._read_task
                    except asyncio.CancelledError:
                        return
                self.connected = False
                self._cancel_aux()
                await self.client.close()
                _LOGGER.info("Disconnected from TCL TV at %s", self.host)
                self._notify()
            else:
                try:
                    await self.client.connect(CONNECT_TIMEOUT)
                except asyncio.CancelledError:
                    return
                except Exception as err:
                    _LOGGER.warning("Connect to TCL TV at %s failed: %s", self.host, err)
                    await self._sleep_or_shutdown(RECONNECT_DELAY)
                    continue
                self.connected = True
                self._read_task = asyncio.create_task(
                    self.client.read_loop(),
                    name="tcl_tcast_read",
                )
                self._hb_task = asyncio.create_task(
                    self._heartbeat_loop(), name="tcl_tcast_heartbeat"
                )
                _LOGGER.info("Connected to TCL TV at %s", self.host)
                self._notify()

    async def _heartbeat_loop(self) -> None:
        while self.connected and not self._shutdown:
            try:
                await self.client.heartbeat()
            except Exception:
                break
            await self._sleep_or_shutdown(HEARTBEAT_INTERVAL)

    async def _sleep_or_shutdown(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            self._shutdown = True
            raise

    def _cancel_aux(self) -> None:
        for task in (self._read_task, self._hb_task):
            if task:
                task.cancel()
        self._read_task = None
        self._hb_task = None

    # -- state ---------------------------------------------------------- #
    @property
    def current_source(self) -> str:
        return self._current_source

    async def async_select_source(self, source: str) -> None:
        """Switch input via the on-screen input menu.

        On TCL TVs the SOURCE key opens an input menu whose focus starts on
        the *current* input. We navigate UP/DOWN from the tracked current
        input to the target and confirm with OK. Keep the tracked current
        input accurate with the ``tcl_tcast.set_current_source`` service.
        """
        target = (source or "").strip().upper()
        if target not in SOURCE_LIST:
            raise ValueError(f"Unknown source '{source}'")
        cur_idx = SOURCE_LIST.index(self._current_source)
        tgt_idx = SOURCE_LIST.index(target)
        if cur_idx == tgt_idx:
            return  # already on the requested input
        await self.client.key(KEY_SOURCE)      # open the input menu
        await asyncio.sleep(1.0)               # let the menu fully render
        if tgt_idx > cur_idx:
            for _ in range(tgt_idx - cur_idx):
                await self.client.key(KEY_DOWN)
                await asyncio.sleep(0.3)
        else:
            for _ in range(cur_idx - tgt_idx):
                await self.client.key(KEY_UP)
                await asyncio.sleep(0.3)
        await asyncio.sleep(0.3)
        await self.client.key(KEY_OK)          # confirm selection
        self._current_source = target
        self._notify()

    async def async_set_current_source(self, source: str) -> None:
        """Calibrate the tracked current input (does NOT switch the TV).

        Call this once the TV is actually on a known input so subsequent
        source switches navigate from the right menu position.
        """
        target = (source or "").strip().upper()
        if target not in SOURCE_LIST:
            raise ValueError(f"Unknown source '{source}'")
        self._current_source = target
        self._notify()

    @property
    def available(self) -> bool:
        return self.connected

    # -- listeners ------------------------------------------------------ #
    def add_listener(self, listener: Listener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Listener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify(self) -> None:
        for listener in self._listeners:
            try:
                listener()
            except Exception:
                _LOGGER.debug("listener error", exc_info=True)
