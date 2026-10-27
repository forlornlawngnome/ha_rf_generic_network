# RF Network

A Home Assistant integration for fixed-code RF devices (ceiling fans, shades,
lights, plug-in remotes) using one or more cheap ESPHome gateways (ESP32 +
CC1101) spread around the house.

- **Device templates, like Bond's.** Each brand is a YAML file that says how
  its codes are built. A device is just *template + address*; every code is
  generated. Templates are grouped by type: fans, lights, covers (shades,
  blinds, awnings) and generic remotes.
- **Any brand, any bit format.** Gateways only move raw pulse timings; all
  encoding and decoding happens in the integration, so a new remote never
  needs new firmware.
- **Any number of gateways, on any bands.** All gateways listen. A press heard
  by several gateways counts once. Each command goes out through a single
  gateway on the right band, falling back to the next if it is offline.
- **Recognises remotes.** Press a button on an unknown remote and RF Network
  suggests the matching template and address.
- **Remotes stay in sync, and work as triggers.** Using a wall remote updates
  Home Assistant, and every press fires an `rf_network_press` event.

## Install

1. HACS → ⋮ → Custom repositories → add this repository as type
   *Integration*, then install **RF Network** and restart Home Assistant.
2. Flash at least one gateway (see [Gateways](#gateways)) and add it to Home
   Assistant through the ESPHome integration.
3. In the ESPHome integration, open the gateway's **Configure** dialog and turn on
   **Allow the device to perform Home Assistant actions**. Without this,
   received codes never reach Home Assistant.
4. Settings → Devices & services → Add integration → **RF Network**.
5. Open RF Network's **Configure** to add devices.

## Gateways

A gateway is an ESPHome node running the RF Network firmware. It is
deliberately simple:

- It exposes an action `rf_network_transmit` (`timings`: list of µs, positive
  = carrier on; `repeat_count`; `frequency_mhz` to retune for that
  transmission, 0 = stay put).
- It fires `esphome.rf_network_raw` (`device`, `frequency_mhz`, `timings` as
  `"350,-700,..."`) for every capture, and `esphome.rf_network_hello`
  (`device`, `frequency_mhz`) on connect and every 5 minutes.

Gateways are discovered automatically. The **Gateways** sensor lists them
with the band each one listens on. A CC1101 board is built for one band, so
use one gateway (or one CC1101) per band you need, e.g. ~303 MHz fans and
433.92 MHz shades.

### Gateway firmware

The firmware is split so the RF logic never has to be touched when the
hardware changes:

| File | Contains |
|---|---|
| [`esphome/rf-network-core.yaml`](esphome/rf-network-core.yaml) | Everything board-independent: the transmit action, the receive event, CC1101 radio settings, drift recalibration, the live frequency box. Tunables are substitutions at the top. |
| [`esphome/hardware/esp32-devkit-cc1101.yaml`](esphome/hardware/esp32-devkit-cc1101.yaml) | ESP32 DevKit + CC1101: board, SPI bus, pins (all substitutions), wiring table. |
| [`esphome/hardware/waveshare-esp32-s3-eth-cc1101.yaml`](esphome/hardware/waveshare-esp32-s3-eth-cc1101.yaml) | Waveshare ESP32-S3-ETH (W5500, PoE) + CC1101 over Ethernet. |
| [`esphome/rf-gateway.example.yaml`](esphome/rf-gateway.example.yaml) | One gateway: name, secrets, network, pin overrides, and the package import. Copy it per gateway. |

Import the firmware straight from this repository in your own gateway
file, and remap anything with substitutions, without copying or editing the
shared files:

```yaml
substitutions:
  name: rf-gateway-1
  cc1101_gdo2_pin: GPIO27   # wired differently on this board

packages:
  rf_network:
    url: https://github.com/forlornlawngnome/ha_rf_generic_network
    ref: 0.2.0
    refresh: never
    files:
      - esphome/hardware/esp32-devkit-cc1101.yaml
      - esphome/rf-network-core.yaml
```

The full example, with the API key, OTA and Wi-Fi, is
[`esphome/rf-gateway.example.yaml`](esphome/rf-gateway.example.yaml).

- `ref:` pins the firmware to a [release](https://github.com/forlornlawngnome/ha_rf_generic_network/releases).
  A release never changes, so the gateway only updates when you change
  `ref:` to a newer one and install. ESPHome caches each ref separately, so a
  new `ref:` is downloaded on the next install.
- `refresh: never` stops ESPHome checking GitHub on every build; a release
  tag cannot change anyway.
- To follow the latest development instead, use `ref: main` with
  `refresh: 1d` (checks at most once a day). **Clean Build Files** does not
  re-download packages; it only deletes the compiled firmware.
- Hardware files do not set up Wi-Fi; add `wifi:` in the gateway file. The
  Ethernet hardware file sets up Ethernet itself, and ESPHome does not allow
  Wi-Fi and Ethernet on the same device.

#### Substitutions you can override

Set any of these in your gateway file's `substitutions:` to change it for
that gateway only.

Pins (defaults from the hardware file):

| Substitution | DevKit default | Waveshare default | |
|---|---|---|---|
| `spi_clk_pin` | GPIO18 | GPIO15 | CC1101 SCK |
| `spi_mosi_pin` | GPIO23 | GPIO16 | CC1101 MOSI (SI) |
| `spi_miso_pin` | GPIO19 | GPIO17 | CC1101 MISO (SO) |
| `cc1101_cs_pin` | GPIO5 | GPIO18 | CC1101 CSN |
| `cc1101_gdo0_pin` | GPIO4 | GPIO1 | CC1101 GDO0, transmit data |
| `cc1101_gdo2_pin` | GPIO26 | GPIO2 | CC1101 GDO2, receive data |
| `esp32_board` | esp32dev | (fixed) | PlatformIO board name |

Radio (defaults from `rf-network-core.yaml`):

| Substitution | Default | |
|---|---|---|
| `cc1101_frequency` | `303` | MHz the gateway listens on (its band) |
| `cc1101_filter_bandwidth` | `812kHz` | Wide, for remotes that drift |
| `rx_filter` | `50us` | Shorter pulses are ignored as noise |
| `rx_idle` | `4ms` | Silence that ends one captured frame |
| `rx_min_pulses` | `16` | Shorter captures are noise and not reported |
| `tx_repeat_gap` | `10ms` | Pause between repeats when sending |
| `rx_recalibrate_interval` | `30s` | How often the CC1101 retunes itself |

#### New hardware

For a board that needs more than pin changes, copy a hardware file. It must
define the `esp32:` platform, the `spi:` bus, and the substitutions
`cc1101_cs_pin`, `cc1101_gdo0_pin` and `cc1101_gdo2_pin`. Boards with
built-in Ethernet should also set up `ethernet:` there.

Bit formats are not set in the firmware any more: they live in the
integration's encodings and templates.

Codes are written `<encoding>:<bits>`, for example
`aircool_12:010101110111`, or `raw:<timings>` for signals no encoding knows.

Tips from the first build (CC1101 at ~303 MHz):

- Use the **RF Frequency** box on the gateway to tune live. Old remotes drift
  from their FCC frequency (one rated 302.0 MHz was strongest at 303.0).
- Keep `rx_filter` at 50us and `rx_idle` at 4ms. Larger values broke decoding.
- Turn on `dump: [raw]` in `remote_receiver` to see captures in the device log.
- A CC1101 board made for 315 MHz works better at ~300 MHz than a 433 MHz one.

## Devices

Open RF Network's **Configure**:

- **Add a device from a template.** Press a button on the device's remote
  first: RF Network pre-selects the matching template and fills in the
  address. Otherwise pick the template and type the address.
- **Add a remote from learned codes.** For anything no template covers:
  press each button, copy the code from the **Last code** sensor (or the raw
  code from **Last unrecognised signal**), and add one line per button.
  Each line becomes a button entity.

  ```
  Power = ev1527_24:000100110101000110100011
  Odd one = raw:500,-500,500,-1500,1500,-500
  ```

### Entities per template type

| Type | Entities |
|---|---|
| `fan` | Fan (speeds from the template, direction if it has `reverse`); Light if it has a light code; Light dim step if it sets `light.dim_step_repeats` |
| `light` | Light (on/off; tracked if there is only a toggle); Brighter / Dimmer buttons; Light dim step |
| `cover` | Cover with open / close (and stop); state is the last command sent or heard |
| `buttons` | One button per command |

State is assumed: these receivers never report back. Pressing the physical
remote updates it.

## Templates

Built-in templates are in
[`custom_components/rf_network/templates/`](custom_components/rf_network/templates):

```
templates/
  encodings.yaml        bit formats shared by templates
  fans/                 type: fan
  lights/               type: light
  covers/               type: cover   (shades, blinds, awnings, gates)
  generic/              type: buttons (remotes with no state)
```

Add your own in `<config>/rf_network/templates/<folder>/<name>.yaml` and
`<config>/rf_network/encodings.yaml`, then reload RF Network. A file with the
same name as a built-in one replaces it. Problems are written to the Home
Assistant log, and devices whose template is missing raise a repair issue.
Each folder has an `.example` file to copy.

### Template format

```yaml
name: Air Cool 12-bit DIP fan (Bond A3)
type: fan                   # fan, light, cover or buttons
frequency_mhz: 303          # sent through a gateway on this band
encoding: aircool_12        # from encodings.yaml, or an inline encoding
address_bits: 6             # leading bits unique to each device
address_example: "010101"
repeat_count: 8             # optional; else the integration setting
commands:                   # the rest of the code, per command
  speeds: ["110111", "110101", "101111", "100111", "011101", "011111"]
  off: "111101"
  reverse: "111011"
  light_toggle: "111110"
  release: "111111"         # optional "key let go" frame, ignored
match:                      # optional: extra patterns (? = any bit)
  light_toggle: ["?????0"]
light:                      # optional, for lights and fan lights
  dim_step_repeats: 33      # holding the key this many frames nudges a dimmer
  hold_ms: 700              # longer presses are holds, not toggles
```

Commands by type:

| Type | Required | Optional |
|---|---|---|
| `fan` | `speeds` (list, slowest first) | `off`, `reverse`, `light_toggle`, `light_on`, `light_off`, `release` |
| `light` | `toggle`, or `on` + `off` | `brightness_up`, `brightness_down`, `release` |
| `cover` | `open`, `close` | `stop`, `release`; also `device_class:` |
| `buttons` | any names | each becomes a button |

### Encodings

An encoding turns bits into pulses (`templates/encodings.yaml`):

```yaml
ev1527_24:
  pulse: 350        # µs per unit
  sync: [1, 31]     # [high, low] in units, sent before the bits
  zero: [1, 3]
  one: [3, 1]
  inverted: false   # true: each pair starts with the low half
  bits: 24
  tolerance: 50     # % timing error accepted when decoding
```

Built in: `aircool_12` (Air Cool / Hampton Bay fans) and `ev1527_24` (the
common EV1527 / PT2262 433 MHz format used by many cheap remotes).

To work out a new remote: set `dump: [raw]` on a gateway, press a button a
few times, and read the pulse lengths. Most fixed-code remotes are one short
and one long pulse per bit. Codes that change on every press of the same
button are *rolling codes* and cannot be replayed.

## Automations

```yaml
trigger:
  - platform: event
    event_type: rf_network_press
    event_data:
      device: Living Room Fan
      command: light_toggle
```

Event data: `code`, `gateways`, `frames`, `duration_ms`, `device`,
`device_id`, `command`, and `suggestions` (matching templates, for presses
from devices not added yet). Commands are the template's names
(`speed_1`…, `off`, `reverse`, `light_toggle`, `light_toggle_hold`,
`open`, …) or the learned button name.

## Settings

| Setting | Default | |
|---|---|---|
| Repeats per command | 8 | Unless the template sets its own. Too few: missed. Too many: a light toggle becomes dimming |
| Silence that ends a press | 250 ms | Captures closer than this are one press |
| Ignore echoes for | 600 ms | Gateways hear our own transmissions |

## Upgrading from 0.1.0

- Update every gateway to the 0.2.0 firmware (`ref: 0.2.0`). 0.2.0 gateways
  send raw pulses; 0.1.0 gateways are not recognised.
- The integration migrates your devices on its own: fans become the
  `aircool_12bit_dip` template and learned `6:` codes become `aircool_12:`.
- Automations on `rf_network_press` now see `light_toggle` instead of
  `light`.

## Versions

Releases are tagged `MAJOR.MINOR.PATCH` (e.g. `0.1.0`, no `v`). One tag covers both the Home
Assistant integration (HACS shows it as the version to install) and the
gateway firmware (`ref:` in the gateway file). Release notes say when a
gateway needs updating alongside the integration; until then, any gateway
on the same major version works.

## Development

```
pip install pytest-homeassistant-custom-component
pytest
```
