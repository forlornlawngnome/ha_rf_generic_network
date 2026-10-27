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
from .hub import SIGNAL_UNKNOWN, RFNetwork


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RFNetworkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the hub sensors."""
    hub = entry.runtime_data.hub
    info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=NAME, manufacturer=NAME, model="Hub")
    async_add_entities(
        [
            RFLastCodeSensor(hub, entry.entry_id, info),
            RFUnknownSensor(hub, entry.entry_id, info),
            RFGatewaysSensor(hub, entry.entry_id, info),
        ]
    )


class _HubSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub: RFNetwork, entry_id: str, info: DeviceInfo, key: str) -> None:
        self._hub = hub
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = info


class RFLastCodeSensor(_HubSensor):
    """The last press heard by any gateway, with template suggestions."""

    def __init__(self, hub: RFNetwork, entry_id: str, info: DeviceInfo) -> None:
        super().__init__(hub, entry_id, info, "last_code")

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_PRESS, self._update))

    @callback
    def _update(self, *_: Any) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        return self._hub.last_press.code if self._hub.last_press else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self._hub.last_press_info)


class RFUnknownSensor(_HubSensor):
    """The last capture no encoding recognised, as a raw code you can learn."""

    def __init__(self, hub: RFNetwork, entry_id: str, info: DeviceInfo) -> None:
        super().__init__(hub, entry_id, info, "last_unknown")

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UNKNOWN, self._update))

    @callback
    def _update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> int | None:
        return self._hub.last_unknown.get("pulses")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self._hub.last_unknown)


class RFGatewaysSensor(_HubSensor):
    """How many gateways are online, with their bands."""

    _attr_should_poll = True
    _attr_native_unit_of_measurement = "gateways"

    def __init__(self, hub: RFNetwork, entry_id: str, info: DeviceInfo) -> None:
        super().__init__(hub, entry_id, info, "gateways")

    @property
    def native_value(self) -> int:
        return len(self._hub.gateways())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "gateways": {
                gw: (f"{band:g} MHz" if (band := self._hub.gateway_bands.get(gw)) else "band not reported yet")
                for gw in self._hub.gateways()
            }
        }
