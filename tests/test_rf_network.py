"""Tests for RF Network."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_capture_events, async_fire_time_changed

from custom_components.rf_network.const import DOMAIN, PRESS_EVENT
from custom_components.rf_network.devices import parse_buttons

FAN_ID = "fan.living_room_fan"
LIGHT_ID = "light.living_room_fan_light"


def _settle(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))


async def test_config_flow_single_instance(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {"devices": {}, "settings": {}}
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT


async def test_entities_created(hass: HomeAssistant, entry) -> None:
    assert hass.states.get(FAN_ID) is not None
    assert hass.states.get(LIGHT_ID) is not None
    assert hass.states.get("button.living_room_fan_light_dim_step") is not None
    assert hass.states.get("button.led_strip_power") is not None
    assert hass.states.get("sensor.rf_network_gateways").state == "1"


async def test_fan_speed_sends_generated_code(hass: HomeAssistant, entry, gateways) -> None:
    await hass.services.async_call("fan", "set_percentage", {"entity_id": FAN_ID, "percentage": 100}, blocking=True)
    assert gateways.calls[-1] == ("rf_test", {"action": "fan_speed_6", "code": "6:010101011111", "repeat_count": 8})
    state = hass.states.get(FAN_ID)
    assert state.state == "on" and state.attributes["percentage"] == 100

    await hass.services.async_call("fan", "set_percentage", {"entity_id": FAN_ID, "percentage": 16}, blocking=True)
    assert gateways.calls[-1][1]["code"] == "6:010101110111"  # speed 1

    await hass.services.async_call("fan", "turn_off", {"entity_id": FAN_ID}, blocking=True)
    assert gateways.calls[-1][1]["code"] == "6:010101111101"
    assert hass.states.get(FAN_ID).state == "off"

    await hass.services.async_call("fan", "set_direction", {"entity_id": FAN_ID, "direction": "reverse"}, blocking=True)
    assert gateways.calls[-1][1]["code"] == "6:010101111011"


async def test_light_toggle_and_dim(hass: HomeAssistant, entry, gateways) -> None:
    await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT_ID}, blocking=True)
    assert gateways.calls[-1][1]["code"] == "6:010101111110"
    assert hass.states.get(LIGHT_ID).state == "on"
    n = len(gateways.calls)
    await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT_ID}, blocking=True)
    assert len(gateways.calls) == n  # already on: no toggle sent
    await hass.services.async_call("button", "press", {"entity_id": "button.living_room_fan_light_dim_step"}, blocking=True)
    assert gateways.calls[-1][1]["repeat_count"] == 33


async def test_remote_press_dedup_and_state(hass: HomeAssistant, entry, gateways) -> None:
    events = async_capture_events(hass, PRESS_EVENT)
    # One press of Speed 3-of-6 heard by two gateways, then the release frame.
    gateways.frames("rf-test", "6:010101101111", 6)
    gateways.frames("rf-attic", "6:010101101111", 4)
    gateways.frames("rf-test", "6:010101111111", 2)
    _settle(hass)
    await hass.async_block_till_done()

    assert len(events) == 1
    data = events[0].data
    assert data["code"] == "6:010101101111"
    assert data["gateways"] == ["rf_attic", "rf_test"]
    assert data["frames"] == 10
    assert data["device"] == "Living Room Fan" and data["command"] == "speed_3"

    state = hass.states.get(FAN_ID)
    assert state.state == "on" and state.attributes["percentage"] == 50
    assert hass.states.get("sensor.rf_network_last_code").state == "6:010101101111"


async def test_light_tap_toggles_hold_does_not(hass: HomeAssistant, entry, gateways) -> None:
    clock = [1000.0]
    with patch("custom_components.rf_network.hub.time.monotonic", side_effect=lambda: clock[0]):
        for _ in range(5):  # tap
            gateways.frames("rf-test", "6:010101111110", 1)
            clock[0] += 0.02
        _settle(hass)
        await hass.async_block_till_done()
        assert hass.states.get(LIGHT_ID).state == "on"

        clock[0] += 5
        for _ in range(60):  # hold ~1.2 s: dimming
            gateways.frames("rf-test", "6:010101111110", 1)
            clock[0] += 0.02
        _settle(hass)
        await hass.async_block_till_done()
        assert hass.states.get(LIGHT_ID).state == "on"


async def test_echo_of_own_command_ignored(hass: HomeAssistant, entry, gateways) -> None:
    events = async_capture_events(hass, PRESS_EVENT)
    await hass.services.async_call("light", "turn_on", {"entity_id": LIGHT_ID}, blocking=True)
    gateways.frames("rf-attic", "6:010101111110", 8)  # another gateway hears us
    _settle(hass)
    await hass.async_block_till_done()
    assert events == []
    assert hass.states.get(LIGHT_ID).state == "on"


async def test_fallback_and_auto_gateway(hass: HomeAssistant, entry, gateways) -> None:
    gateways.add("rf_attic")
    # The attic gateway heard the fan's remote most recently: auto picks it.
    gateways.frames("rf-attic", "6:010101111101", 3)
    _settle(hass)
    await hass.async_block_till_done()
    await hass.services.async_call("fan", "turn_off", {"entity_id": FAN_ID}, blocking=True)
    assert gateways.calls[-1][0] == "rf_attic"
    # If it fails, the other gateway is used.
    gateways.broken.add("rf_attic")
    await hass.services.async_call("fan", "turn_off", {"entity_id": FAN_ID}, blocking=True)
    assert gateways.calls[-1][0] == "rf_test"


async def test_learned_button(hass: HomeAssistant, entry, gateways) -> None:
    await hass.services.async_call("button", "press", {"entity_id": "button.led_strip_red"}, blocking=True)
    assert gateways.calls[-1][1]["code"] == "1:000100110101000110100101"
    events = async_capture_events(hass, PRESS_EVENT)
    gateways.frames("rf-test", "1:000100110101000110100011", 4)
    _settle(hass)
    await hass.async_block_till_done()
    assert events[0].data["device"] == "LED Strip" and events[0].data["command"] == "Power"


async def test_options_add_fan_and_remove(hass: HomeAssistant, entry) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_fan"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Basement Fan", "address": "010101", "gateway": "auto"}
    )
    assert result["errors"] == {"address": "address_in_use"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Basement Fan", "address": "000001", "gateway": "auto"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.states.get("fan.basement_fan") is not None

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "remove_device"})
    basement = next(k for k, v in entry.options["devices"].items() if v["name"] == "Basement Fan")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"device": basement})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.states.get("fan.basement_fan") is None or hass.states.get("fan.basement_fan").state == "unavailable"


async def test_options_buttons_validation(hass: HomeAssistant, entry) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_buttons"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Shade", "gateway": "auto", "buttons": "Open = 6:0101\nClose 6:1"}
    )
    assert result["errors"] == {"buttons": "invalid_buttons"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Shade", "gateway": "auto", "buttons": "Open = 6:0101\nClose = 6:0110"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


def test_parse_buttons() -> None:
    assert parse_buttons("# comment\nA = 6:0101\n\nB = raw:350,-700,350") == {"A": "6:0101", "B": "raw:350,-700,350"}
