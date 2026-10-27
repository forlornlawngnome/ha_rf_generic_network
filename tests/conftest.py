"""Fixtures for RF Network tests."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

import pytest

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rf_network.const import DOMAIN
from custom_components.rf_network.library import load_library

LIB = load_library(None)
FAN_ENC = LIB.encodings["aircool_12"]
EV_ENC = LIB.encodings["ev1527_24"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom_components."""
    return


def frame(encoding, bits: str) -> list[int]:
    """What a gateway captures for one frame: the leading long gap is lost."""
    timings = encoding.encode(bits)
    return timings[1:] if encoding.inverted else timings[2:] + [encoding.sync[0] * encoding.pulse]


class FakeGateways:
    """Fake ESPHome gateways exposing the RF Network transmit action."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.broken: set[str] = set()

    def add(self, name: str, band: float | None = None) -> None:
        async def handler(call: ServiceCall) -> None:
            if name in self.broken:
                raise HomeAssistantError(f"{name} is offline")
            self.calls.append((name, dict(call.data)))

        self.hass.services.async_register("esphome", f"{name}_rf_network_transmit", handler)
        if band is not None:
            self.hass.bus.async_fire(
                "esphome.rf_network_hello", {"device": name.replace("_", "-"), "frequency_mhz": f"{band:.3f}"}
            )

    def raw(self, gateway_device: str, timings: list[int], count: int = 5, band: float = 303.0) -> None:
        text = ",".join(str(t) for t in timings)
        for _ in range(count):
            self.hass.bus.async_fire(
                "esphome.rf_network_raw",
                {"device": gateway_device, "frequency_mhz": f"{band:.3f}", "timings": text},
            )

    def fan(self, gateway_device: str, bits: str, count: int = 5) -> None:
        self.raw(gateway_device, frame(FAN_ENC, bits), count)


@pytest.fixture
async def gateways(hass: HomeAssistant) -> FakeGateways:
    gws = FakeGateways(hass)
    gws.add("rf_test", band=303.0)
    await hass.async_block_till_done()
    return gws


FAN = {"template": "aircool_12bit_dip", "name": "Living Room Fan", "address": "010101", "gateway": "auto"}
LEARNED = {
    "template": "learned",
    "name": "LED Strip",
    "gateway": "auto",
    "buttons": {"Power": "ev1527_24:000100110101000110100011", "Odd": "raw:500,-500,500,-1500,1500,-500,500,-500,500,-500,500,-500,500,-500,500,-500,500"},
}


def write_user_templates(config_dir: str) -> None:
    base = Path(config_dir) / "rf_network" / "templates" / "covers"
    base.mkdir(parents=True, exist_ok=True)
    (base / "test_shade.yaml").write_text(
        "name: Test shade\ntype: cover\ndevice_class: shade\nfrequency_mhz: 433.92\n"
        "encoding: ev1527_24\naddress_bits: 20\ncommands:\n  open: '0001'\n  close: '0011'\n  stop: '0101'\n"
    )
    lights = Path(config_dir) / "rf_network" / "templates" / "lights"
    lights.mkdir(parents=True, exist_ok=True)
    (lights / "test_lamp.yaml").write_text(
        "name: Test lamp\ntype: light\nfrequency_mhz: 433.92\nencoding: ev1527_24\naddress_bits: 20\n"
        "light:\n  on: '1100'\n  off: '0011'\n  brightness_up: '1000'\n"
    )
    (lights / "half_lamp.yaml").write_text(
        "name: Half lamp\ntype: light\nfrequency_mhz: 433.92\nencoding: ev1527_24\naddress_bits: 20\n"
        "light:\n  on: '1100'\n"
    )
    bad = Path(config_dir) / "rf_network" / "templates" / "fans"
    bad.mkdir(parents=True, exist_ok=True)
    (bad / "broken.yaml").write_text("name: Broken\ntype: fan\nfrequency_mhz: 303\nencoding: nope\ncommands: {}\n")


LAMP = {"template": "test_lamp", "name": "Desk Lamp", "address": "00000000111111110000", "gateway": "auto"}
SHADE = {"template": "test_shade", "name": "Patio Shade", "address": "10110011100011110000", "gateway": "auto"}


@pytest.fixture
async def entry(hass: HomeAssistant, gateways: FakeGateways) -> MockConfigEntry:
    await hass.async_add_executor_job(write_user_templates, hass.config.config_dir)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="RF Network",
        unique_id=DOMAIN,
        version=2,
        data={},
        options={"devices": {"lr": FAN, "led": LEARNED, "shade": SHADE, "lamp": LAMP}, "settings": {"burst_gap_ms": 250}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry
    await hass.async_add_executor_job(
        shutil.rmtree, Path(hass.config.config_dir) / "rf_network", True
    )
