"""Integration tests for RF Network."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.rf_network.const import DOMAIN, PRESS_EVENT

from .conftest import EV_ENC, FAN_ENC, frame

FAN_ID = "fan.living_room_fan"
LIGHT_ID = "light.living_room_fan_light"
SHADE_ID = "cover.patio_shade"


def _settle(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))


def _sent(gateways) -> tuple[str, str]:
    """(gateway, bits) of the last transmission, decoded back."""
    name, data = gateways.calls[-1]
    timings = list(data["timings"])
    enc = FAN_ENC if len(timings) == 26 else EV_ENC
    captured = timings[1:] if enc.inverted else timings[2:]
    return name, enc.decode(captured)


async def test_config_flow_single_instance(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT


async def test_entities(hass: HomeAssistant, entry) -> None:
    for entity_id in (FAN_ID, LIGHT_ID, SHADE_ID, "button.living_room_fan_light_dim_step",
                      "button.led_strip_power", "sensor.rf_network_gateways"):
        assert hass.states.get(entity_id) is not None, entity_id
    assert hass.states.get(SHADE_ID).attributes["device_class"] == "shade"
    assert hass.states.get(FAN_ID).attributes["percentage_step"] == 100 / 6


async def test_fan_commands(hass: HomeAssistant, entry, gateways) -> None:
    await hass.services.async_call("fan", "set_percentage", {"entity_id": FAN_ID, "percentage": 100}, blocking=True)
    assert _sent(gateways) == ("rf_test", "010101011111")
    data = gateways.calls[-1][1]
    assert data["repeat_count"] == 8 and data["frequency_mhz"] == 303.0
    await hass.services.async_call("fan", "set_percentage", {"entity_id": FAN_ID, "percentage": 16}, blocking=True)
    assert _sent(gateways)[1] == "010101110111"
    await hass.services.async_call("fan", "turn_off", {"entity_id": FAN_ID}, blocking=True)
    assert _sent(gateways)[1] == "010101111101"
    await hass.services.async_call("fan", "set_direction", {"entity_id": FAN_ID, "direction": "reverse"}, blocking=True)
    assert _sent(gateways)[1] == "010101111011"


async def test_light_and_dim(hass: HomeAssistant, entry, gateways) -> None:
    await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT_ID}, blocking=True)
    assert _sent(gateways)[1] == "010101111110"
    n = len(gateways.calls)
    await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT_ID}, blocking=True)
    assert len(gateways.calls) == n
    await hass.services.async_call("button", "press", {"entity_id": "button.living_room_fan_light_dim_step"}, blocking=True)
    assert gateways.calls[-1][1]["repeat_count"] == 33


async def test_remote_press_dedup_state_and_release(hass: HomeAssistant, entry, gateways) -> None:
    events = async_capture_events(hass, PRESS_EVENT)
    gateways.fan("rf-test", "010101101111", 6)  # speed 3 of 6
    gateways.fan("rf-attic", "010101101111", 4)
    gateways.fan("rf-test", "010101111111", 2)  # release frames
    _settle(hass)
    await hass.async_block_till_done()
    assert len(events) == 1
    data = events[0].data
    assert data["code"] == "aircool_12:010101101111"
    assert data["gateways"] == ["rf_attic", "rf_test"] and data["frames"] == 10
    assert data["device"] == "Living Room Fan" and data["command"] == "speed_3"
    state = hass.states.get(FAN_ID)
    assert state.state == "on" and state.attributes["percentage"] == 50


async def test_light_tap_vs_hold(hass: HomeAssistant, entry, gateways) -> None:
    clock = [1000.0]
    with patch("custom_components.rf_network.hub.time.monotonic", side_effect=lambda: clock[0]):
        for _ in range(5):
            gateways.fan("rf-test", "010101110110", 1)  # remote's "up light" key also toggles
            clock[0] += 0.02
        _settle(hass)
        await hass.async_block_till_done()
        assert hass.states.get(LIGHT_ID).state == "on"
        clock[0] += 5
        for _ in range(60):
            gateways.fan("rf-test", "010101111110", 1)
            clock[0] += 0.02
        _settle(hass)
        await hass.async_block_till_done()
        assert hass.states.get(LIGHT_ID).state == "on"


async def test_echo_ignored(hass: HomeAssistant, entry, gateways) -> None:
    events = async_capture_events(hass, PRESS_EVENT)
    await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT_ID}, blocking=True)
    gateways.fan("rf-attic", "010101111110", 8)
    _settle(hass)
    await hass.async_block_till_done()
    assert events == []


async def test_band_routing_and_fallback(hass: HomeAssistant, entry, gateways) -> None:
    gateways.add("rf_porch", band=433.92)
    gateways.add("rf_attic", band=303.0)
    await hass.async_block_till_done()
    # Shade (433.92 MHz) only goes through the 433 gateway, retuned to its frequency.
    await hass.services.async_call("cover", "close_cover", {"entity_id": SHADE_ID}, blocking=True)
    assert _sent(gateways) == ("rf_porch", "101100111000111100000011")
    assert gateways.calls[-1][1]["frequency_mhz"] == 433.92
    assert hass.states.get(SHADE_ID).state == "closed"
    # Fan: the attic gateway heard its remote last, so auto picks it...
    gateways.fan("rf-attic", "010101111101", 3)
    _settle(hass)
    await hass.async_block_till_done()
    await hass.services.async_call("fan", "turn_off", {"entity_id": FAN_ID}, blocking=True)
    assert gateways.calls[-1][0] == "rf_attic"
    # ...and falls back to the other 303 MHz gateway, never the 433 one.
    gateways.broken.add("rf_attic")
    await hass.services.async_call("fan", "turn_off", {"entity_id": FAN_ID}, blocking=True)
    assert gateways.calls[-1][0] == "rf_test"


async def test_learned_and_raw_codes(hass: HomeAssistant, entry, gateways) -> None:
    events = async_capture_events(hass, PRESS_EVENT)
    gateways.raw("rf-test", frame(EV_ENC, "000100110101000110100011"), 4)
    # A signal no encoding knows, matched against the learned raw code.
    gateways.raw("rf-test", [520, -480, 510, -1450, 1530, -490, 480, -520, 500, -500, 500, -500, 500, -500, 500, -500, 500], 3)
    _settle(hass)
    await hass.async_block_till_done()
    assert sorted(e.data["command"] for e in events) == ["Odd", "Power"]
    await hass.services.async_call("button", "press", {"entity_id": "button.led_strip_power"}, blocking=True)
    assert _sent(gateways)[1] == "000100110101000110100011"


async def test_unknown_signal_and_detection(hass: HomeAssistant, entry, gateways) -> None:
    gateways.raw("rf-test", [900, -100] * 10, 2)
    gateways.fan("rf-test", "000001111101", 3)  # a fan not added yet
    _settle(hass)
    await hass.async_block_till_done()
    unknown = hass.states.get("sensor.rf_network_last_unrecognised_signal")
    assert unknown.state == "20" and unknown.attributes["raw"].startswith("raw:900,-100")
    last = hass.states.get("sensor.rf_network_last_code")
    assert last.attributes["suggestions"] == [
        {"template": "aircool_12bit_dip", "name": "Fan · Air Cool 12-bit DIP fan (Bond A3)", "address": "000001", "command": "off"}
    ]
    # The add-device flow pre-selects the template and fills in the address.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_device"})
    assert "address 000001" in result["description_placeholders"]["detected"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"template": "aircool_12bit_dip"})
    assert result["step_id"] == "device_details"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Basement Fan", "address": "000001", "gateway": "auto"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.states.get("fan.basement_fan") is not None


async def test_options_validation(hass: HomeAssistant, entry) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_device"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"template": "aircool_12bit_dip"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Dup", "address": "010101", "gateway": "auto"}
    )
    assert result["errors"] == {"address": "address_in_use"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Dup", "address": "0101", "gateway": "auto"}
    )
    assert result["errors"] == {"address": "invalid_address"}


async def test_template_errors_reported(hass: HomeAssistant, entry) -> None:
    # The broken user template is skipped; devices on missing templates raise a repair issue.
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "devices": {**entry.options["devices"], "x": {"template": "broken", "name": "X"}}}
    )
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "missing_templates") is not None
    assert hass.states.get(FAN_ID) is not None


async def test_migrate_from_0_1(hass: HomeAssistant, gateways) -> None:
    old = MockConfigEntry(
        domain=DOMAIN,
        title="RF Network",
        unique_id=DOMAIN,
        version=1,
        data={},
        options={
            "devices": {
                "a": {"profile": "fan_dip12", "name": "Old Fan", "address": "000001", "gateway": "auto"},
                "b": {"profile": "learned_buttons", "name": "Old Remote", "gateway": "auto",
                      "buttons": {"Off": "6:010101111101", "Other": "1:000100110101000110100011"}},
            },
            "settings": {},
        },
    )
    old.add_to_hass(hass)
    assert await hass.config_entries.async_setup(old.entry_id)
    await hass.async_block_till_done()
    assert old.version == 2
    assert old.options["devices"]["a"]["template"] == "aircool_12bit_dip"
    assert old.options["devices"]["b"]["buttons"]["Off"] == "aircool_12:010101111101"
    assert hass.states.get("fan.old_fan") is not None
