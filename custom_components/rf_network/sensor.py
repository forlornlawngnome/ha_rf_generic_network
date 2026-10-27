"""Diagnostic sensors for RF Network: last received code and gateways."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RFNetworkConfigEntry
from .const import DOMAIN, NAME, SIGNAL_PRESS
from .hub import Press, RFNetwork


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RFNetworkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the hub sensors."""
    hub = entry.runtime_data.hub
    info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=NAME, manufacturer=NAME, model="Hub")
    async_add_entities(
        [RFLastCodeSensor(hub, entry.entry_id, info), RFGatewaysSensor(hub, entry.entry_id, info)]
    )


class RFLastCodeSensor(SensorEntity):
    """The last remote press heard by any gateway: use it to learn codes."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "last_code"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub: RFNetwork, entry_id: str, info: DeviceInfo) -> None:
        self._hub = hub
        self._attr_unique_id = f"{entry_id}_last_code"
        self._attr_device_info = info

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_PRESS, self._on_press))

    @callback
    def _on_press(self, press: Press) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        return self._hub.last_press.code if self._hub.last_press else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self._hub.last_press_info)


class RFGatewaysSensor(SensorEntity):
    """How many gateways are online, with their names."""

    _attr_has_entity_name = True
    _attr_translation_key = "gateways"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "gateways"

    def __init__(self, hub: RFNetwork, entry_id: str, info: DeviceInfo) -> None:
        self._hub = hub
        self._attr_unique_id = f"{entry_id}_gateways"
        self._attr_device_info = info

    @property
    def native_value(self) -> int:
        return len(self._hub.gateways())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"gateways": self._hub.gateways()}
