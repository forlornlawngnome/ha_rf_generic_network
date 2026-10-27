"""Encoding and template tests, including real captures."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from custom_components.rf_network.library import load_library

from .conftest import EV_ENC, FAN_ENC, LIB, frame

# Raw captures logged by an ESP32 + CC1101 (at 302 MHz, slightly off tune)
# while pressing keys on an Air Cool remote with all DIP switches up. The
# frames that came through cleanly are the remote's release code.
REAL = Path(__file__).parent / "fixtures" / "aircool_dip_all_up.txt"


def test_real_captures_decode_like_esphome() -> None:
    counts: Counter = Counter()
    for line in REAL.read_text().splitlines():
        timings = [int(v) for v in line.split(",")]
        counts[FAN_ENC.decode(timings)] += 1
    # The clean frames decode to the release code; fragments do not decode.
    assert counts["000001111111"] == 18
    assert set(counts) == {"000001111111", None}


def test_roundtrip() -> None:
    for enc, bits in ((FAN_ENC, "010101110111"), (EV_ENC, "101100111000111100001010")):
        assert enc.decode(frame(enc, bits)) == bits
    # Non-inverted frames whose last low half ran into the gap.
    assert EV_ENC.decode(EV_ENC.encode("101100111000111100001011")[2:]) == "101100111000111100001011"
    assert FAN_ENC.decode([300, -300, 300]) is None


def test_fan_template() -> None:
    tpl = LIB.templates["aircool_12bit_dip"]
    assert tpl.split("aircool_12:010101110111") == ("010101", "110111")
    assert tpl.identify("110111") == "speed_1"
    assert tpl.identify("011111") == "speed_6"
    assert tpl.identify("101110") == "light_toggle"  # any combination with the light key
    assert tpl.identify("111111") == "release"
    assert tpl.command_code("010101", "speeds", 3) == "aircool_12:010101101111"
    found = LIB.detect("aircool_12:000001111101")
    assert [(t.id, a, c) for t, a, c in found] == [("aircool_12bit_dip", "000001", "off")]


def test_user_templates_and_errors(tmp_path) -> None:
    from .conftest import write_user_templates

    write_user_templates(str(tmp_path))
    lib = load_library(str(tmp_path))
    assert "test_shade" in lib.templates and "aircool_12bit_dip" in lib.templates
    assert any("broken.yaml" in e and "unknown encoding" in e for e in lib.errors)
