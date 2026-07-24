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
