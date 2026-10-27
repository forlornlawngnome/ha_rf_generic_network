"""The RF Network hub: gateways, decoding, press detection and sending.

Gateways are ESPHome nodes running the RF Network gateway firmware. They only
move raw pulse timings. Everything else happens here:

* Each received capture is decoded with every known encoding into a code
  string such as `aircool_12:010101110111`.
* A remote press arrives as many captures (the remote repeats while a button
  is held), usually heard by several gateways. Captures of the same code are
  merged into one Press until the code has been silent for `burst_gap`.
* Codes we transmitted ourselves are ignored for `echo_window`.
* Transmissions are serialised across all gateways and each command goes
  out through exactly one gateway on the right band, falling back to the
  next one on failure. Two gateways transmitting at once would garble the
  signal or make a short press look like a held button.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later

from .const import (
    BAND_TOLERANCE_MHZ,
    DEFAULT_BURST_GAP,
    DEFAULT_ECHO_WINDOW,
    DEFAULT_REPEATS,
    ESPHOME_DOMAIN,
    GATEWAY_AUTO,
    GATEWAY_SERVICE_SUFFIX,
    HELLO_EVENT,
    PRESS_EVENT,
    RAW_EVENT,
    REPEAT_GAP_S,
    SIGNAL_PRESS,
)
from .encodings import parse_raw, raw_matches

if TYPE_CHECKING:
    from .devices import RFDevice
    from .library import Library

_LOGGER = logging.getLogger(__name__)

SIGNAL_UNKNOWN = "rf_network_unknown_signal"


def gateway_slug(device: str) -> str:
    """ESPHome node name -> the prefix of its action names (rf-test -> rf_test)."""
    return device.strip().lower().replace("-", "_").replace(" ", "_")


@dataclass
class Press:
    """One remote press, merged across captures and gateways."""

    code: str
    started: float
    last: float
    frames: int = 1
    gateways: set[str] = field(default_factory=set)

    @property
    def duration(self) -> float:
        """Seconds between the first and last capture of the press."""
        return self.last - self.started


@dataclass
class _Burst:
    press: Press
    cancel: CALLBACK_TYPE | None = None


class RFNetwork:
    """Shared state for the RF Network config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        library: Library,
        *,
        repeat_count: int = DEFAULT_REPEATS,
        burst_gap_ms: int = DEFAULT_BURST_GAP,
        echo_window_ms: int = DEFAULT_ECHO_WINDOW,
    ) -> None:
        self.hass = hass
        self.library = library
        self.repeat_count = repeat_count
        self.burst_gap = burst_gap_ms / 1000
        self.echo_window = echo_window_ms / 1000
        self.devices: list[RFDevice] = []
        self.last_press: Press | None = None
        self.last_press_info: dict[str, Any] = {}
        self.last_unknown: dict[str, Any] = {}
        self.gateway_bands: dict[str, float] = {}
        self._bursts: dict[str, _Burst] = {}
        self._echo_until: dict[str, float] = {}
        self._heard: dict[str, dict[str, float]] = {}
        self._send_lock = asyncio.Lock()
        self._unsubs: list[CALLBACK_TYPE] = []

    # ------------------------------------------------------------------ setup
    @callback
    def async_start(self) -> None:
        """Start listening to gateway events."""
        self._unsubs = [
            self.hass.bus.async_listen(RAW_EVENT, self._handle_raw),
            self.hass.bus.async_listen(HELLO_EVENT, self._handle_hello),
        ]

    @callback
    def async_stop(self) -> None:
        """Stop listening and drop pending presses."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []
        for burst in self._bursts.values():
            if burst.cancel:
                burst.cancel()
        self._bursts.clear()

    # --------------------------------------------------------------- gateways
    @callback
    def gateways(self) -> list[str]:
        """Gateways currently offering the transmit action, by action prefix."""
        suffix = f"_{GATEWAY_SERVICE_SUFFIX}"
        services = self.hass.services.async_services().get(ESPHOME_DOMAIN, {})
        return sorted(name[: -len(suffix)] for name in services if name.endswith(suffix))

    def _record_band(self, gateway: str, value: Any) -> None:
        try:
            self.gateway_bands[gateway] = float(value)
        except (TypeError, ValueError):
            return

    @callback
    def _handle_hello(self, event: Event) -> None:
        gateway = gateway_slug(str(event.data.get("device") or ""))
        if gateway:
            self._record_band(gateway, event.data.get("frequency_mhz"))

    @callback
    def gateway_order(
        self, preferred: str, match: Callable[[str], bool], frequency_mhz: float = 0
    ) -> list[str]:
        """Gateways to try, best first.

        Gateways listening on a different band are left out. A fixed
        preference goes first; the rest are ordered by how recently each one
        heard a code belonging to the device, then gateways whose band is not
        known yet.
        """
        candidates = []
        for gw in self.gateways():
            band = self.gateway_bands.get(gw)
            if frequency_mhz and band is not None and abs(band - frequency_mhz) > BAND_TOLERANCE_MHZ:
                continue
            candidates.append(gw)
        last_heard: dict[str, float] = {}
        for code, heard in self._heard.items():
            if match(code):
                for gw, when in heard.items():
                    last_heard[gw] = max(when, last_heard.get(gw, 0.0))
        candidates.sort(key=lambda gw: (-last_heard.get(gw, 0.0), gw not in self.gateway_bands, gw))
        if preferred and preferred != GATEWAY_AUTO and preferred in candidates:
            candidates.remove(preferred)
            candidates.insert(0, preferred)
        return candidates

    # ---------------------------------------------------------------- sending
    def timings_for(self, code: str) -> list[int]:
        """Raw timings of one frame of a code."""
        enc_id, _, bits = code.partition(":")
        if enc_id == "raw":
            return parse_raw(bits)
        encoding = self.library.encodings.get(enc_id)
        if encoding is None:
            raise HomeAssistantError(f"Unknown encoding '{enc_id}' in code {code}")
        return encoding.encode(bits)

    async def async_send(
        self,
        code: str,
        *,
        frequency_mhz: float = 0,
        repeat_count: int | None = None,
        preferred: str = GATEWAY_AUTO,
        match: Callable[[str], bool] | None = None,
    ) -> str:
        """Transmit `code` through one gateway; return the gateway used."""
        timings = self.timings_for(code)
        repeats = repeat_count or self.repeat_count
        order = self.gateway_order(preferred, match or (lambda c: c == code), frequency_mhz)
        if not order:
            band = f" on {frequency_mhz:g} MHz" if frequency_mhz else ""
            raise HomeAssistantError(
                f"No RF Network gateway{band} is online. Check that the ESPHome gateway is "
                f"connected and runs the RF Network firmware (action '{GATEWAY_SERVICE_SUFFIX}')"
            )
        airtime = repeats * (sum(abs(t) for t in timings) / 1_000_000 + REPEAT_GAP_S)
        last_error: Exception | None = None
        async with self._send_lock:
            for gateway in order:
                self._echo_until[code] = time.monotonic() + airtime + self.echo_window
                try:
                    await self.hass.services.async_call(
                        ESPHOME_DOMAIN,
                        f"{gateway}_{GATEWAY_SERVICE_SUFFIX}",
                        {
                            "timings": timings,
                            "repeat_count": repeats,
                            "frequency_mhz": float(frequency_mhz),
                        },
                        blocking=True,
                    )
                except HomeAssistantError as err:
                    _LOGGER.warning("Gateway %s could not send %s: %s", gateway, code, err)
                    last_error = err
                    continue
                # The gateway transmits in the background; keep the lock until
                # it is done so no other gateway transmits over it.
                await asyncio.sleep(airtime + 0.05)
                self._echo_until[code] = time.monotonic() + self.echo_window
                _LOGGER.debug("Sent %s x%s via %s", code, repeats, gateway)
                return gateway
        raise HomeAssistantError(f"No gateway could send {code}: {last_error}")

    # -------------------------------------------------------------- receiving
    def decode(self, timings: list[int]) -> str | None:
        """Code string for one capture, or None if nothing recognises it."""
        for encoding in self.library.encodings.values():
            if (bits := encoding.decode(timings)) is not None:
                return f"{encoding.id}:{bits}"
        for device in self.devices:
            for code in device.raw_codes():
                if raw_matches(timings, parse_raw(code[4:])):
                    return code
        return None

    @callback
    def _handle_raw(self, event: Event) -> None:
        gateway = gateway_slug(str(event.data.get("device") or "unknown"))
        self._record_band(gateway, event.data.get("frequency_mhz"))
        try:
            timings = parse_raw(str(event.data.get("timings") or ""))
        except ValueError:
            return
        code = self.decode(timings)
        if code is None:
            self.last_unknown = {
                "raw": "raw:" + ",".join(str(t) for t in timings),
                "gateway": gateway,
                "pulses": len(timings),
            }
            async_dispatcher_send(self.hass, SIGNAL_UNKNOWN)
            return
        self.handle_code(code, gateway)

    @callback
    def handle_code(self, code: str, gateway: str) -> None:
        """Feed one decoded capture into press detection."""
        now = time.monotonic()
        self._heard.setdefault(code, {})[gateway] = now
        if now < self._echo_until.get(code, 0.0):
            return

        burst = self._bursts.get(code)
        if burst is not None and now - burst.press.last <= self.burst_gap:
            burst.press.last = now
            burst.press.frames += 1
            burst.press.gateways.add(gateway)
            if burst.cancel:
                burst.cancel()
        else:
            if burst is not None:
                self._finish(code)
            burst = _Burst(Press(code=code, started=now, last=now, gateways={gateway}))
            self._bursts[code] = burst

        @callback
        def _finish_later(_now: Any, c: str = code) -> None:
            self._finish(c)

        burst.cancel = async_call_later(self.hass, self.burst_gap, _finish_later)

    @callback
    def _finish(self, code: str) -> None:
        burst = self._bursts.pop(code, None)
        if burst is None:
            return
        if burst.cancel:
            burst.cancel()
        press = burst.press
        info: dict[str, Any] = {
            "code": press.code,
            "gateways": sorted(press.gateways),
            "frames": press.frames,
            "duration_ms": round(press.duration * 1000),
            "device": None,
            "device_id": None,
            "command": None,
            "suggestions": [],
        }
        for device in self.devices:
            if device.matches(code):
                command = device.describe(press)
                if command is None:
                    # e.g. a "button released" frame: part of a press, not one.
                    return
                info.update(device=device.name, device_id=device.dev_id, command=command)
                break
        else:
            detected = self.library.detect(code)
            if any(cmd == "release" for _, _, cmd in detected):
                return
            info["suggestions"] = [
                {"template": tpl.id, "name": tpl.label, "address": address, "command": cmd}
                for tpl, address, cmd in detected
            ]
        self.last_press = press
        self.last_press_info = info
        self.hass.bus.async_fire(PRESS_EVENT, info)
        async_dispatcher_send(self.hass, SIGNAL_PRESS, press)
