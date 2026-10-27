"""RF devices: a template plus an address, or a set of learned codes."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CONF_ADDRESS,
    CONF_BUTTONS,
    CONF_GATEWAY,
    CONF_NAME,
    CONF_TEMPLATE,
    DOMAIN,
    GATEWAY_AUTO,
    TEMPLATE_LEARNED,
)

if TYPE_CHECKING:
    from .hub import Press, RFNetwork
    from .library import DeviceTemplate, Library

CODE_RE = re.compile(r"^([A-Za-z0-9_]+:[01]+|raw:-?\d+(,-?\d+)*)$")

# Commands where holding the key does something else (ramping a dimmer).
HOLDABLE = ("light_toggle", "light_on", "light_off")


class RFDevice:
    """Base class for one physical RF device."""

    model = "RF device"
    frequency_mhz: float = 0

    def __init__(self, hub: RFNetwork, dev_id: str, conf: dict[str, Any]) -> None:
        self.hub = hub
        self.dev_id = dev_id
        self.conf = conf
        self.name: str = conf[CONF_NAME]
        self.gateway: str = conf.get(CONF_GATEWAY) or GATEWAY_AUTO

    @property
    def device_info(self) -> DeviceInfo:
        """Home Assistant device for this RF device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.dev_id)},
            name=self.name,
            manufacturer="RF Network",
            model=self.model,
        )

    def matches(self, code: str) -> bool:
        """Whether a received code belongs to this device."""
        raise NotImplementedError

    def describe(self, press: Press) -> str | None:
        """Command name for a press; None if the press should be ignored."""
        raise NotImplementedError

    def raw_codes(self) -> list[str]:
        """Learned raw codes the hub should match captures against."""
        return []

    async def async_send_code(self, code: str, *, repeat_count: int | None = None) -> str:
        """Send a code through the best gateway for this device."""
        return await self.hub.async_send(
            code,
            frequency_mhz=self.frequency_mhz,
            repeat_count=repeat_count,
            preferred=self.gateway,
            match=self.matches,
        )


class TemplateDevice(RFDevice):
    """A device described by a template: the address is its only setting."""

    def __init__(self, hub: RFNetwork, dev_id: str, conf: dict[str, Any], template: DeviceTemplate) -> None:
        super().__init__(hub, dev_id, conf)
        self.template = template
        self.address: str = conf.get(CONF_ADDRESS, "")
        self.frequency_mhz = template.frequency_mhz
        self.model = template.name

    @property
    def type(self) -> str:
        """Template type: fan, light, cover or buttons."""
        return self.template.type

    def has(self, command: str) -> bool:
        """Whether the template defines a command."""
        return self.template.has(command)

    def code(self, command: str, index: int | None = None) -> str:
        """Code string for a named command."""
        return self.template.command_code(self.address, command, index)

    async def async_command(self, command: str, index: int | None = None, *, repeat_count: int | None = None) -> str:
        """Send a named command."""
        return await self.async_send_code(
            self.code(command, index), repeat_count=repeat_count or self.template.repeat_count
        )

    def matches(self, code: str) -> bool:
        parts = self.template.split(code)
        return parts is not None and parts[0] == self.address

    def command(self, press: Press) -> str | None:
        """Command name of a received press ("speed_2", "off", "light_toggle_hold", ...)."""
        parts = self.template.split(press.code)
        if parts is None:
            return None
        name = self.template.identify(parts[1])
        if name in HOLDABLE and press.duration * 1000 >= self.template.light.get("hold_ms", 700):
            return f"{name}_hold"
        return name

    def describe(self, press: Press) -> str | None:
        name = self.command(press)
        if name == "release":
            return None
        return name or f"unknown_{self.template.split(press.code)[1]}"


def parse_buttons(text: str) -> dict[str, str]:
    """Parse 'Name = code' lines. Raises ValueError with a readable message."""
    buttons: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, code = line.partition("=")
        name, code = name.strip(), code.strip().replace(" ", "")
        if not sep or not name or not code:
            raise ValueError(f"Line {lineno}: use 'Button name = aircool_12:010101110111'")
        if not CODE_RE.match(code):
            raise ValueError(f"Line {lineno}: '{code}' is not a code like aircool_12:010101110111 or raw:350,-700,…")
        if name in buttons:
            raise ValueError(f"Line {lineno}: the button name '{name}' is used twice")
        buttons[name] = code
    if not buttons:
        raise ValueError("Add at least one button")
    return buttons


def format_buttons(buttons: dict[str, str]) -> str:
    """Inverse of parse_buttons."""
    return "\n".join(f"{name} = {code}" for name, code in buttons.items())


class LearnedDevice(RFDevice):
    """Any remote no template covers: one button entity per learned code."""

    model = "Learned RF remote"

    def __init__(self, hub: RFNetwork, dev_id: str, conf: dict[str, Any]) -> None:
        super().__init__(hub, dev_id, conf)
        self.buttons: dict[str, str] = dict(conf.get(CONF_BUTTONS) or {})
        self._by_code = {code: name for name, code in self.buttons.items()}

    def matches(self, code: str) -> bool:
        return code in self._by_code

    def describe(self, press: Press) -> str | None:
        return self._by_code.get(press.code)

    def raw_codes(self) -> list[str]:
        return [code for code in self.buttons.values() if code.startswith("raw:")]


def build_device(hub: RFNetwork, library: Library, dev_id: str, conf: dict[str, Any]) -> RFDevice | None:
    """Create the device object for a stored device config, if possible."""
    tid = conf.get(CONF_TEMPLATE)
    if tid == TEMPLATE_LEARNED:
        return LearnedDevice(hub, dev_id, conf)
    template = library.templates.get(tid or "")
    if template is None:
        return None
    return TemplateDevice(hub, dev_id, conf, template)
