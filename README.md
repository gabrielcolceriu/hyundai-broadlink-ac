# Hyundai AC — local Home Assistant integration

Local (cloud-free) [Home Assistant](https://www.home-assistant.io/) control for **Hyundai
HTAC** air conditioners that use the OEM **BroadLink "DNA"** Wi‑Fi module (the one paired with
the **Intelligent AC** mobile app). The integration talks to the module directly over the LAN
using its per‑device AES key — no cloud, no app required at runtime.

> This project pairs an existing Home Assistant integration for this BroadLink/DNA module with
> the reverse‑engineering work needed to recover the module's **local AES key straight from the
> device's UART**, so a Hyundai HTAC unit can be controlled entirely offline. See
> [How the local key was recovered](#how-the-local-key-was-recovered).

<p align="center">
  <img src="custom_components/hyundai_ac/icon.png" width="96" alt="Hyundai AC">
</p>

## Supported hardware

| | |
|---|---|
| AC models | Hyundai **HTAC‑09CHSD/XA71‑I**, **HTAC‑12CHSD/XA71‑I**, **HTAC‑18CHSD/XA71‑I**, **HTAC‑24CHSD/XA71‑I** |
| Wi‑Fi module | [Hyundai AC Wi‑Fi module](https://www.emarketon.ro/modul-wi-fi-aer-conditionat-hyundai-2019) (BroadLink **DNA**, OEM `OEM_TCLISO_******`) |
| Chipset | Realtek RTL8195A |
| Device type | `0x507A` (also `0x507C`) |
| App | Intelligent AC |
| Transport | LAN, UDP :80, AES‑128‑CBC |

Other white‑label brands ship the same BroadLink "DNA" module and may work as well.

## Features

One device with the full control surface, all local:

| Platform | Entities |
|---|---|
| `climate` | on/off, mode (cool / heat / dry / fan / auto), target temp (16–31 °C), fan speed (auto, low, mid‑low, medium, mid‑high, high), **vertical** swing |
| `switch` (9) | Turbo, Eco, Quiet, Display, Buzzer, Anti‑mildew, Health, Frost protection, Evaporator clean |
| `select` (1) | Sleep (off / normal / senior / child / custom) |
| `sensor` (5) | Outdoor temp, Coil temp, Vent temp, Error code 1, Error code 2 |
| `binary_sensor` (2) | Filter dirty, Clean check |

Fan speeds and swing ship with proper labels and icons (`icons.json` + translations, EN/RO).

## Installation

### HACS (recommended)
1. HACS → three‑dot menu → **Custom repositories**.
2. Add `https://github.com/gabrielcolceriu/hyundai-broadlink-ac`, category **Integration**.
3. Install **Hyundai AC**, then restart Home Assistant.

### Manual
Copy [`custom_components/hyundai_ac/`](custom_components/hyundai_ac) into your `config/custom_components/`
and restart Home Assistant.

## Configuration

**Settings → Devices & Services → Add Integration → “Hyundai AC”**, then provide:

| Field | Example | Notes |
|---|---|---|
| Host | `192.168.1.50` | The module's LAN IP — give it a DHCP reservation |
| MAC | `AA:BB:CC:DD:EE:FF` | The module's MAC |
| Key | `<32 hex chars>` | The **local AES key** — see below |
| Device type | `20602` | `0x507A` in decimal (default); `0x507C` = `20604` |

### Getting the local key
The AES key is provisioned per device and is **not** exposed by the app or the cloud API in a
convenient way. On this hardware it can be read directly from the module — see
[How the local key was recovered](#how-the-local-key-was-recovered) and
[`docs/00-SOLVED-KEY.md`](docs/00-SOLVED-KEY.md).

> ⚠️ The key rotates when the module is re‑paired. If you re‑add it in the Intelligent AC app,
> read the key again.

## How the local key was recovered

The BroadLink "DNA" module used by Hyundai HTAC units does **not** authenticate with the standard
BroadLink key, so the usual `python-broadlink` local auth fails. The recovery path documented here
was worked out hands‑on on a real unit:

1. **Identify the module.** With the module removed from the app, a BroadLink LAN scan reports it
   as an **unknown / new device type** — `0x507A`, internal name `OEM_TCLISO_******`. Node‑RED's
   BroadLink node likewise flags *“Unconfigured Device Type … may be a new device type.”* These
   findings were reported upstream: **[python‑broadlink issue #806](https://github.com/mjg59/python-broadlink/issues/806)**.
2. **Tap the UART.** Wire a 5 V USB‑UART adapter to the module's **TX/RX** test points and watch
   the serial console **while power‑cycling the board** (the key is printed early in the boot
   sequence, not at runtime).
3. **Capture the key at boot.** During start‑up the firmware prints its local AES key on the
   console (the `Aes PWd:` line). That 16‑byte value is the AES‑128‑CBC key used for all LAN
   traffic. Full pin‑out, framing and the exact boot line are in
   [`docs/00-SOLVED-KEY.md`](docs/00-SOLVED-KEY.md) and [`docs/04-lan-broadlink.md`](docs/04-lan-broadlink.md).
4. **Control locally.** With `key` + `mac` + `host`, Home Assistant encrypts JSON commands with
   AES‑128‑CBC inside the BroadLink packet framing and drives the AC over the LAN — no cloud.

The deeper reverse‑engineering notes (hardware teardown, Wi‑Fi pairing, UART control protocol,
LAN/BroadLink analysis) live under [`docs/`](docs).

## How it works (protocol)

- BroadLink packet: `0x38`‑byte header (magic `5aa5aa55…`, device type at `0x24`, MAC at `0x2a`,
  device id at `0x30`, checksum at `0x34`), then the payload from `0x38`.
- Payload = **AES‑128‑CBC(JSON)** with the per‑device key.
- **Command** = only the changed field (`{"pwr":1}`, `{"temp":250}`); **status** = the full JSON object.
- Implementation: [`custom_components/hyundai_ac/protocol.py`](custom_components/hyundai_ac/protocol.py).

## Credits

- Base integration: **[RazvanManolache/home-assistant-tcl-intelligent-ac-local](https://github.com/RazvanManolache/home-assistant-tcl-intelligent-ac-local)**,
  which is itself based on **[jestempablo/home-assistant-tcl-intelligent-ac](https://github.com/jestempablo/home-assistant-tcl-intelligent-ac)**.
- This project adds Hyundai HTAC support and documents the **local AES‑key recovery over UART** for
  the BroadLink/DNA `0x507A` module, so the unit works fully offline. Device‑type findings reported
  in [python‑broadlink #806](https://github.com/mjg59/python-broadlink/issues/806).

## Disclaimer

Independent project, not affiliated with Hyundai, BroadLink or the module's OEM. All reverse engineering was
done on the author's own equipment for interoperability and personal use. No firmware, vendor app
or other copyrighted material is included. Use at your own risk.

## License

[MIT](LICENSE).
