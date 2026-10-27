"""RF Network: control fixed-code RF devices through ESPHome gateways."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_BURST_GAP,
    CONF_DEVICES,
    CONF_ECHO_WINDOW,
    CONF_REPEATS,
    CONF_SETTINGS,
    DEFAULT_BURST_GAP,
    DEFAULT_ECHO_WINDOW,
    DEFAULT_REPEATS,
    DOMAIN,
)
from .devices import RFDevice, build_device
from .hub import RFNetwork

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
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
    settings = entry.options.get(CONF_SETTINGS, {})
    hub = RFNetwork(
        hass,
        repeat_count=int(settings.get(CONF_REPEATS, DEFAULT_REPEATS)),
        burst_gap_ms=int(settings.get(CONF_BURST_GAP, DEFAULT_BURST_GAP)),
        echo_window_ms=int(settings.get(CONF_ECHO_WINDOW, DEFAULT_ECHO_WINDOW)),
    )
    devices: list[RFDevice] = []
    for dev_id, conf in entry.options.get(CONF_DEVICES, {}).items():
        device = build_device(hub, dev_id, conf)
        if device is not None:
            devices.append(device)
    hub.devices = devices

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
