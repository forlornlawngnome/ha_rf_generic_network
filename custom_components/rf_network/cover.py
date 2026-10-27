"""Cover entities for RF Network: shades, blinds, awnings, gates."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import CoverDeviceClass, CoverEntity, CoverEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import RFNetworkConfigEntry
from .devices import TemplateDevice
from .entity import RFNetworkEntity
from .hub import Press
from .library import TYPE_COVER


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RFNetworkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a cover entity for every cover device."""
    async_add_entities(
        RFNetworkCover(dev)
        for dev in entry.runtime_data.devices
        if isinstance(dev, TemplateDevice) and dev.type == TYPE_COVER
    )


class RFNetworkCover(RFNetworkEntity, CoverEntity, RestoreEntity):
    """A cover with open/close (and optionally stop) codes.

    Position is not known; the state is the last command sent or heard.
    """

    _attr_name = None

    device: TemplateDevice

    def __init__(self, device: TemplateDevice) -> None:
        super().__init__(device, "cover")
        features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
        if device.has("stop"):
            features |= CoverEntityFeature.STOP
        self._attr_supported_features = features
        try:
            self._attr_device_class = CoverDeviceClass(device.template.device_class or "")
        except ValueError:
            self._attr_device_class = None
        self._attr_is_closed = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None and last.state in ("open", "closed"):
            self._attr_is_closed = last.state == "closed"

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self.device.async_command("open")
        self._attr_is_closed = False
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self.device.async_command("close")
        self._attr_is_closed = True
        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self.device.async_command("stop")
        # Stopped part-way: neither fully open nor closed. Show it as open.
        self._attr_is_closed = False
        self.async_write_ha_state()

    @callback
    def handle_press(self, press: Press) -> bool:
        cmd = self.device.command(press)
        if cmd == "open":
            self._attr_is_closed = False
        elif cmd == "close":
            self._attr_is_closed = True
        elif cmd == "stop":
            self._attr_is_closed = False
        else:
            return False
        return True
