"""Button entities for RF Network."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import slugify

from . import RFNetworkConfigEntry
from .devices import FanDip12, LearnedButtons
from .entity import RFNetworkEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RFNetworkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add learned buttons and the fan light dim step buttons."""
    entities: list[ButtonEntity] = []
    for dev in entry.runtime_data.devices:
        if isinstance(dev, FanDip12):
            entities.append(RFNetworkDimStep(dev))
        elif isinstance(dev, LearnedButtons):
            entities.extend(RFNetworkLearnedButton(dev, name, code) for name, code in dev.buttons.items())
    async_add_entities(entities)


class RFNetworkDimStep(RFNetworkEntity, ButtonEntity):
    """Hold the light key for about a second to nudge the dimmer.

    The dimmer ramps in whichever direction it is currently going and
    reverses at each end, so this is meant to be pressed while watching.
    """

    _attr_translation_key = "dim_step"
    _attr_assumed_state = False

    device: FanDip12

    def __init__(self, device: FanDip12) -> None:
        super().__init__(device, "dim_step")

    async def async_press(self) -> None:
        await self.device.async_send(
            self.device.code(self.device.LIGHT),
            repeat_count=self.device.DIM_STEP_REPEATS,
            action="light_dim",
        )


class RFNetworkLearnedButton(RFNetworkEntity, ButtonEntity):
    """One learned remote button."""

    _attr_assumed_state = False

    def __init__(self, device: LearnedButtons, name: str, code: str) -> None:
        super().__init__(device, f"btn_{slugify(name)}")
        self._attr_name = name
        self._code = code

    async def async_press(self) -> None:
        await self.device.async_send(self._code, action=self._attr_name or "")
