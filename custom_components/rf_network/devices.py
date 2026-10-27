"""Device profiles: how a kind of RF device maps codes to commands.

A profile turns a small amount of configuration (an address, or a list of
learned codes) into the codes to send and a way to recognise received codes.
Entities use the profile; the hub uses `matches`/`describe` to label presses.

To add a new kind of device, subclass RFDevice, register it in PROFILES and
add the entities it needs to the platforms.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CONF_ADDRESS,
    CONF_BUTTONS,
    CONF_GATEWAY,
    CONF_NAME,
    CONF_PROFILE,
    CONF_PROTOCOL,
    DOMAIN,
    GATEWAY_AUTO,
    PROFILE_BUTTONS,
    PROFILE_FAN_A3,
)

if TYPE_CHECKING:
    from .hub import Press, RFNetwork

CODE_RE = re.compile(r"^(\d+:[01]+|raw:-?\d+(,-?\d+)*)$")

# A press longer than this is a "hold" (e.g. ramping a dimmer), not a tap.
HOLD_THRESHOLD_S = 0.7


def split_code(code: str) -> tuple[str, str]:
    """'6:010101110111' -> ('6', '010101110111')."""
    proto, _, bits = code.partition(":")
    return proto, bits


class RFDevice:
    """Base class for one physical RF device."""

    profile: str = ""
    model: str = "RF device"

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

    async def async_send(self, code: str, *, repeat_count: int | None = None, action: str = "") -> str:
        """Send a code through the best gateway for this device."""
        return await self.hub.async_send(
            code,
            repeat_count=repeat_count,
            preferred=self.gateway,
            match=self.matches,
            action=action or self.name,
        )


@dataclass(frozen=True)
class FanCommand:
    """Decoded meaning of a fan code."""

    kind: str  # "speed", "off", "reverse", "light", "light_hold"
    speed: int = 0


class FanDip12(RFDevice):
    """Ceiling fan receiver with a 4-DIP address and 6 active-low key lines.

    Frames are 12 bits (rc_switch protocol 6 shape): 6 address bits then 6
    key bits, where a 0 means "pressed". Key bits, left to right:
    speed 3, speed 2, speed 1, reverse, off, light. All-ones is the release
    frame. Extra speeds are two keys at once. Verified on Bond template A3.
    """

    profile = PROFILE_FAN_A3
    model = "Ceiling fan (12-bit DIP, Bond A3)"

    RELEASE = "111111"
    LIGHT = "111110"
    OFF = "111101"
    REVERSE = "111011"
    # Speed 1 (slowest) .. 6 (fastest). 1, 3 and 6 are the remote's own
    # speed keys; 2, 4 and 5 are two-key combinations.
    SPEEDS = ("110111", "110101", "101111", "100111", "011101", "011111")
    DEFAULT_SPEED = 3
    # Holding the light key ramps the dimmer; about 33 frames is ~1 s.
    DIM_STEP_REPEATS = 33

    def __init__(self, hub: RFNetwork, dev_id: str, conf: dict[str, Any]) -> None:
        super().__init__(hub, dev_id, conf)
        self.address: str = conf[CONF_ADDRESS]
        self.protocol: str = str(conf.get(CONF_PROTOCOL) or "6")

    @property
    def speed_count(self) -> int:
        """Number of fan speeds."""
        return len(self.SPEEDS)

    def code(self, keys: str) -> str:
        """Full code for a 6-bit key pattern."""
        return f"{self.protocol}:{self.address}{keys}"

    def speed_code(self, speed: int) -> str:
        """Code for speed 1..speed_count."""
        return self.code(self.SPEEDS[speed - 1])

    def matches(self, code: str) -> bool:
        proto, bits = split_code(code)
        return proto == self.protocol and len(bits) == 12 and bits[:6] == self.address

    def decode(self, press: Press) -> FanCommand | None:
        """Meaning of a received press for this fan, if any."""
        keys = split_code(press.code)[1][6:]
        if keys == self.RELEASE:
            return None
        if keys[5] == "0":
            # Every key combination with the light line toggles the light.
            return FanCommand("light_hold" if press.duration >= HOLD_THRESHOLD_S else "light")
        if keys in self.SPEEDS:
            return FanCommand("speed", self.SPEEDS.index(keys) + 1)
        if keys == self.OFF:
            return FanCommand("off")
        if keys == self.REVERSE:
            return FanCommand("reverse")
        return None

    def describe(self, press: Press) -> str | None:
        cmd = self.decode(press)
        if cmd is None:
            keys = split_code(press.code)[1][6:]
            return None if keys == self.RELEASE else f"unknown_{keys}"
        return f"speed_{cmd.speed}" if cmd.kind == "speed" else cmd.kind


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
            raise ValueError(f"Line {lineno}: use 'Button name = 6:010101110111'")
        if not CODE_RE.match(code):
            raise ValueError(f"Line {lineno}: '{code}' is not a code like 6:010101110111")
        if name in buttons:
            raise ValueError(f"Line {lineno}: the button name '{name}' is used twice")
        buttons[name] = code
    if not buttons:
        raise ValueError("Add at least one button")
    return buttons


def format_buttons(buttons: dict[str, str]) -> str:
    """Inverse of parse_buttons."""
    return "\n".join(f"{name} = {code}" for name, code in buttons.items())


class LearnedButtons(RFDevice):
    """Any fixed-code remote: one button entity per learned code."""

    profile = PROFILE_BUTTONS
    model = "Learned RF buttons"

    def __init__(self, hub: RFNetwork, dev_id: str, conf: dict[str, Any]) -> None:
        super().__init__(hub, dev_id, conf)
        self.buttons: dict[str, str] = dict(conf.get(CONF_BUTTONS) or {})
        self._by_code = {code: name for name, code in self.buttons.items()}

    def matches(self, code: str) -> bool:
        return code in self._by_code

    def describe(self, press: Press) -> str | None:
        return self._by_code.get(press.code)


PROFILES: dict[str, type[RFDevice]] = {
    FanDip12.profile: FanDip12,
    LearnedButtons.profile: LearnedButtons,
}


def build_device(hub: RFNetwork, dev_id: str, conf: dict[str, Any]) -> RFDevice | None:
    """Create the device object for a stored device config."""
    cls = PROFILES.get(conf.get(CONF_PROFILE, ""))
    return cls(hub, dev_id, conf) if cls else None
