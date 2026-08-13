"""Config flow for TCL T-Cast: manual IP entry or LAN discovery."""
from __future__ import annotations

import asyncio
import logging
import socket
import time
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_ALGORITHM,
    CONF_DEVICE_NAME,
    CONF_MAC,
    CONNECT_TIMEOUT,
    DOMAIN,
    SCAN_TIMEOUT,
    UDP_PORT,
    WOL_BROADCAST,
)
from .tcl_client import TCLClient

_LOGGER = logging.getLogger(__name__)

_SCAN_START = f"1:{int(time.time() * 1000)}:HA:PHONE:1:HA::0:0\0"


async def _scan_tvs(hass: HomeAssistant, timeout: float = SCAN_TIMEOUT):
    """Broadcast UDP 6537 discovery and collect TV responses."""
    loop = hass.loop
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        sock.bind(("", UDP_PORT))
    except OSError:
        try:
            sock.bind(("", 0))
        except OSError:
            sock.close()
            return []
    sock.setblocking(False)
    try:
        sock.sendto(_SCAN_START.encode("utf-8"), (WOL_BROADCAST, UDP_PORT))
    except OSError:
        sock.close()
        return []

    found: list[tuple[str, str]] = []          # (ip, name)
    end = loop.time() + timeout
    while loop.time() < end:
        try:
            data, addr = await loop.sock_recvfrom(sock, 1024)
        except (BlockingIOError, InterruptedError):
            await asyncio.sleep(0.2)
            continue
        except OSError:
            break
        try:
            text = data.decode("utf-8", errors="replace").rstrip("\0")
            parts = text.split(":")
            if len(parts) >= 5 and parts[3] == "TV":
                ip, name = addr[0], parts[2] or addr[0]
                if not any(ip == e[0] for e in found):
                    found.append((ip, name))
        except Exception:
            continue
    sock.close()
    return found


async def _try_connect(host: str) -> dict[str, str] | None:
    """Return handshake device_info on success, else None."""
    client = TCLClient(host)
    try:
        await client.connect(CONNECT_TIMEOUT)
    except Exception:
        return None
    info = dict(client.device_info)
    await client.close()
    return info


class TCLTcastConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Entry menu: manual IP or LAN scan."""
        return self.async_show_menu(step_id="user", menu_options=["manual", "scan"])

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            name = user_input.get(CONF_DEVICE_NAME) or host
            info = await _try_connect(host)
            if info is None:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(self._unique_id(host, info))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_HOST: host,
                        CONF_DEVICE_NAME: name,
                        CONF_MAC: self._normalize_mac(info.get("mac", "")),
                        CONF_ALGORITHM: info.get("algorithm_type", "-1"),
                    },
                )
        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_DEVICE_NAME, default=""): str,
                }
            ),
            errors=errors,
        )

    async def async_step_scan(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is None:
            tvs = await _scan_tvs(self.hass)
            if not tvs:
                return self.async_abort(reason="no_devices_found")
            self._discovered = tvs
            options = {ip: f"{name} ({ip})" for ip, name in tvs}
            return self.async_show_form(
                step_id="scan",
                data_schema=vol.Schema({vol.Required(CONF_HOST): vol.In(options)}),
            )
        host: str = user_input[CONF_HOST]
        name = next(
            (n for ip, n in getattr(self, "_discovered", []) if ip == host), host
        )
        info = await _try_connect(host)
        if info is None:
            return self.async_abort(reason="cannot_connect")
        await self.async_set_unique_id(self._unique_id(host, info))
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=name,
            data={
                CONF_HOST: host,
                CONF_DEVICE_NAME: name,
                CONF_MAC: self._normalize_mac(info.get("mac", "")),
                CONF_ALGORITHM: info.get("algorithm_type", "-1"),
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            info = await _try_connect(host)
            if info is None:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    data_updates={
                        CONF_HOST: host,
                        CONF_MAC: self._normalize_mac(info.get("mac", "")),
                        CONF_ALGORITHM: info.get("algorithm_type", "-1"),
                    },
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    @staticmethod
    def _normalize_mac(mac: str) -> str:
        return mac.replace("&#058", ":").strip()

    @staticmethod
    def _unique_id(host: str, info: dict[str, str]) -> str:
        mac = info.get("mac", "").replace("&#058", ":").strip()
        if mac:
            return f"mac-{mac.lower()}"
        tv_num = info.get("tv_device_num", "")
        if tv_num:
            return f"devnum-{tv_num}"
        return f"ip-{host}"
