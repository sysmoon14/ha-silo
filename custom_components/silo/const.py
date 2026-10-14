"""Constants for the Silo integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "silo"

CONF_PROFILE_ID: Final = "profile_id"
CONF_TVS: Final = "tvs"
CONF_ADB_ENTITY: Final = "adb_entity_id"
CONF_CLIENT_IP: Final = "client_ip"
CONF_NAME: Final = "name"
CONF_WAKE_DELAY: Final = "wake_delay"

DEFAULT_WAKE_DELAY: Final = 2.0
SCAN_INTERVAL: Final = timedelta(seconds=5)
SERVER_SCAN_INTERVAL: Final = timedelta(seconds=60)

ATTR_TASK_KEY: Final = "task_key"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
SERVICE_RUN_TASK: Final = "run_task"
SERVICE_SEND_MESSAGE: Final = "send_message"
SERVICE_STOP_PLAYBACK: Final = "stop_playback"
ATTR_MESSAGE: Final = "message"
ATTR_TITLE: Final = "title"

# hass.data[DOMAIN][DATA_TARGETS]: entities whose sessions messages/stop can reach.
DATA_TARGETS: Final = "session_targets"

ANDROID_PACKAGE: Final = "org.siloserver.silo"

ATTR_CONTENT_ID: Final = "content_id"
ATTR_FROM_START: Final = "from_start"
ATTR_SKIP_IF_PLAYING: Final = "skip_if_playing"
ATTR_PROFILE_ID: Final = "profile_id"
ATTR_SCOPE_ID: Final = "scope_id"

SERVICE_PLAY: Final = "play"
SERVICE_SHUFFLE: Final = "shuffle"

# Prefix used for Home Assistant media browser ids so they never collide with
# a raw Silo content id passed straight to play_media.
BROWSE_PREFIX: Final = "silo://"
