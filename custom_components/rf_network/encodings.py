"""Pulse encodings: turn bits into raw pulse timings and back.

Gateways only move raw timings (positive = carrier on, negative = off, in
microseconds). Every brand's bit format lives here, so supporting a new
remote never needs new gateway firmware.

The format follows the rc_switch family that most fixed-code remotes use:
each bit is a (high, low) pair measured in units of `pulse` microseconds, a
sync pair is sent before the bits, and "inverted" encodings start each pair
with the low part.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import voluptuous as vol

PAIR = vol.All([vol.All(int, vol.Range(min=1, max=255))], vol.Length(min=2, max=2))

ENCODING_SCHEMA = vol.Schema(
    {
        vol.Required("pulse"): vol.All(int, vol.Range(min=10, max=10000)),
        vol.Required("sync"): PAIR,
        vol.Required("zero"): PAIR,
        vol.Required("one"): PAIR,
        vol.Optional("inverted", default=False): bool,
        vol.Required("bits"): vol.All(int, vol.Range(min=4, max=64)),
        vol.Optional("tolerance", default=50): vol.All(int, vol.Range(min=5, max=80)),
        vol.Optional("description", default=""): str,
    }
)


@dataclass(frozen=True)
class Encoding:
    """One bit format."""

    id: str
    pulse: int
    sync: tuple[int, int]
    zero: tuple[int, int]
    one: tuple[int, int]
    inverted: bool
    bits: int
    tolerance: int = 50
    description: str = ""

    @classmethod
    def from_config(cls, enc_id: str, conf: dict[str, Any]) -> Encoding:
        """Build from a validated config dict."""
        conf = ENCODING_SCHEMA(conf)
        return cls(
            id=enc_id,
            pulse=conf["pulse"],
            sync=tuple(conf["sync"]),
            zero=tuple(conf["zero"]),
            one=tuple(conf["one"]),
            inverted=conf["inverted"],
            bits=conf["bits"],
            tolerance=conf["tolerance"],
            description=conf["description"],
        )

    # ------------------------------------------------------------- encode
    def _pair(self, units: tuple[int, int]) -> list[int]:
        high, low = units[0] * self.pulse, units[1] * self.pulse
        return [-high, low] if self.inverted else [high, -low]

    def encode(self, bits: str) -> list[int]:
        """Raw timings for one frame: sync, then the bits."""
        if len(bits) != self.bits or set(bits) - {"0", "1"}:
            raise ValueError(f"{self.id} needs exactly {self.bits} bits of 0/1, got {bits!r}")
        timings = self._pair(self.sync)
        for bit in bits:
            timings += self._pair(self.one if bit == "1" else self.zero)
        return timings

    # ------------------------------------------------------------- decode
    def _near(self, value: int, units: int) -> bool:
        expected = units * self.pulse
        return expected * (100 - self.tolerance) / 100 <= value <= expected * (100 + self.tolerance) / 100

    def decode(self, timings: list[int]) -> str | None:
        """Bits of one received frame, or None if it is not this encoding.

        A frame starts after a long gap, so the long half of the sync pair
        is usually missing: the capture starts at the sync's short half
        (inverted) or directly at the first bit.
        """
        t = timings
        n = len(t)

        def mark(i: int, units: int) -> bool:
            return i < n and t[i] > 0 and self._near(t[i], units)

        def space(i: int, units: int) -> bool:
            return i < n and t[i] < 0 and self._near(-t[i], units)

        def pair(i: int, units: tuple[int, int]) -> bool:
            if self.inverted:
                return space(i, units[0]) and mark(i + 1, units[1])
            return mark(i, units[0]) and space(i + 1, units[1])

        i = 0
        if self.inverted:
            if mark(0, self.sync[1]):
                i = 1
        elif pair(0, self.sync):
            i = 2

        bits = ""
        while len(bits) < self.bits:
            if pair(i, self.zero):
                bits += "0"
            elif pair(i, self.one):
                bits += "1"
            else:
                break
            i += 2

        # Non-inverted: the last bit's low half runs into the gap and is lost.
        if len(bits) == self.bits - 1 and not self.inverted and i == n - 1:
            if mark(i, self.zero[0]) and not mark(i, self.one[0]):
                bits += "0"
            elif mark(i, self.one[0]):
                bits += "1"

        return bits if len(bits) == self.bits else None


def parse_raw(text: str) -> list[int]:
    """'350,-700,350' (or with spaces) -> [350, -700, 350]."""
    return [int(v) for v in text.replace(" ", "").split(",") if v]


def raw_matches(a: list[int], b: list[int], tolerance: int = 35) -> bool:
    """Whether two raw frames are the same signal, within a tolerance."""
    if len(a) != len(b) or not a:
        return False
    for x, y in zip(a, b, strict=True):
        if (x > 0) != (y > 0):
            return False
        if abs(abs(x) - abs(y)) > abs(y) * tolerance / 100:
            return False
    return True
