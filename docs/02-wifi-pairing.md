# 02 — Connecting to WiFi (Pairing)

## Summary: what the problem was

The module refused to show up in the app. **The real cause was NOT the board** — it was the
WiFi network used during pairing.

The `MyWiFi-IOT` network (almost certainly) has **client isolation** and/or port filtering.
The effect:
- The board connected to WiFi ✅, got an IP ✅, DNS ✅, **HTTP activation with the cloud ✅**
- BUT the persistent discovery/heartbeat connection **was blocked** →
  `dis_server_count=0`, `dis_wifi_count=0`, `bl2_socket_work hb_type 0 timeout`
- → the app could never "see"/bind the board.

**The solution:** pair on the **main 2.4 GHz network** (`MyWiFi`, no isolation).
There it bound instantly.

## Status codes (`network status:N`)

Observed on UART (`[TCLISO] network status:N`):

| Status | Meaning (inferred) |
|---|---|
| 1 | Scanning / pairing mode (SmartConfig) — channel hopping |
| 6 | Connecting to AP (auth/assoc in progress) |
| 7 | Connected, DHCP obtained |
| 8 | Online, trying heartbeat/discovery (but unbound) |
| 9 | Online + cloud sync (RTC set) — advanced state |

Binding success signal: `dis_wifi_count` or `dis_server_count` **> 0**
(on the IOT network they always stayed 0; on the main one `device_probe` appeared).

## The key difference: IOT vs. main network

On the **main** network the log showed things that NEVER existed on IOT:
```
try Udp SUCCESS
cloud_read ... 8.209.100.108          (reads FROM the cloud, bidirectional)
ret 48 device_probe                    (the app probes the board LOCALLY)
socket_read ... 192.168.1.165           (the phone talks directly to the board)
```
→ proof that `MyWiFi-IOT` blocked local + persistent traffic.

## Pairing / SmartConfig mode

- The board enters pairing = **`status:1` + channel scanning** (`Channel 1 count`, `Channel 6 count`, ...).
- SmartConfig broadcasts **the network the phone is on** → so the phone doing the
  pairing MUST be on the target network (2.4 GHz).
- The module stores the credentials → on reboot it reconnects on its own (it does not re-enter pairing).

### How to force re-pairing WITHOUT a remote

The method that worked: **make the saved network unavailable** (disable/rename the
`MyWiFi-IOT` SSID in the router, or change the password), then power-cycle the module.
Unable to connect, the board **falls into SmartConfig mode** (`status:1` + scanning).

> A plain power-cycle (without changing the network) does NOT force pairing — the board
> reconnects to the stored WiFi. The 5V supply came from the Arduino Uno pin; the Uno's
> RESET button does NOT cut power to the module.

## The final procedure that worked

1. Phone (Android) on the **main 2.4 GHz network** (`MyWiFi`).
2. Disabled `MyWiFi-IOT` → power-cycled the module → it entered scanning (`status:1`).
3. SmartConfig from the app → the module received `WiFi SSID = MyWiFi PSK = ...`.
4. `auth success → association → DHCP → status:9`, then `device_probe` from the phone.
5. **Device added in the app.** ✅

## Rule to remember

The module must stay on a network **without client isolation** (the main network).
On `MyWiFi-IOT` it will NOT work unless you disable client isolation in the router.
The module is **2.4 GHz only**.
