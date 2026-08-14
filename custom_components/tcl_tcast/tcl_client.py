"""Asyncio protocol client for the TCL T-Cast private protocol.

Implements the reverse-engineered wire format (see ANALYSIS/docs/03, 05):

    TCP 6553, frame = [4-byte big-endian length][UTF-8 "cmd>>param..."]
    algorithmType == 1  ->  AES-128/CBC/PKCS7 (key/iv from const.py)
    Handshake cmd 159, heartbeat cmd 150 (always sent in plaintext)
    WOL magic packet on UDP 255.255.255.255:7778

Uses only asyncio + `cryptography` (bundled with Home Assistant), no extra
requirements.
"""
from __future__ import annotations

import asyncio
import logging
import socket
import struct
from typing import Awaitable, Callable

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .const import (
    AES_IV,
    AES_KEY,
    CMD_GET_CLIENTTYPE,
    CMD_ISONLINE,
    CMD_KEY,
    CMD_MOUSE,
    CMD_SNAP_SHOT,
    TCP_PORT,
    WOL_BROADCAST,
    WOL_PORT,
)

_LOGGER = logging.getLogger(__name__)

# Handshake response fields (0-indexed), see docs/03-tcp-command.md
_HANDSHAKE_FIELDS = (
    "client_type",
    "app_version",        # "code:name"
    "software_version",
    "tv_device_num",
    "mac",
    "algorithm_type",
    "bluetooth_mac",
    "tv_type",
    "tv_store",
    "shake_function_code",
    "tv_language",
    "sn_code",
    "client_code",
    "country_code",
    "p2p_mac",
    "active_mac",
    "tv_device_id",
    "tv_net_ip",
)

MessageCallback = Callable[[str], Awaitable[None]]


def _pkcs7_pad(data: bytes, block: int = 16) -> bytes:
    pad_len = block - (len(data) % block)
    return data + bytes([pad_len]) * pad_len


def _pkcs7_unpad(data: bytes, block: int = 16) -> bytes:
    if not data:
        return data
    pad_len = data[-1]
    if pad_len < 1 or pad_len > block:
        return data
    return data[:-pad_len]


