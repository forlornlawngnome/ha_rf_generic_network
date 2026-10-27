"""Constants for RF Network."""

from __future__ import annotations

DOMAIN = "rf_network"
NAME = "RF Network"

# ESPHome gateway contract (see esphome/rf-network-core.yaml). A gateway
# exposes an action `<node>_<GATEWAY_SERVICE_SUFFIX>` taking `timings` (int
# list, microseconds), `repeat_count` and `frequency_mhz`; it fires RAW_EVENT
# with `device`, `frequency_mhz`, `timings` ("350,-700,...") for each capture,
# and HELLO_EVENT with `device`, `frequency_mhz` on connect and every 5 min.
ESPHOME_DOMAIN = "esphome"
GATEWAY_SERVICE_SUFFIX = "rf_network_transmit"
RAW_EVENT = "esphome.rf_network_raw"
HELLO_EVENT = "esphome.rf_network_hello"

# A gateway serves a template if its listen frequency is within this range.
BAND_TOLERANCE_MHZ = 10.0
# Pause the gateway leaves between repeats (tx_repeat_gap in the firmware).
REPEAT_GAP_S = 0.010

# Event this integration fires once per (deduplicated) remote press.
PRESS_EVENT = f"{DOMAIN}_press"
SIGNAL_PRESS = f"{DOMAIN}_press_signal"

# Options keys
CONF_DEVICES = "devices"
CONF_SETTINGS = "settings"
CONF_TEMPLATE = "template"
CONF_NAME = "name"
CONF_GATEWAY = "gateway"
CONF_ADDRESS = "address"
CONF_BUTTONS = "buttons"

TEMPLATE_LEARNED = "learned"
GATEWAY_AUTO = "auto"

# Settings
CONF_BURST_GAP = "burst_gap_ms"
CONF_ECHO_WINDOW = "echo_window_ms"
CONF_REPEATS = "repeat_count"
DEFAULT_BURST_GAP = 250  # ms of silence that ends a press
DEFAULT_ECHO_WINDOW = 600  # ms after our own transmission to ignore echoes
DEFAULT_REPEATS = 8

# 0.1.0 options format, migrated on load
LEGACY_PROFILE = "profile"
LEGACY_FAN = "fan_dip12"
LEGACY_BUTTONS = "learned_buttons"
LEGACY_FAN_TEMPLATE = "aircool_12bit_dip"
LEGACY_FAN_ENCODING = "aircool_12"
