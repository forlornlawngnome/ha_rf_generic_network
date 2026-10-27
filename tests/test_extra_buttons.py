"""Extra buttons on template devices."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_capture_events, async_fire_time_changed

from custom_components.rf_network.const import PRESS_EVENT


async def test_extra_button_sends_and_is_recognised(hass: HomeAssistant, entry, gateways) -> None:
    state = hass.states.get("button.living_room_fan_turbo")
    assert state is not None
    events = async_capture_events(hass, PRESS_EVENT)
    gateways.fan("rf-test", "010101010111", 4)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
    await hass.async_block_till_done()
    assert events[0].data["device"] == "Living Room Fan" and events[0].data["command"] == "Turbo"

    await hass.services.async_call("button", "press", {"entity_id": "button.living_room_fan_turbo"}, blocking=True)
    timings = list(gateways.calls[-1][1]["timings"])
    from .conftest import FAN_ENC

    assert FAN_ENC.decode(timings[1:]) == "010101010111"


async def test_edit_device_adds_buttons(hass: HomeAssistant, entry) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "edit_device" in result["menu_options"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "edit_device"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"device": "lr"})
    assert result["step_id"] == "edit_device_details"
    base = {"name": "Living Room Fan", "address": "010101", "gateway": "auto"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, "extra_buttons": "Turbo = 010111\nToo long = 0101110"}
    )
    assert result["errors"] == {"extra_buttons": "invalid_buttons"}
    assert "6 digits" in result["description_placeholders"]["error_detail"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**base, "extra_buttons": "Turbo = 010111\nBreeze = 101101"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.states.get("button.living_room_fan_breeze") is not None
    assert entry.options["devices"]["lr"]["extra_buttons"] == {"Turbo": "010111", "Breeze": "101101"}
