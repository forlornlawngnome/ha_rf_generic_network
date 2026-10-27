"""Config and options flows for RF Network."""

from __future__ import annotations

import re
from typing import Any
import uuid

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_ADDRESS,
    CONF_BURST_GAP,
    CONF_BUTTONS,
    CONF_DEVICES,
    CONF_ECHO_WINDOW,
    CONF_GATEWAY,
    CONF_NAME,
    CONF_PROFILE,
    CONF_REPEATS,
    CONF_SETTINGS,
    DEFAULT_BURST_GAP,
    DEFAULT_ECHO_WINDOW,
    DEFAULT_REPEATS,
    DOMAIN,
    ESPHOME_DOMAIN,
    GATEWAY_AUTO,
    GATEWAY_SERVICE_SUFFIX,
    NAME,
    PROFILE_BUTTONS,
    PROFILE_FAN_A3,
)
from .devices import format_buttons, parse_buttons

ADDRESS_RE = re.compile(r"^[01]{6}$")
CONF_DEVICE = "device"


class RFNetworkConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the single RF Network entry."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(
                title=NAME,
                data={},
                options={CONF_DEVICES: {}, CONF_SETTINGS: {}},
            )
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return RFNetworkOptionsFlow()


class RFNetworkOptionsFlow(OptionsFlow):
    """Add, edit and remove RF devices; change settings."""

    def __init__(self) -> None:
        self._edit_id: str | None = None

    # ------------------------------------------------------------ helpers
    @property
    def _devices(self) -> dict[str, dict[str, Any]]:
        return dict(self.config_entry.options.get(CONF_DEVICES, {}))

    def _save(self, devices: dict[str, Any] | None = None, settings: dict[str, Any] | None = None) -> ConfigFlowResult:
        options = dict(self.config_entry.options)
        if devices is not None:
            options[CONF_DEVICES] = devices
        if settings is not None:
            options[CONF_SETTINGS] = settings
        return self.async_create_entry(data=options)

    def _gateway_selector(self) -> SelectSelector:
        suffix = f"_{GATEWAY_SERVICE_SUFFIX}"
        services = self.hass.services.async_services().get(ESPHOME_DOMAIN, {})
        gateways = sorted(n[: -len(suffix)] for n in services if n.endswith(suffix))
        options = [SelectOptionDict(value=GATEWAY_AUTO, label="Automatic (the gateway that hears it best)")]
        options += [SelectOptionDict(value=g, label=g) for g in gateways]
        return SelectSelector(SelectSelectorConfig(options=options, custom_value=True, mode=SelectSelectorMode.DROPDOWN))

    def _device_selector(self, profile: str | None = None) -> SelectSelector:
        options = [
            SelectOptionDict(value=dev_id, label=conf[CONF_NAME])
            for dev_id, conf in self._devices.items()
            if profile is None or conf.get(CONF_PROFILE) == profile
        ]
        return SelectSelector(SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN))

    def _name_taken(self, name: str, ignore: str | None = None) -> bool:
        return any(
            conf[CONF_NAME].strip().lower() == name.strip().lower()
            for dev_id, conf in self._devices.items()
            if dev_id != ignore
        )

    # --------------------------------------------------------------- menu
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = ["add_fan", "add_buttons"]
        if any(c.get(CONF_PROFILE) == PROFILE_BUTTONS for c in self._devices.values()):
            menu.append("edit_buttons")
        if self._devices:
            menu.append("remove_device")
        menu.append("settings")
        return self.async_show_menu(step_id="init", menu_options=menu)

    # ---------------------------------------------------------------- fan
    async def async_step_add_fan(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip()
            name = user_input[CONF_NAME].strip()
            if not ADDRESS_RE.match(address):
                errors[CONF_ADDRESS] = "invalid_address"
            elif any(
                c.get(CONF_PROFILE) == PROFILE_FAN_A3 and c.get(CONF_ADDRESS) == address
                for c in self._devices.values()
            ):
                errors[CONF_ADDRESS] = "address_in_use"
            if not name or self._name_taken(name):
                errors[CONF_NAME] = "name_in_use"
            if not errors:
                devices = self._devices
                devices[uuid.uuid4().hex[:10]] = {
                    CONF_PROFILE: PROFILE_FAN_A3,
                    CONF_NAME: name,
                    CONF_ADDRESS: address,
                    CONF_GATEWAY: user_input.get(CONF_GATEWAY) or GATEWAY_AUTO,
                }
                return self._save(devices=devices)
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_ADDRESS): str,
                vol.Required(CONF_GATEWAY, default=GATEWAY_AUTO): self._gateway_selector(),
            }
        )
        return self.async_show_form(
            step_id="add_fan",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    # ------------------------------------------------------------ buttons
    async def async_step_add_buttons(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._buttons_form("add_buttons", user_input, dev_id=None)

    async def async_step_edit_buttons(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._edit_id = user_input[CONF_DEVICE]
            return await self.async_step_edit_buttons_codes()
        return self.async_show_form(
            step_id="edit_buttons",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE): self._device_selector(PROFILE_BUTTONS)}),
        )

    async def async_step_edit_buttons_codes(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._buttons_form("edit_buttons_codes", user_input, dev_id=self._edit_id)

    async def _buttons_form(
        self, step_id: str, user_input: dict[str, Any] | None, dev_id: str | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"error_detail": ""}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            if not name or self._name_taken(name, ignore=dev_id):
                errors[CONF_NAME] = "name_in_use"
            try:
                buttons = parse_buttons(user_input[CONF_BUTTONS])
            except ValueError as err:
                errors[CONF_BUTTONS] = "invalid_buttons"
                placeholders["error_detail"] = str(err)
            if not errors:
                devices = self._devices
                devices[dev_id or uuid.uuid4().hex[:10]] = {
                    CONF_PROFILE: PROFILE_BUTTONS,
                    CONF_NAME: name,
                    CONF_GATEWAY: user_input.get(CONF_GATEWAY) or GATEWAY_AUTO,
                    CONF_BUTTONS: buttons,
                }
                return self._save(devices=devices)
        suggested: dict[str, Any] = dict(user_input or {})
        if user_input is None and dev_id is not None:
            conf = self._devices[dev_id]
            suggested = {
                CONF_NAME: conf[CONF_NAME],
                CONF_GATEWAY: conf.get(CONF_GATEWAY, GATEWAY_AUTO),
                CONF_BUTTONS: format_buttons(conf.get(CONF_BUTTONS, {})),
            }
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_GATEWAY, default=GATEWAY_AUTO): self._gateway_selector(),
                vol.Required(CONF_BUTTONS): TextSelector(TextSelectorConfig(multiline=True)),
            }
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders=placeholders,
        )

    # ------------------------------------------------------------- remove
    async def async_step_remove_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            devices = self._devices
            devices.pop(user_input[CONF_DEVICE], None)
            return self._save(devices=devices)
        return self.async_show_form(
            step_id="remove_device",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE): self._device_selector()}),
        )

    # ----------------------------------------------------------- settings
    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self._save(settings={k: int(v) for k, v in user_input.items()})
        current = self.config_entry.options.get(CONF_SETTINGS, {})

        def num(lo: int, hi: int, unit: str | None = None) -> NumberSelector:
            return NumberSelector(
                NumberSelectorConfig(min=lo, max=hi, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement=unit)
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_REPEATS, default=current.get(CONF_REPEATS, DEFAULT_REPEATS)): num(1, 30),
                vol.Required(CONF_BURST_GAP, default=current.get(CONF_BURST_GAP, DEFAULT_BURST_GAP)): num(50, 2000, "ms"),
                vol.Required(CONF_ECHO_WINDOW, default=current.get(CONF_ECHO_WINDOW, DEFAULT_ECHO_WINDOW)): num(0, 5000, "ms"),
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)
