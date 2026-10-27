# RF Network

A Home Assistant integration for fixed-code RF devices (ceiling fans, shades,
plug-in remotes) using one or more cheap ESPHome gateways (ESP32 + CC1101)
spread around the house.

- **Any number of gateways.** All gateways listen. A press of a physical remote
  heard by several gateways counts once.
- **One transmitter at a time.** Each command goes out through a single
  gateway, falling back to the next if it is offline. Commands are queued so
  two gateways never transmit over each other.
- **Device profiles.** A profile turns a little configuration into entities.
  A ceiling fan needs only its 6-bit address; every code is generated.
- **Remotes stay in sync.** Using the wall remote updates the fan and light in
  Home Assistant.
- **Remotes as triggers.** Every press fires an `rf_network_press` event you
  can use in automations.

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

A gateway is any ESPHome node that exposes an action named
`transmit_rf_fan` (fields `action`, `code`, `repeat_count`) and fires
`esphome.rf_fan_received` (fields `device`, `action`, `code`) for every frame
it decodes. The provided YAML does both. Gateways are discovered
automatically; the **Gateways** sensor lists the ones online.

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
    ref: v0.1.0
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
| `cc1101_frequency` | `303` | MHz |
| `cc1101_filter_bandwidth` | `812kHz` | Wide, for remotes that drift |
| `rc_code_bits` | `12` | Bits per code reported to Home Assistant |
| `tx_pulse_length` | `333` | µs per timing unit when sending |
| `tx_sync_high` / `tx_sync_low` | `23` / `1` | Sync pulse, in units |
| `tx_zero_high` / `tx_zero_low` | `1` / `2` | A 0 bit, in units |
| `tx_one_high` / `tx_one_low` | `2` / `1` | A 1 bit, in units |
| `tx_inverted` | `true` | rc_switch protocol 6 is inverted |
| `rx_filter` | `50us` | Shorter pulses are ignored as noise |
| `rx_idle` | `4ms` | Silence that ends one received frame |
| `rx_recalibrate_interval` | `30s` | How often the CC1101 retunes itself |

#### New hardware

For a board that needs more than pin changes, copy a hardware file. It must
define the `esp32:` platform, the `spi:` bus, and the substitutions
`cc1101_cs_pin`, `cc1101_gdo0_pin` and `cc1101_gdo2_pin`. Boards with
built-in Ethernet should also set up `ethernet:` there.

Codes are strings of the form `<rc_switch protocol>:<bits>`, for example
`6:010101110111`.

Tips from the first build (CC1101 at ~303 MHz):

- Use the **RF Frequency** box on the gateway to tune live. Old remotes drift
  from their FCC frequency (one rated 302.0 MHz was strongest at 303.0).
- Keep `rx_filter` at 50us and `rx_idle` at 4ms. Larger values broke decoding.
- A CC1101 board made for 315 MHz works better at ~300 MHz than a 433 MHz one.

## Device profiles

### Ceiling fan (12-bit DIP, Bond template A3)

12-bit frames, rc_switch protocol 6 shape (~333 µs unit): 6 address bits
(4 DIP switches plus `01`) then 6 active-low key bits:
`speed 3, speed 2, speed 1, reverse, off, light`. `111111` is the
"released" frame.

| Entity | What it does |
|---|---|
| Fan | 6 speeds (1, 3 and 6 are the remote's keys; 2, 4, 5 are key combinations), direction |
| Light | On/off. The receiver only toggles, so state is tracked; remote presses resync it |
| Light dim step | Holds the light key ~1 s; the dimmer ramps in its current direction |

Add one with **Configure → Add a ceiling fan** and the first 6 digits of any
code from its remote, e.g. `010101`.

### Learned buttons

Any fixed-code remote. Press each button, copy the code from the **Last
code** sensor, and enter one line per button:

```
Open = 6:010101110111
Close = 6:010101101111
```

Each line becomes a button entity.

## Automations

```yaml
trigger:
  - platform: event
    event_type: rf_network_press
    event_data:
      device: Living Room Fan
      command: light
```

Event data: `code`, `gateways`, `frames`, `duration_ms`, `device`,
`device_id`, `command` (fans: `speed_1`…`speed_6`, `off`, `reverse`,
`light`, `light_hold`; learned buttons: the button name).

## Settings

| Setting | Default | |
|---|---|---|
| Repeats per command | 8 | Too few: missed. Too many: a light toggle becomes dimming |
| Silence that ends a press | 250 ms | Frames closer than this are one press |
| Ignore echoes for | 600 ms | Gateways hear our own transmissions |

## Adding a profile

Profiles live in `custom_components/rf_network/devices.py`. Subclass
`RFDevice`, implement `matches()` and `describe()`, register it in `PROFILES`,
then add the entities in the platform files and a step in `config_flow.py`.

## Versions

Releases are tagged `vMAJOR.MINOR.PATCH`. One tag covers both the Home
Assistant integration (HACS shows it as the version to install) and the
gateway firmware (`ref:` in the gateway file). Release notes say when a
gateway needs updating alongside the integration; until then, any gateway
on the same major version works.

## Development

```
pip install pytest-homeassistant-custom-component
pytest
```
