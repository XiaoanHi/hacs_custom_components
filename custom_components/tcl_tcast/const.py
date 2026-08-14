"""Constants for the TCL T-Cast integration.

Reverse-engineered from `com.tnscreen.main` (base.apk) — see ANALYSIS/docs/.
"""
from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_NAME

DOMAIN = "tcl_tcast"
DOMAIN_TITLE = "TCL T-Cast"

# Config entry data keys
CONF_MAC = "mac"
CONF_ALGORITHM = "algorithm"
# Alias for user-facing config
CONF_DEVICE_NAME = "name"

# --- Ports ---
UDP_PORT = 6537          # discovery broadcast / listen
TCP_PORT = 6553          # command channel
WOL_PORT = 7778          # wake-on-lan magic packet
WOL_BROADCAST = "255.255.255.255"
AUDIO_PORT = 4332        # voice stream (unused in this integration)

# --- AES (from libjnitool.so) ---
AES_KEY = b"tnscreentnscreen"
AES_IV = bytes([0x12, 0x34, 0x56, 0x78, 0x90, 0xAB, 0xCD, 0xEF] * 2)

# --- TCP command numbers ---
CMD_KEY = 149
CMD_ISONLINE = 150
CMD_MOUSE = 151
CMD_INPUTSTR = 155
CMD_VOICE = 157
CMD_GET_CLIENTTYPE = 159
CMD_GET_SYSTEM_VOLUME = 183
CMD_SET_SYSTEM_VOLUME = 184
CMD_SNAP_SHOT = 225
CMD_VOICE_STRING = 233
CMD_GET_RECENT_INPUT = 269

# --- Media command numbers ---
MEDIA_STOP = 129
MEDIA_SET_VOLUME = 130
MEDIA_SET_MUTE = 131
MEDIA_SEEK = 132
MEDIA_PREPARE_PLAY = 133
MEDIA_PLAY = 134
MEDIA_PAUSE = 135

# --- TR_KEY keycodes (TCL private, NOT Android keycodes) ---
KEY_POWER = 20
KEY_HOME = 19
KEY_SMARTTV = 45
KEY_MENU = 18
KEY_UP = 11
KEY_DOWN = 12
KEY_LEFT = 13
KEY_RIGHT = 14
KEY_OK = 15
KEY_BACK = 16
KEY_ENTER = 68
KEY_VOL_UP = 21
KEY_VOL_DOWN = 22
KEY_MUTE = 23
KEY_CH_UP = 27
KEY_CH_DOWN = 28
KEY_SOURCE = 29
KEY_PLAYBACK = 26
KEY_MOUSE_LEFT = 39
KEY_MOUSE_RIGHT = 40
KEY_RED = 34
KEY_GREEN = 35
KEY_YELLOW = 36
KEY_BLUE = 37
KEY_INFO = 41
KEY_SEARCH = 33
KEY_EPG = 24

# --- Remote button map: name -> TR_KEY keycode ---
KEY_COMMANDS: dict[str, int] = {
    "power": KEY_POWER,
    "home": KEY_HOME,
    "smarttv": KEY_SMARTTV,
    "menu": KEY_MENU,
    "up": KEY_UP,
    "down": KEY_DOWN,
    "left": KEY_LEFT,
    "right": KEY_RIGHT,
    "ok": KEY_OK,
    "back": KEY_BACK,
    "enter": KEY_ENTER,
    "vol_up": KEY_VOL_UP,
    "vol_down": KEY_VOL_DOWN,
    "mute": KEY_MUTE,
    "ch_up": KEY_CH_UP,
    "ch_down": KEY_CH_DOWN,
    "source": KEY_SOURCE,
    "playback": KEY_PLAYBACK,
    "mouse_left": KEY_MOUSE_LEFT,
    "mouse_right": KEY_MOUSE_RIGHT,
    "red": KEY_RED,
    "green": KEY_GREEN,
    "yellow": KEY_YELLOW,
    "blue": KEY_BLUE,
    "info": KEY_INFO,
    "search": KEY_SEARCH,
    "epg": KEY_EPG,
}
KEY_COMMANDS["0"] = 10  # TR_KEY_0 = 10
for _digit in range(1, 10):
    KEY_COMMANDS[str(_digit)] = _digit

# Input order the SOURCE menu lists (matches the user's TV: TV, HDMI1, HDMI2, AV).
SOURCE_LIST = ["TV", "HDMI1", "HDMI2", "AV"]
# Which inputs get their own one-tap switch buttons.
SOURCE_BUTTONS = ["HDMI1", "HDMI2"]

# --- Defaults ---
SCAN_TIMEOUT = 8.0        # seconds for LAN discovery
HEARTBEAT_INTERVAL = 10   # seconds between probes; must beat the TV's idle
                          # drop (~15 s) or the socket is closed -> offline
HEARTBEAT_CONFIRM = 25    # seconds to wait for a probe reply before offline
HEARTBEAT_MISSES = 3      # consecutive missed replies before declaring offline
RECONNECT_DELAY = 5       # seconds
CONNECT_TIMEOUT = 10      # seconds
