"""Fan entities for RF Network."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import (
    DIRECTION_FORWARD,
    DIRECTION_REVERSE,
    FanEntity,
    FanEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from . import RFNetworkConfigEntry
from .devices import FanDip12
from .entity import RFNetworkEntity
from .hub import Press


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RFNetworkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a fan entity for every fan device."""
    async_add_entities(
        RFNetworkFan(dev) for dev in entry.runtime_data.devices if isinstance(dev, FanDip12)
    )


class RFNetworkFan(RFNetworkEntity, FanEntity, RestoreEntity):
    """A ceiling fan driven by RF codes."""

    _attr_name = None  # use the device name
    _attr_translation_key = "fan"
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.DIRECTION
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )

    device: FanDip12

    def __init__(self, device: FanDip12) -> None:
        super().__init__(device, "fan")
        self._speeds = list(range(1, device.speed_count + 1))
        self._attr_speed_count = device.speed_count
        self._is_on = False
        self._speed = device.DEFAULT_SPEED
        self._attr_current_direction = DIRECTION_FORWARD

    async def async_added_to_hass(self) -> None:
        """Restore the last known state."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is None:
            return
        self._is_on = last.state == "on"
        if (direction := last.attributes.get("direction")) in (DIRECTION_FORWARD, DIRECTION_REVERSE):
            self._attr_current_direction = direction
        if (speed := last.attributes.get("rf_speed")) in self._speeds:
            self._speed = speed

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def percentage(self) -> int:
        if not self._is_on:
            return 0
        return ordered_list_item_to_percentage(self._speeds, self._speed)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"rf_speed": self._speed}

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage == 0:
            await self.async_turn_off()
            return
        speed = percentage_to_ordered_list_item(self._speeds, percentage)
        await self.device.async_send(self.device.speed_code(speed), action=f"fan_speed_{speed}")
        self._is_on, self._speed = True, speed
        self.async_write_ha_state()

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        if percentage is None:
            percentage = ordered_list_item_to_percentage(self._speeds, self._speed)
        await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.device.async_send(self.device.code(self.device.OFF), action="fan_off")
        self._is_on = False
        self.async_write_ha_state()

    async def async_set_direction(self, direction: str) -> None:
        if direction == self._attr_current_direction:
            return
        # The receiver only has a "reverse" toggle.
        await self.device.async_send(self.device.code(self.device.REVERSE), action="fan_reverse")
        self._attr_current_direction = direction
        self.async_write_ha_state()

    @callback
    def handle_press(self, press: Press) -> bool:
        cmd = self.device.decode(press)
        if cmd is None:
            return False
        if cmd.kind == "speed":
            self._is_on, self._speed = True, cmd.speed
        elif cmd.kind == "off":
            self._is_on = False
        elif cmd.kind == "reverse":
            self._attr_current_direction = (
                DIRECTION_REVERSE
                if self._attr_current_direction == DIRECTION_FORWARD
                else DIRECTION_FORWARD
            )
        else:
            return False
        return True
