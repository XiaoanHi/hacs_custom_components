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
    HEARTBEAT_TIMEOUT,
    RECONNECT_DELAY,
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
                self._notify()
            else:
                try:
                    await self.client.connect(CONNECT_TIMEOUT)
                except asyncio.CancelledError:
                    return
                except Exception:
                    await self._sleep_or_shutdown(RECONNECT_DELAY)
                    continue
                self.connected = True
                self._read_task = asyncio.create_task(
                    self.client.read_loop(idle_timeout=HEARTBEAT_TIMEOUT),
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
