# Roadmap — fully local, cloud-free

**Goal:** provision and run the module **100 % locally** — never touch the TCL/BroadLink cloud or
the *Intelligent AC* app, with a **guided setup (pop-ups) inside the Home Assistant config flow**.

## Independence & security
- [ ] **Block the module from the internet** (firewall rule / isolated IoT VLAN) so the vendor
      cannot push OTA firmware or collect telemetry. Local control needs no cloud, so this costs
      nothing. See [Staying independent](README.md#staying-independent-no-cloud-no-ota).
- [ ] Document the exact MikroTik rules (address-list by module MAC → drop forward to WAN, keep LAN + HA).

## Fully-local onboarding (guided config flow)
- [ ] **Reset / de-cloud** the module (factory reset via the on-board button) — guided, with photos.
- [ ] **Enter pairing mode** on the AC (remote key combo / module button) — guided, with photos.
- [ ] **Wi-Fi provisioning from inside HA (no cloud):** in pairing mode the module exposes a SoftAP
      (`Air conditioner_XXXX`, gateway `192.168.10.1` / `192.168.4.1` / `10.10.100.254`). Connect, send
      SSID + password, module joins the LAN. Port the logic from jestempablo's
      [`tools/tcl-ac-provision.mjs`](https://github.com/jestempablo/home-assistant-tcl-intelligent-ac/blob/main/tools/tcl-ac-provision.mjs).
- [ ] **LAN discovery** of the freshly paired module (device type `0x507A` / `0x507C`).
- [ ] **Obtain the local AES key — try automatic first:**
  - [ ] **Auto (no UART, no cloud):** standard BroadLink LAN auth (command `0x0065`, decrypt with init
        key `097628…`, key = response bytes `0x04..0x13`). Works on non-locked modules (e.g. XA71I
        `0x507C`). The integration already ships this in `protocol.py` (`authenticate_tcl_ac_device`) —
        the config flow just needs to try it.
  - [ ] **Fallback A — app WebView bridge:** drive the Intelligent AC app's Cordova WebView over
        `adb` + Chrome DevTools (`com.ab.smartDevice`) to read the key, per jestempablo's
        [`tools/intelligent-ac-webview-bridge.mjs`](https://github.com/jestempablo/home-assistant-tcl-intelligent-ac/blob/main/tools/intelligent-ac-webview-bridge.mjs).
  - [ ] **Fallback B — UART read (our case):** locked modules (`bl2 locked`, our Hyundai `0x507A`)
        print the key on boot (`Aes PWd:`); guided read + paste. See [`docs/00-SOLVED-KEY.md`](docs/00-SOLVED-KEY.md).
- [ ] **Validate** local control and create the entities.
- [ ] **Config-flow UX:** multi-step pop-ups (pairing → provisioning → auto-auth → fallback if needed →
      done), with instructions, images and per-step validation.

## Feasibility findings (researched 2026-07-24)

Cross-checked against jestempablo, RazvanManolache, python-broadlink #806 and the HA community:

- **The lock is set by cloud/app provisioning, not by hardware.** A locked module (`LOCKED=True`,
  auth fails `0xffff`) can be cleared by a **deep Wi-Fi-module / factory reset** (remove/re-add in
  the app alone is NOT enough — one documented case). After a reset + **accountless local (SoftAP)
  re-pair**, the module comes up `LOCKED=False` and returns the key over standard LAN auth `0x0065`
  — **no UART needed**. (Empirical; validate on a real unit before relying on it.)
- **Everything except first-time provisioning can already run fully in HA:** discovery + `0x0065`
  auto-key + control — this is the existing `local_discovery` step in `config_flow.py`.
- **Wi-Fi provisioning cannot run inside HA.** These modules only support **SoftAP (join-the-AP)**;
  even `python-broadlink.setup()` is AP-mode. A headless HA server can't leave the LAN to join the
  AC's `Air conditioner_XXXX` hotspot, so provisioning stays a **one-time laptop/phone step**.
- **Our UART `Aes PWd` recovery appears to be novel** for these DNA `0x507A`/`0x507C` modules — no
  other public project extracts the key that way; everyone else relies on `0x0065` LAN auth. It is
  the fallback for units that stay locked.

**Net:** for an *unlocked, already-paired* module the fully-local-from-HA flow already works. For a
*locked* one (like this Hyundai), the only path to "unlocked, auto-key from HA" is a one-time
factory-reset + local SoftAP re-pair on a laptop/phone — it cannot be done from HA alone, and cannot
be done without a reset.

## Nice to have
- [ ] DHCP auto-discovery of already-paired modules.
- [ ] Re-key / diagnostics flow for when the key rotates after a re-pair.

## Credits for the roadmap approach
The local provisioning (SoftAP) and the automatic key-over-LAN-auth path are proven in
[jestempablo/home-assistant-tcl-intelligent-ac](https://github.com/jestempablo/home-assistant-tcl-intelligent-ac)
(`tools/` + `docs/reverse-engineering-notes.md`). This project adds the UART key-recovery path for
locked Hyundai `0x507A` modules where LAN auth is refused.

## Done
- [x] Local LAN control with the UART-recovered AES key.
- [x] Full entity set (climate + switches + select + sensors + binary sensors), EN/RO labels & icons.
- [x] Packaged as a HACS custom repository (v0.0.1).
