"""Device templates: what a brand of RF device sends, as YAML files.

Templates live in `templates/<fans|lights|covers|generic>/*.yaml` inside the
integration, and in `<config>/rf_network/templates/**` for your own. A
template names an encoding, how many leading bits are the per-device
address, and the command bits for each action its device type expects.
A user template with the same file name replaces a built-in one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import re
from typing import Any

import voluptuous as vol
import yaml

from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .encodings import Encoding

_LOGGER = logging.getLogger(__name__)

BUILTIN_DIR = Path(__file__).parent / "templates"
USER_DIR_NAME = DOMAIN  # <config>/rf_network/

TYPE_FAN = "fan"
TYPE_LIGHT = "light"
TYPE_COVER = "cover"
TYPE_BUTTONS = "buttons"
TYPES = (TYPE_FAN, TYPE_LIGHT, TYPE_COVER, TYPE_BUTTONS)
TYPE_LABELS = {TYPE_FAN: "Fan", TYPE_LIGHT: "Light", TYPE_COVER: "Cover", TYPE_BUTTONS: "Remote"}

# Commands each type understands. Anything else in `commands` is rejected,
# except for `buttons` templates where every command is a button.
TYPE_COMMANDS: dict[str, dict[str, bool]] = {
    # name: required
    TYPE_FAN: {"speeds": True, "off": False, "reverse": False, "light_toggle": False,
               "light_on": False, "light_off": False, "release": False},
    TYPE_LIGHT: {"toggle": False, "on": False, "off": False, "brightness_up": False,
                 "brightness_down": False, "release": False},
    TYPE_COVER: {"open": True, "close": True, "stop": False, "release": False},
}

BITS = vol.All(str, vol.Match(r"^[01]+$"))
PATTERN = vol.All(str, vol.Match(r"^[01?]+$"))

LIGHT_SCHEMA = vol.Schema(
    {
        vol.Optional("dim_step_repeats"): vol.All(int, vol.Range(min=2, max=200)),
        vol.Optional("hold_ms", default=700): vol.All(int, vol.Range(min=100, max=5000)),
    }
)

TEMPLATE_SCHEMA = vol.Schema(
    {
        vol.Required("name"): str,
        vol.Required("type"): vol.In(TYPES),
        vol.Required("frequency_mhz"): vol.All(vol.Coerce(float), vol.Range(min=300, max=928)),
        vol.Required("encoding"): vol.Any(str, dict),
        vol.Optional("address_bits", default=0): vol.All(int, vol.Range(min=0, max=63)),
        vol.Optional("address_example", default=""): str,
        vol.Optional("repeat_count"): vol.All(int, vol.Range(min=1, max=100)),
        vol.Optional("device_class"): str,
        vol.Required("commands"): {str: vol.Any(BITS, [BITS])},
        vol.Optional("match", default={}): {str: [PATTERN]},
        vol.Optional("light", default={}): LIGHT_SCHEMA,
    }
)


@dataclass
class DeviceTemplate:
    """A validated template."""

    id: str
    name: str
    type: str
    frequency_mhz: float
    encoding: Encoding
    address_bits: int
    address_example: str
    repeat_count: int | None
    device_class: str | None
    commands: dict[str, Any]
    match: dict[str, list[str]]
    light: dict[str, Any]
    source: str = ""
    # flat list of (command name, bits) used to recognise received codes
    _lookup: list[tuple[str, str]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        for name, value in self.commands.items():
            if isinstance(value, list):
                self._lookup += [(f"{name.removesuffix('s')}_{i}", bits) for i, bits in enumerate(value, start=1)]
            else:
                self._lookup.append((name, value))

    @property
    def command_bits(self) -> int:
        """Length of the command part of a code."""
        return self.encoding.bits - self.address_bits

    @property
    def label(self) -> str:
        """Name for menus."""
        return f"{TYPE_LABELS[self.type]} · {self.name}"

    def has(self, command: str) -> bool:
        """Whether the template defines a command."""
        return command in self.commands

    def code(self, address: str, command_bits: str) -> str:
        """Code string for a device address and command bits."""
        return f"{self.encoding.id}:{address}{command_bits}"

    def command_code(self, address: str, command: str, index: int | None = None) -> str:
        """Code for a named command (index is 1-based for list commands)."""
        value = self.commands[command]
        bits = value[index - 1] if isinstance(value, list) else value
        return self.code(address, bits)

    def split(self, code: str) -> tuple[str, str] | None:
        """(address, command bits) if the code uses this template's encoding."""
        enc, _, bits = code.partition(":")
        if enc != self.encoding.id or len(bits) != self.encoding.bits:
            return None
        return bits[: self.address_bits], bits[self.address_bits :]

    def identify(self, command_bits: str) -> str | None:
        """Command name for received command bits ("speeds_3", "off", ...)."""
        for name, bits in self._lookup:
            if bits == command_bits:
                return name
        for name, patterns in self.match.items():
            for pattern in patterns:
                if len(pattern) == len(command_bits) and all(
                    p in ("?", c) for p, c in zip(pattern, command_bits, strict=True)
                ):
                    return name
        return None


