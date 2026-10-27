"""Button entities for RF Network."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import slugify

from . import RFNetworkConfigEntry
from .devices import LearnedDevice, TemplateDevice
from .entity import RFNetworkEntity
from .library import TYPE_BUTTONS, TYPE_FAN, TYPE_LIGHT

# Template commands that become extra buttons on fans and lights.
EXTRA_BUTTONS = {
    TYPE_LIGHT: ("brightness_up", "brightness_down"),
}
DIM_COMMAND = {TYPE_FAN: "light_toggle", TYPE_LIGHT: "toggle"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RFNetworkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add remote buttons, learned buttons and dimmer helpers."""
    entities: list[ButtonEntity] = []
    for dev in entry.runtime_data.devices:
        if isinstance(dev, LearnedDevice):
            entities.extend(RFNetworkCodeButton(dev, name, code) for name, code in dev.buttons.items())
            continue
        if not isinstance(dev, TemplateDevice):
            continue
        tpl = dev.template
        if tpl.type == TYPE_BUTTONS:
            entities.extend(RFNetworkCommandButton(dev, name) for name in tpl.commands if name != "release")
        for name in EXTRA_BUTTONS.get(tpl.type, ()):
            if dev.has(name):
                entities.append(RFNetworkCommandButton(dev, name, translated=True))
        dim = DIM_COMMAND.get(tpl.type)
        if dim and dev.has(dim) and tpl.light.get("dim_step_repeats"):
            entities.append(RFNetworkDimStep(dev, dim, tpl.light["dim_step_repeats"]))
    async_add_entities(entities)


class RFNetworkCommandButton(RFNetworkEntity, ButtonEntity):
    """Sends one template command."""

    _attr_assumed_state = False

    def __init__(self, device: TemplateDevice, command: str, *, translated: bool = False) -> None:
        super().__init__(device, f"cmd_{slugify(command)}")
        self._command = command
        if translated:
            self._attr_translation_key = command
        else:
            self._attr_name = command

    async def async_press(self) -> None:
        await self.device.async_command(self._command)


class RFNetworkDimStep(RFNetworkEntity, ButtonEntity):
    """Holds the light key for about a second to nudge a dimmer.

    The dimmer ramps in whichever direction it is going and reverses at each
    end, so this is meant to be pressed while watching the light.
    """

    _attr_translation_key = "dim_step"
    _attr_assumed_state = False

    def __init__(self, device: TemplateDevice, command: str, repeats: int) -> None:
        super().__init__(device, "dim_step")
        self._command, self._repeats = command, repeats

    async def async_press(self) -> None:
        await self.device.async_command(self._command, repeat_count=self._repeats)


class RFNetworkCodeButton(RFNetworkEntity, ButtonEntity):
    """One learned code."""

    _attr_assumed_state = False

    def __init__(self, device: LearnedDevice, name: str, code: str) -> None:
        super().__init__(device, f"btn_{slugify(name)}")
        self._attr_name = name
        self._code = code

    async def async_press(self) -> None:
        await self.device.async_send_code(self._code)
