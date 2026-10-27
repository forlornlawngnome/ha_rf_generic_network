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
2. Flash at least one gateway with [`esphome/rf-network-gateway.yaml`](esphome/rf-network-gateway.yaml)
   and add it to Home Assistant through the ESPHome integration.
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

Codes are strings of the form `<rc_switch protocol>:<bits>`, for example
`6:010101110111`.

Tips from the first build (CC1101 at ~303 MHz):

- Use the **RF Frequency** box on the gateway to tune live. Old remotes drift
  from their FCC frequency (one rated 302.0 MHz was strongest at 303.0).
- Keep `filter: 50us` and `idle: 4ms`. Larger values broke decoding.
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

## Development

```
pip install pytest-homeassistant-custom-component
pytest
```
