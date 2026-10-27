"""The RF Network hub: gateway discovery, press detection and sending.

Gateways are ESPHome nodes running the RF Network gateway firmware. They are
deliberately simple: they transmit what they are told and report every frame
they decode. Everything else happens here:

* A remote press arrives as many frames (the remote repeats while a button is
  held) and is usually heard by several gateways. Frames of the same code are
  merged into one Press until the code has been silent for `burst_gap`.
* Frames that match something we transmitted ourselves are ignored for
  `echo_window`, so our own commands do not look like remote presses.
* Transmissions are serialised across all gateways and each command goes out
  through exactly one gateway (falling back to the next one on failure). Two
  gateways transmitting at once would garble the signal or, worse, make a
  short press look like a held button.
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
    DEFAULT_BURST_GAP,
    DEFAULT_ECHO_WINDOW,
    DEFAULT_REPEATS,
    ESPHOME_DOMAIN,
    FRAME_AIRTIME_S,
    GATEWAY_AUTO,
    GATEWAY_EVENT,
    GATEWAY_SERVICE_SUFFIX,
    PRESS_EVENT,
    SIGNAL_PRESS,
)

if TYPE_CHECKING:
    from .devices import RFDevice

_LOGGER = logging.getLogger(__name__)


def gateway_slug(device: str) -> str:
    """ESPHome node name -> the prefix of its action names (rf-test -> rf_test)."""
    return device.strip().lower().replace("-", "_").replace(" ", "_")


@dataclass
class Press:
    """One remote press, merged across frames and gateways."""

    code: str
    started: float
    last: float
    frames: int = 1
    gateways: set[str] = field(default_factory=set)

    @property
    def duration(self) -> float:
        """Seconds between the first and last frame of the press."""
        return self.last - self.started


@dataclass
class _Burst:
    press: Press
    cancel: CALLBACK_TYPE | None = None


class RFNetwork:
    """Shared state for one RF Network config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        repeat_count: int = DEFAULT_REPEATS,
        burst_gap_ms: int = DEFAULT_BURST_GAP,
        echo_window_ms: int = DEFAULT_ECHO_WINDOW,
    ) -> None:
        self.hass = hass
        self.repeat_count = repeat_count
        self.burst_gap = burst_gap_ms / 1000
        self.echo_window = echo_window_ms / 1000
        self.devices: list[RFDevice] = []
        self.last_press: Press | None = None
        self.last_press_info: dict[str, Any] = {}
        self._bursts: dict[str, _Burst] = {}
        self._echo_until: dict[str, float] = {}
        self._heard: dict[str, dict[str, float]] = {}
        self._send_lock = asyncio.Lock()
        self._unsub: CALLBACK_TYPE | None = None

    # ------------------------------------------------------------------ setup
    @callback
    def async_start(self) -> None:
        """Start listening to gateway events."""
        self._unsub = self.hass.bus.async_listen(GATEWAY_EVENT, self._handle_frame)

    @callback
    def async_stop(self) -> None:
        """Stop listening and drop pending presses."""
        if self._unsub:
            self._unsub()
            self._unsub = None
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

    @callback
    def gateway_order(self, preferred: str, match: Callable[[str], bool]) -> list[str]:
        """Gateways to try, best first.

        A fixed preference goes first. The rest are ordered by how recently
        each one heard a code belonging to the device, so in "auto" mode a
        device is driven by the gateway that hears its remote.
        """
        available = self.gateways()
        last_heard: dict[str, float] = {}
        for code, heard in self._heard.items():
            if not match(code):
                continue
            for gateway, when in heard.items():
                last_heard[gateway] = max(when, last_heard.get(gateway, 0.0))
        order = sorted(available, key=lambda gw: (-last_heard.get(gw, 0.0), gw))
        if preferred and preferred != GATEWAY_AUTO and preferred in order:
            order.remove(preferred)
            order.insert(0, preferred)
        return order

    # ---------------------------------------------------------------- sending
    async def async_send(
        self,
        code: str,
        *,
        repeat_count: int | None = None,
        preferred: str = GATEWAY_AUTO,
        match: Callable[[str], bool] | None = None,
        action: str = "",
    ) -> str:
        """Transmit `code` through one gateway; return the gateway used."""
        repeats = repeat_count or self.repeat_count
        order = self.gateway_order(preferred, match or (lambda c: c == code))
        if not order:
            raise HomeAssistantError(
                "No RF Network gateway is online. Check that the ESPHome gateway "
                f"is connected and exposes the '{GATEWAY_SERVICE_SUFFIX}' action"
            )
        airtime = repeats * FRAME_AIRTIME_S
        last_error: Exception | None = None
        async with self._send_lock:
            for gateway in order:
                self._echo_until[code] = time.monotonic() + airtime + self.echo_window
                try:
                    await self.hass.services.async_call(
                        ESPHOME_DOMAIN,
                        f"{gateway}_{GATEWAY_SERVICE_SUFFIX}",
                        {"action": action or "send", "code": code, "repeat_count": repeats},
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
    @callback
    def _handle_frame(self, event: Event) -> None:
        code = str(event.data.get("code") or "").strip()
        if not code:
            return
        gateway = gateway_slug(str(event.data.get("device") or "unknown"))
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
        }
        for device in self.devices:
            if device.matches(code):
                command = device.describe(press)
                if command is None:
                    # e.g. a "button released" frame: part of a press, not one.
                    return
                info.update(device=device.name, device_id=device.dev_id, command=command)
                break
        self.last_press = press
        self.last_press_info = info
        self.hass.bus.async_fire(PRESS_EVENT, info)
        async_dispatcher_send(self.hass, SIGNAL_PRESS, press)
