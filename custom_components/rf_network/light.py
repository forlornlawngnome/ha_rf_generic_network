"""Light entities for RF Network: light templates and lights built into fans."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import RFNetworkConfigEntry
from .devices import TemplateDevice
from .entity import RFNetworkEntity
from .hub import Press
from .library import TYPE_FAN, TYPE_LIGHT

# Command names for each device type: (toggle, on, off)
COMMANDS = {
    TYPE_FAN: ("light_toggle", "light_on", "light_off"),
    TYPE_LIGHT: ("toggle", "on", "off"),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RFNetworkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add light devices and the lights of fans that have one."""
    entities = []
    for dev in entry.runtime_data.devices:
        if not isinstance(dev, TemplateDevice) or dev.type not in COMMANDS:
            continue
        toggle, on, off = COMMANDS[dev.type]
        if dev.has(toggle) or (dev.has(on) and dev.has(off)):
            entities.append(RFNetworkLight(dev, toggle, on, off))
    async_add_entities(entities)


class RFNetworkLight(RFNetworkEntity, LightEntity, RestoreEntity):
    """An on/off light. With only a toggle code, on/off is tracked here.

    If the state is wrong (e.g. after a power cut), tap the physical remote
    once: every remote press updates the state.
    """

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    device: TemplateDevice

    def __init__(self, device: TemplateDevice, toggle: str, on: str, off: str) -> None:
        super().__init__(device, "light")
        self._toggle, self._on, self._off = toggle, on, off
        if device.type == TYPE_LIGHT:
            self._attr_name = None  # the device itself is the light
        else:
            self._attr_translation_key = "light"
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == "on"

    async def _switch(self, on: bool) -> None:
        direct = self._on if on else self._off
        if self.device.has(direct):
            await self.device.async_command(direct)
        elif self._attr_is_on != on:
            await self.device.async_command(self._toggle)
        self._attr_is_on = on
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._switch(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._switch(False)

    @callback
    def handle_press(self, press: Press) -> bool:
        cmd = self.device.command(press)
        if cmd == self._toggle:
            self._attr_is_on = not self._attr_is_on
        elif cmd == self._on:
            self._attr_is_on = True
        elif cmd == self._off:
            self._attr_is_on = False
        else:
            # A held key ramps a dimmer without toggling.
            return False
        return True
