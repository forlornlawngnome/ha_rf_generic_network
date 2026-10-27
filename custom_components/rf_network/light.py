"""Light entities for RF Network."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import RFNetworkConfigEntry
from .devices import FanDip12
from .entity import RFNetworkEntity
from .hub import Press


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RFNetworkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the light of every fan device."""
    async_add_entities(
        RFNetworkFanLight(dev) for dev in entry.runtime_data.devices if isinstance(dev, FanDip12)
    )


class RFNetworkFanLight(RFNetworkEntity, LightEntity, RestoreEntity):
    """A fan's light. The receiver only has a toggle, so on/off is tracked here.

    If the state is wrong (e.g. after a power cut), turn it off and on again,
    or tap the wall remote once: every remote press updates the state.
    """

    _attr_translation_key = "light"
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    device: FanDip12

    def __init__(self, device: FanDip12) -> None:
        super().__init__(device, "light")
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == "on"

    async def _toggle_to(self, on: bool) -> None:
        if self._attr_is_on == on:
            return
        await self.device.async_send(self.device.code(self.device.LIGHT), action="light_toggle")
        self._attr_is_on = on
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._toggle_to(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._toggle_to(False)

    @callback
    def handle_press(self, press: Press) -> bool:
        cmd = self.device.decode(press)
        if cmd is None or cmd.kind != "light":
            # A held light key ramps the dimmer without toggling.
            return False
        self._attr_is_on = not self._attr_is_on
        return True
