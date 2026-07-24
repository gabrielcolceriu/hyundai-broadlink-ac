# ✅ SOLVED — Local control AES key (2026-07-24)

![Debug-log UART header — where `Aes PWd:` prints](images/IMG_8169.jpeg)

## The discovery
The module **prints its AES key over UART at activation** (the `Aes PWd:` line).
The idea came from the user ("maybe it's in the boot section"). It was in our captures all along.

## The key + recipe (CONFIRMED — decrypts local traffic)

```
AES-128 key (local):    <DEVICE_KEY-from-.env>
IV (block 0, derived):  <derived-block0-iv>
Cipher:                 AES-128-CBC
Device id (0x30):       01 00 00 00  (0x00000001)
MAC:                    AA:BB:CC:DD:EE:FF
```

Other "Aes PWd" keys observed (from previous activations — they rotate on re-pairing):
`<redacted-aes-pwd>`, `<redacted-aes-pwd>`,
`<redacted-aes-pwd>`, `<DEVICE_KEY-from-.env>` (← the active one).

## Packet framing (local, Broadlink)
- Broadlink header, 0x38 bytes (magic `5aa5aa55 5aa5aa55`, devtype `7a50` at 0x24,
  command byte at 0x26, MAC at 0x2a, device id at 0x30, payload checksum at 0x34).
- **Payload from 0x38 onward = AES-128-CBC(JSON)** using the key above.
- Decrypted = a complete JSON object (~832 bytes): `{"if_function":0,"pwr":..,"temp":..,...}`.
- Command = only the changed field (`{"pwr":1}`); status = the full object.

## Key stability
- **Regenerated on every (re)pairing/activation** with the cloud.
- **Stable as long as the device stays paired** (does not change on a normal reboot).
- The current key is valid until the next re-pairing.
- **Self-recoverable:** the module prints it over UART (`Aes PWd:`), so a tap on the
  logging UART can re-read it at any time — full independence from the cloud.

## What's left (easy)
1. Confirm the per-packet IV scheme (we have known-plaintext; the block 0 IV is derived above).
2. Build a Broadlink encoder/decoder in Python (we have framing + key + id).
3. Send `{"pwr":1}` to `192.168.1.10:80`, verify on UART that `--> data:{"pwr":1}` appears.
4. Bridge → MQTT → Home Assistant (climate entity). **Zero cloud.**

## Verify (optional) whether it prints the key on EVERY boot
If `Aes PWd:` also appears on a normal boot (not just at pairing), an ESP/Arduino on the UART
can always read the current key at startup → a permanent solution even if the key rotates.

---

# UPDATE — The COMMAND protocol (fully decrypted)

## Command framing (phone→module), Broadlink packet 0x6a
```
0x00: 5aa5aa55 5aa5aa55            (magic)
0x08..0x1f: zero
0x20: [2B whole-packet checksum - DNA algorithm, still UNKNOWN]
0x24: 7a50  (devtype)   0x26: 6a 00  (command 0x6a "send")
0x28: [2B - per-packet checksum/nonce - UNKNOWN]
0x2a: FFEEDDCCBBAA (MAC)   0x30: 01000000 (device id FIXED)
0x34: [2B payload checksum - DNA]   0x36: 0000
0x38: payload = AES-128-CBC( plaintext ) with KEY + IV=562e17996d093d28ddb3ba695a2e6f58
```

## Plaintext payload (before AES)
```
[2B LE total = 12 + len(JSON)]
[a5 a5 5a 5a]                  (DNA magic, constant)
[2B JSON checksum - DNA, UNKNOWN]
[02 0b]                        (constant)
[4B LE len(JSON)]
[JSON]  e.g. {"pwr":1}
[zero padding up to a multiple of 16]
```
Confirmed examples (decrypted):
- {"pwr":1}  {"pwr":0}  {"tcl_mode":1}(heat)  {"tcl_mode":3}(cool)
- status query = {}  (76B packet)

## STATUS (module→phone): identical but with a long payload = {"if_function":0,...} (832B JSON)

## CONTROL blocker
- Byte-identical replay = RECEIVED but NOT applied -> source/nonce validation, not checksum.
- For generated commands: we need the DNA checksum algorithm (in libNetworkAPI.so) + a fresh nonce.
- Alternatively: spoof the source IP as the phone (to be tested, we have root).

## READ (monitoring) = FULLY FUNCTIONAL now (we decrypt the status stream).
