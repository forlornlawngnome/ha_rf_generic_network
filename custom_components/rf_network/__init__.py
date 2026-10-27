"""RF Network: control fixed-code RF devices through ESPHome gateways."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, issue_registry as ir

from .const import (
    CONF_BURST_GAP,
    CONF_BUTTONS,
    CONF_DEVICES,
    CONF_ECHO_WINDOW,
    CONF_REPEATS,
    CONF_SETTINGS,
    CONF_TEMPLATE,
    DEFAULT_BURST_GAP,
    DEFAULT_ECHO_WINDOW,
    DEFAULT_REPEATS,
    DOMAIN,
    LEGACY_BUTTONS,
    LEGACY_FAN,
    LEGACY_FAN_ENCODING,
    LEGACY_FAN_TEMPLATE,
    LEGACY_PROFILE,
    TEMPLATE_LEARNED,
)
from .devices import RFDevice, build_device
from .hub import RFNetwork
from .library import async_get_library

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.COVER,
    Platform.FAN,
    Platform.LIGHT,
    Platform.SENSOR,
]


@dataclass
class RFNetworkData:
    """Runtime data stored on the config entry."""

    hub: RFNetwork
    devices: list[RFDevice]


type RFNetworkConfigEntry = ConfigEntry[RFNetworkData]


async def async_setup_entry(hass: HomeAssistant, entry: RFNetworkConfigEntry) -> bool:
    """Set up RF Network from a config entry."""
    library = await async_get_library(hass, reload=True)
    settings = entry.options.get(CONF_SETTINGS, {})
    hub = RFNetwork(
        hass,
        library,
        repeat_count=int(settings.get(CONF_REPEATS, DEFAULT_REPEATS)),
        burst_gap_ms=int(settings.get(CONF_BURST_GAP, DEFAULT_BURST_GAP)),
        echo_window_ms=int(settings.get(CONF_ECHO_WINDOW, DEFAULT_ECHO_WINDOW)),
    )
    devices: list[RFDevice] = []
    missing: list[str] = []
    for dev_id, conf in entry.options.get(CONF_DEVICES, {}).items():
        device = build_device(hub, library, dev_id, conf)
        if device is None:
            missing.append(f"{conf.get('name')} (template '{conf.get(CONF_TEMPLATE)}')")
        else:
            devices.append(device)
    hub.devices = devices

    if missing:
        ir.async_create_issue(
            hass,
            DOMAIN,
            "missing_templates",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="missing_templates",
            translation_placeholders={"devices": ", ".join(missing)},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, "missing_templates")

    # Remove devices that were deleted in the options flow.
    registry = dr.async_get(hass)
    keep = {(DOMAIN, d.dev_id) for d in devices} | {(DOMAIN, entry.entry_id)}
    for dev in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if not dev.identifiers & keep:
            registry.async_remove_device(dev.id)

    entry.runtime_data = RFNetworkData(hub=hub, devices=devices)
    hub.async_start()
    entry.async_on_unload(hub.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass: HomeAssistant, entry: RFNetworkConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: RFNetworkConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _migrate_code(code: str) -> str:
    """0.1.0 codes were rc_switch '<protocol>:<bits>'; 6 with 12 bits is aircool_12."""
    proto, _, bits = code.partition(":")
    if proto == "6" and len(bits) == 12:
        return f"{LEGACY_FAN_ENCODING}:{bits}"
    return code


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate 0.1.0 options (profiles) to templates."""
    if entry.version == 1:
        devices: dict[str, Any] = {}
        for dev_id, conf in entry.options.get(CONF_DEVICES, {}).items():
            conf = dict(conf)
            profile = conf.pop(LEGACY_PROFILE, None)
            conf.pop("protocol", None)
            if profile == LEGACY_FAN:
                conf[CONF_TEMPLATE] = LEGACY_FAN_TEMPLATE
            elif profile == LEGACY_BUTTONS:
                conf[CONF_TEMPLATE] = TEMPLATE_LEARNED
                conf[CONF_BUTTONS] = {k: _migrate_code(v) for k, v in conf.get(CONF_BUTTONS, {}).items()}
            devices[dev_id] = conf
        options = {**entry.options, CONF_DEVICES: devices}
        hass.config_entries.async_update_entry(entry, options=options, version=2)
        _LOGGER.info("Migrated RF Network options to version 2 (templates)")
    return True
