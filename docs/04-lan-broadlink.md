# 04 — LAN / Broadlink: Discovery, Transport, the Crypto Wall

## Discovery (works)

`python-broadlink discover` finds the module:

| Field | Value |
|---|---|
| host | `192.168.1.10:80` (UDP) |
| MAC | `AA:BB:CC:DD:EE:FF` (in the packet: `FFEEDDCCBBAA`) |
| devtype | `0x507a` (= 20602) |
| python-broadlink class | generic `Device` (unsupported type) |

## Packet framing (classic Broadlink for LOCAL)

**Local** module↔phone packets use the Broadlink header `5aa5aa55 5aa5aa55` (0x38+):
- `0x24` devtype `7a50`
- `0x26` command byte (`0xee` on status responses — non-standard)
- `0x2a` module MAC
- `0x30` device id (`01000000` = 1)
- `0x34` payload checksum
- `0x38`/`0x3c` AES-CBC encrypted payload

## Two channels identified (from the MikroTik capture)

| Channel | Flow | Format | Port |
|---|---|---|---|
| **LOCAL** | `module:80 → phone:rnd` | Broadlink `5aa5aa55`, 908B status | 80 |
| **CLOUD** | `module:16387 → 8.209.100.108` | `d27fdf...` format | 1812 |

- The phone does **local polling** → the module replies with an **encrypted 908B status**.
- ON/OFF commands (when the phone is on the LAN) go **locally** phone→module.

## ❌ Standard local AUTH fails

- `auth 0x65` with the default Broadlink key → **error `0xfff9`** (licensed DNA device).
- Confirmed both by `python-broadlink` (`Authentication failed`) and by a manual test.
- On UART, at pairing: `bl2 locked, AUTH_FAIL`, `authcode:0000<your-did>...` (license).

## 🧱 THE WALL: the operational AES key

We extracted the keys from UART (pairing):
- `key:<your-32hex-aes-key>` (stable, 16×)
- `iv:<derived-iv-16B>`

**These keys do NOT decrypt the operational traffic** (neither local 908B nor cloud `d27fdf`).
Tested exhaustively: 3 keys × 4+ IVs × 8 offsets × CBC → 0 real results.

Verified conclusions:
- The local 908B payload: **53 unique blocks, 0 repeated** → AES-CBC correct (not ECB), key unknown.
- UART does **NOT log** the local key during normal operation (only at activation, and that one doesn't work).
- `<activation-key>` is most likely a **cloud activation session** key, NOT the local communication key.

### Why it's blocked
The local communication key is **provisioned from the cloud** at setup and stored on the module.
It does not appear in capturable traffic and cannot be derived from known-plaintext (AES is secure).

## Capture limitations (MikroTik)

- The RouterOS sniffer only catches **FROM_MOD** (the module's outbound traffic). The
  **phone→module** traffic is **switched in hardware** (switch chip) and never reaches the CPU → it isn't captured.
- So the local commands received by the module are NOT visible on MikroTik (only its responses).

## What's needed to break the wall (see `05`)

1. **Firmware/flash dump** (CH341A + flashrom) → extract the stored local key + license.
2. **Android app decompilation** → how the app derives/obtains the key from the cloud.
3. **UART-JSON bridge** → bypass the crypto entirely (the module gives us plaintext JSON on UART).