class TCLClient:
    """One TCL TV control connection (single host)."""

    def __init__(
        self,
        host: str,
        phone_name: str = "HA-TCast",
        uuid: str = "",
        on_message: MessageCallback | None = None,
    ) -> None:
        self.host = host
        self.phone_name = phone_name
        self.uuid = uuid
        self.on_message = on_message

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self.algorithm_type = -1          # -1 plaintext, 1 AES
        self.device_info: dict[str, str] = {}
        self.connected = False
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # connection / handshake
    # ------------------------------------------------------------------ #
    async def connect(self, timeout: float = 10.0) -> None:
        """Open TCP, run the cmd-159 handshake, set algorithm_type.

        Both the TCP connect *and* the handshake are bounded by ``timeout``,
        otherwise a peer that accepts the connection but never replies would
        hang ``connect()`` forever (stalling reconnects and the config flow).
        """
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, TCP_PORT), timeout
        )
        try:
            await asyncio.wait_for(self._handshake(), timeout)
            self.connected = True
        except Exception:
            await self.close()
            raise

    async def _handshake(self) -> None:
        """Cmd-159 handshake; the frame is always plaintext.

        Some TV firmwares already encrypt the handshake reply (or push
        unrelated frames first). Try plaintext, then AES, until we see 159.
        """
        try:
            self._writer.set_tcp_nodelay(True)
        except AttributeError:  # Python < 3.11
            pass
        self._enable_keepalive()
        await self._send(
            f"{CMD_GET_CLIENTTYPE}>>{self.phone_name}>>1>>{self.uuid}>>1",
            ignore_alg=True,
        )
        for _ in range(3):
            payload = await self._read_payload()
            text = self._decode_handshake(payload)
            if text is not None:
                self._parse_handshake(text)
                return
        _LOGGER.warning(
            "Could not parse a valid handshake response from %s", self.host
        )

    def _decode_handshake(self, payload: bytes) -> str | None:
        prefix = f"{CMD_GET_CLIENTTYPE}>>"
        candidates = [payload]
        # Only try AES on AES-sized data; a plaintext frame isn't a valid
        # ciphertext length and would raise.
        if self.algorithm_type == -1 and len(payload) % 16 == 0:
            try:
                candidates.append(self._decrypt(payload))
            except Exception:
                pass
        for cand in candidates:
            try:
                text = cand.decode("utf-8", errors="replace")
            except Exception:
                continue
            if text.startswith(prefix):
                return text
        return None

    def _enable_keepalive(self) -> None:
        """Let the OS detect a powered-off TV instead of relying on silence.

        The TV may stay TCP-silent even while online (e.g. if it does not
        reply to our heartbeat), so we must not use a read timeout to judge
        it offline. TCP keepalive probes report a dead connection from the
        network stack. Tuning knobs are Linux-only; ignore unsupported opts.
        """
        sock = None
        try:
            sock = self._writer.transport.get_extra_info("socket")
        except Exception:
            return
        if sock is None:
            return
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            return
        for opt_name, val in (("TCP_KEEPIDLE", 30), ("TCP_KEEPINTVL", 10), ("TCP_KEEPCNT", 6)):
            if hasattr(socket, opt_name):
                try:
                    sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, opt_name), val)
                except OSError:
                    pass

    def _parse_handshake(self, resp: str) -> None:
        parts = resp.split(">>")
        if not parts or parts[0] != str(CMD_GET_CLIENTTYPE):
            _LOGGER.warning("Unexpected handshake response: %r", resp[:80])
            return
        for idx, name in enumerate(_HANDSHAKE_FIELDS):
            pos = idx + 1
            if len(parts) > pos:
                self.device_info[name] = parts[pos]
        alg = self.device_info.get("algorithm_type", "-1")
        self.algorithm_type = 1 if alg == "1" else -1
        _LOGGER.debug(
            "handshake ok: client=%s mac=%s alg=%s",
            self.device_info.get("client_type"),
            self.device_info.get("mac"),
            self.algorithm_type,
        )

    async def close(self) -> None:
        self.connected = False
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            self._writer = None
        self._reader = None

    # ------------------------------------------------------------------ #
    # framing / crypto
    # ------------------------------------------------------------------ #
    async def _send(self, text: str, ignore_alg: bool = False) -> None:
        if self._writer is None or self._writer.is_closing():
            raise ConnectionError("TCL TV is not connected")
        payload = text.encode("utf-8")
        if self.algorithm_type == 1 and not ignore_alg:
            payload = self._encrypt(payload)
        frame = struct.pack(">I", len(payload)) + payload
        async with self._lock:
            self._writer.write(frame)
            await self._writer.drain()

    async def _read_payload(self, timeout: float | None = None) -> bytes:
        async def _read() -> bytes:
            header = await self._reader.readexactly(4)
            (length,) = struct.unpack(">I", header)
            return await self._reader.readexactly(length)

        if timeout is not None:
            return await asyncio.wait_for(_read(), timeout)
        return await _read()

    async def _read_frame(self, timeout: float | None = None) -> str:
        payload = await self._read_payload(timeout)
        if self.algorithm_type == 1:
            payload = self._decrypt(payload)
        return payload.decode("utf-8", errors="replace")

    @staticmethod
    def _encrypt(data: bytes) -> bytes:
        enc = Cipher(algorithms.AES(AES_KEY), modes.CBC(AES_IV)).encryptor()
        return enc.update(_pkcs7_pad(data)) + enc.finalize()

    @staticmethod
    def _decrypt(data: bytes) -> bytes:
        dec = Cipher(algorithms.AES(AES_KEY), modes.CBC(AES_IV)).decryptor()
        return _pkcs7_unpad(dec.update(data) + dec.finalize())

    # ------------------------------------------------------------------ #
    # commands
    # ------------------------------------------------------------------ #
    async def key(self, keycode: int) -> None:
        """Send a TR_KEY remote key (cmd 149)."""
        await self._send(f"{CMD_KEY}>>{keycode}")

    async def mouse(self, x: int, y: int) -> None:
        """Touchpad / mouse move (cmd 151)."""
        await self._send(f"{CMD_MOUSE}>>{x}>>{y}")

    async def snapshot(self) -> None:
        """Request a TV screenshot (cmd 225)."""
        await self._send(f"{CMD_SNAP_SHOT}")

    async def send_raw(self, text: str) -> None:
        """Send an arbitrary `cmd>>param` message (advanced / services)."""
        await self._send(text)

    async def heartbeat(self) -> None:
        """Heartbeat (cmd 150).

        Matches the original app: payload is ``150>>`` and it is *encrypted*
        when AES is negotiated (HeartbeatRequest.setIgnoreAlgorithmType(false)).
        """
        await self._send(f"{CMD_ISONLINE}>>")

    async def read_loop(self, idle_timeout: float = 300.0) -> None:
        """Background task: read frames until the socket dies.

        Offline detection is handled by TCP keepalive (see _enable_keepalive),
        not by silence. ``idle_timeout`` is only a slow fallback for
        environments without keepalive support, so an online-but-silent TV is
        not wrongly marked offline.
        """
        while self._writer is not None and not self._writer.is_closing():
            try:
                msg = await self._read_frame(timeout=idle_timeout)
            except asyncio.TimeoutError:
                _LOGGER.debug(
                    "No data from TV for %.0fs; assuming offline", idle_timeout
                )
                break
            except (asyncio.IncompleteReadError, ConnectionError, OSError):
                break
            except Exception:  # keep reader alive on transient errors
                _LOGGER.debug("read_loop error", exc_info=True)
                continue
            if self.on_message:
                try:
                    await self.on_message(msg)
                except Exception:
                    _LOGGER.debug("on_message error", exc_info=True)
        self.connected = False

    # ------------------------------------------------------------------ #
    # wake-on-lan
    # ------------------------------------------------------------------ #
    @staticmethod
    async def wol_wake(
        mac: str,
        port: int = WOL_PORT,
        broadcast: str = WOL_BROADCAST,
        tries: int = 5,
    ) -> None:
        """Send a WOL magic packet (UDP broadcast :7778), 5 times."""
        mac = mac.replace(":", "").replace("-", "").strip()
        if len(mac) != 12:
            raise ValueError(f"Invalid MAC address: {mac!r}")
        magic = bytes.fromhex("FF" * 6 + mac * 16)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)  # never block the event loop on UDP sends
        try:
            for _ in range(tries):
                sock.sendto(magic, (broadcast, port))
                await asyncio.sleep(0.2)
        finally:
            sock.close()
