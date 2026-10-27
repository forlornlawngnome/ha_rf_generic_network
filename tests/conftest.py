"""Fixtures for RF Network tests."""

from __future__ import annotations

from typing import Any

import pytest

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rf_network.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom_components."""
    return


class FakeGateways:
    """Fake ESPHome gateways exposing the transmit action."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.broken: set[str] = set()

    def add(self, name: str) -> None:
        async def handler(call: ServiceCall) -> None:
            if name in self.broken:
                raise HomeAssistantError(f"{name} is offline")
            self.calls.append((name, dict(call.data)))

        self.hass.services.async_register("esphome", f"{name}_transmit_rf_fan", handler)

    def frames(self, gateway_device: str, code: str, count: int = 5) -> None:
        for _ in range(count):
            self.hass.bus.async_fire(
                "esphome.rf_fan_received",
                {"device": gateway_device, "action": "sniff", "code": code},
            )


@pytest.fixture
def gateways(hass: HomeAssistant) -> FakeGateways:
    gws = FakeGateways(hass)
    gws.add("rf_test")
    return gws


FAN = {"profile": "fan_dip12", "name": "Living Room Fan", "address": "010101", "gateway": "auto"}
BUTTONS = {
    "profile": "learned_buttons",
    "name": "LED Strip",
    "gateway": "auto",
    "buttons": {"Power": "1:000100110101000110100011", "Red": "1:000100110101000110100101"},
}


@pytest.fixture
async def entry(hass: HomeAssistant, gateways: FakeGateways) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="RF Network",
        unique_id=DOMAIN,
        data={},
        options={"devices": {"lr": FAN, "led": BUTTONS}, "settings": {"burst_gap_ms": 250}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
