"""Shared entity base for RF Network devices."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import SIGNAL_PRESS
from .devices import RFDevice
from .hub import Press


class RFNetworkEntity(Entity):
    """An entity belonging to one RF device.

    State is assumed: these receivers never report back. Presses from the
    physical remote heard by any gateway are fed to `handle_press`.
    """

    _attr_has_entity_name = True
    _attr_assumed_state = True
    _attr_should_poll = False

    def __init__(self, device: RFDevice, key: str) -> None:
        self.device = device
        self._attr_unique_id = f"{device.dev_id}_{key}"
        self._attr_device_info = device.device_info

    async def async_added_to_hass(self) -> None:
        """Subscribe to presses."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_PRESS, self._on_press)
        )

    @callback
    def _on_press(self, press: Press) -> None:
        if self.device.matches(press.code) and self.handle_press(press):
            self.async_write_ha_state()

    @callback
    def handle_press(self, press: Press) -> bool:
        """Update state from a remote press; return True if it changed."""
        return False
