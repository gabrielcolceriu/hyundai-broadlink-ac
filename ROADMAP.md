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
- [ ] **Enter pairing mode** on the AC (remote key combo / module button) — guided.
- [ ] **Wi-Fi provisioning from inside HA** via BroadLink **SmartConfig** — user enters SSID +
      password, HA broadcasts the credentials. No app, no cloud account.
- [ ] **LAN discovery** of the freshly paired module (device type `0x507A` / `0x507C`).
- [ ] **Obtain the local AES key:**
  - [ ] Short-term: guided **UART read** (instructions + photos of the `log-Rx/log-Tx/GND` header),
        then paste the `Aes PWd:` key into the flow.
  - [ ] Research: can a fresh local SmartConfig pairing yield a usable key **without UART**?
        (The BroadLink "DNA" module currently rejects the standard local auth — that is exactly
        why the UART tap is needed today.)
- [ ] **Validate** local control and create the entities.
- [ ] **Config-flow UX:** multi-step pop-ups with instructions, images and per-step validation.

## Nice to have
- [ ] DHCP auto-discovery of already-paired modules.
- [ ] Re-key / diagnostics flow for when the key rotates after a re-pair.
- [ ] Submit the brand to [home-assistant/brands](https://github.com/home-assistant/brands) and to HACS default.

## Done
- [x] Local LAN control with the UART-recovered AES key.
- [x] Full entity set (climate + switches + select + sensors + binary sensors), EN/RO labels & icons.
- [x] Packaged as a HACS custom repository (v0.0.1).