class TemplateError(ValueError):
    """A template file is invalid."""


def _validate(tid: str, conf: dict[str, Any], encodings: dict[str, Encoding], source: str) -> DeviceTemplate:
    try:
        conf = TEMPLATE_SCHEMA(conf)
    except vol.Invalid as err:
        raise TemplateError(str(err)) from err
    enc_conf = conf["encoding"]
    if isinstance(enc_conf, str):
        if enc_conf not in encodings:
            raise TemplateError(f"unknown encoding '{enc_conf}'")
        encoding = encodings[enc_conf]
    else:
        encoding = Encoding.from_config(f"{tid}_enc", enc_conf)
    if conf["address_bits"] >= encoding.bits:
        raise TemplateError("address_bits must be smaller than the encoding's bits")
    command_len = encoding.bits - conf["address_bits"]
    ttype = conf["type"]
    commands = conf["commands"]
    if ttype in TYPE_COMMANDS:
        allowed = TYPE_COMMANDS[ttype]
        if unknown := set(commands) - set(allowed):
            raise TemplateError(f"{ttype} templates do not use: {', '.join(sorted(unknown))}")
        if missing := [c for c, req in allowed.items() if req and c not in commands]:
            raise TemplateError(f"{ttype} templates need: {', '.join(missing)}")
    if ttype == TYPE_LIGHT and "toggle" not in commands and not {"on", "off"} <= set(commands):
        raise TemplateError("light templates need `toggle`, or both `on` and `off`")
    if ttype == TYPE_FAN and not isinstance(commands["speeds"], list):
        raise TemplateError("`speeds` must be a list, slowest first")
    for name, value in commands.items():
        for bits in value if isinstance(value, list) else [value]:
            if len(bits) != command_len:
                raise TemplateError(f"command '{name}' must be {command_len} bits, got '{bits}'")
    for name, patterns in conf["match"].items():
        if any(len(p) != command_len for p in patterns):
            raise TemplateError(f"match patterns for '{name}' must be {command_len} characters")
    return DeviceTemplate(
        id=tid,
        name=conf["name"],
        type=ttype,
        frequency_mhz=conf["frequency_mhz"],
        encoding=encoding,
        address_bits=conf["address_bits"],
        address_example=conf["address_example"],
        repeat_count=conf.get("repeat_count"),
        device_class=conf.get("device_class"),
        commands=commands,
        match=conf["match"],
        light=conf["light"],
        source=source,
    )


@dataclass
class Library:
    """All encodings and templates, plus problems found while loading."""

    encodings: dict[str, Encoding]
    templates: dict[str, DeviceTemplate]
    errors: list[str]

    def detect(self, code: str) -> list[tuple[DeviceTemplate, str, str]]:
        """Templates that recognise a code: (template, address, command)."""
        found = []
        for tpl in self.templates.values():
            if (parts := tpl.split(code)) is None:
                continue
            address, cmd_bits = parts
            if (command := tpl.identify(cmd_bits)) and command != "release":
                found.append((tpl, address, command))
        return found


class _Loader(yaml.SafeLoader):
    """YAML 1.2-style booleans: only true/false, so `on:`/`off:` stay strings."""


_Loader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:bool"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def _read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return yaml.load(handle, Loader=_Loader) or {}  # noqa: S506 - SafeLoader subclass


def load_library(config_dir: str | None) -> Library:
    """Load built-in and user encodings/templates (blocking: run in executor)."""
    errors: list[str] = []
    roots = [BUILTIN_DIR]
    if config_dir:
        roots.append(Path(config_dir) / USER_DIR_NAME)

    encodings: dict[str, Encoding] = {}
    for root in roots:
        path = root / "encodings.yaml"
        if not path.is_file():
            continue
        try:
            for enc_id, conf in (_read_yaml(path) or {}).items():
                encodings[str(enc_id)] = Encoding.from_config(str(enc_id), conf)
        except (OSError, yaml.YAMLError, vol.Invalid, TypeError, AttributeError) as err:
            errors.append(f"{path}: {err}")

    templates: dict[str, DeviceTemplate] = {}
    for root in roots:
        tdir = root if root == BUILTIN_DIR else root / "templates"
        if not tdir.is_dir():
            continue
        for path in sorted(tdir.glob("*/*.yaml")):
            tid = path.stem
            try:
                templates[tid] = _validate(tid, _read_yaml(path), encodings, str(path))
            except (OSError, yaml.YAMLError, TemplateError, vol.Invalid, TypeError) as err:
                errors.append(f"{path}: {err}")
    for message in errors:
        _LOGGER.error("RF Network template problem: %s", message)
    return Library(encodings=encodings, templates=templates, errors=errors)


async def async_get_library(hass: HomeAssistant, *, reload: bool = False) -> Library:
    """The loaded library, cached until reload."""
    store = hass.data.setdefault(DOMAIN, {})
    if reload or "library" not in store:
        store["library"] = await hass.async_add_executor_job(load_library, hass.config.config_dir)
    return store["library"]
