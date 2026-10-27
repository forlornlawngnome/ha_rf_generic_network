"""Constants for RF Network."""

from __future__ import annotations

DOMAIN = "rf_network"
NAME = "RF Network"

# ESPHome gateway contract (see esphome/rf-network-gateway.yaml).
# Each gateway exposes an action named `<node>_<GATEWAY_SERVICE_SUFFIX>` with
# fields `action`, `code`, `repeat_count`, and fires GATEWAY_EVENT for every
# decoded frame with fields `device`, `action`, `code`.
ESPHOME_DOMAIN = "esphome"
GATEWAY_SERVICE_SUFFIX = "transmit_rf_fan"
GATEWAY_EVENT = "esphome.rf_fan_received"

# Event this integration fires once per (deduplicated) remote press.
PRESS_EVENT = f"{DOMAIN}_press"
SIGNAL_PRESS = f"{DOMAIN}_press_signal"

# Options keys
CONF_DEVICES = "devices"
CONF_SETTINGS = "settings"
CONF_PROFILE = "profile"
CONF_NAME = "name"
CONF_GATEWAY = "gateway"
CONF_ADDRESS = "address"
CONF_BUTTONS = "buttons"
CONF_PROTOCOL = "protocol"

GATEWAY_AUTO = "auto"

# Settings
CONF_BURST_GAP = "burst_gap_ms"
CONF_ECHO_WINDOW = "echo_window_ms"
CONF_REPEATS = "repeat_count"
DEFAULT_BURST_GAP = 250  # ms of silence that ends a press
DEFAULT_ECHO_WINDOW = 600  # ms after our own transmission to ignore echoes
DEFAULT_REPEATS = 8

# Approximate on-air time per repeat of a short (12-24 bit) frame incl. the
# gateway's 10 ms wait_time. Used to space out transmissions so that two
# gateways never transmit at the same time.
FRAME_AIRTIME_S = 0.032

PROFILE_FAN_A3 = "fan_dip12"
PROFILE_BUTTONS = "learned_buttons"
