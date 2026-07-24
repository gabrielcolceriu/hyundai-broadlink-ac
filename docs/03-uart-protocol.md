# 03 — Control/Status Protocol (JSON over UART)

From UART (the firmware's debug console) we observed that the module works internally with
**JSON payloads** for control and status. These are the *decrypted* version of the messages
received/sent over the Broadlink transport on the LAN.

## Directions (log markers)

| Marker | Direction | Content |
|---|---|---|
| `--> data:` | **COMMAND** (app → module) | **minimal** JSON, only the changed field |
| `<-- data:` | **STATUS** (module → app) | **complete** JSON (~60 fields) |

### Observed commands (confirmed)
```
--> data: {"pwr":1}
--> data: {"pwr":0}
--> data: {"temp":250}
```
→ For control you send ONLY the desired field. You don't need the whole object.

### Status (complete object)
```json
<-- data: {"if_function":0,"pwr":1,"tcl_mode":3,"ecomode":0,"temp":250,
"tcl_mark":0,"qtmode":0,"pwfmode":0,"tcl_vdir":0,"tcl_hdir":0,"3dairmode":0,
"tempunit":0,"ac_health":0,"tcl_slp":0,"ac_photos":0,"desicmode":0,"bglight":0,
"beep":1,"smartdesic":0,"evaportor":0,"filter_check":0,"if_filterdirty":0,
"no_wfeeling":0,"el_heat":0,"clean_check":0,"humidity_check":0,"man_wind":0,
"auto_study":0,"autostd_cmd":0,"tcl_type":0,"air_quality":0,"envtempoutdoor":0,
"savemode":0,"save_temp":0,"target_kwh":0,"save_state":0,"dynamo":0,"ac_hwind":0,
"ac_lwind":0,"save_beg_t":"0,0","sava_stp_t":"0,0","envtemp":0,"in_vent_temp":0,
"in_coil_temp":0,"save_last_mode":0,"save_last_temp":0,"if_8heat":0,"8heat":0,
"warm_prompt":0,"ac_errcode1":0,"ac_errcode2":0,"tvoc_class":0,"pm25_class":0,
"pm25":0,"hcho":0,"co2_data":0,"tvoc_vol":0,"tvoc_q":0,"humidity":0}
```

## Field mapping

### ✅ Confirmed
| Field | Meaning | Observed values |
|---|---|---|
| `pwr` | On / Off | `1` = ON, `0` = OFF |
| `temp` | Set temperature (×10) | `250` = 25.0 °C, `260` = 26.0 °C |
| `beep` | Beep on command | `1` (active) |
| `tcl_mode` | Operating mode | `3` (only value seen — probably COOL) |

### 🔬 To be mapped (not exercised in the capture)
| Field | Assumed |
|---|---|
| `tcl_mode` | mode: auto/cool/dry/fan/heat — values to be determined |
| `man_wind`, `ac_hwind`, `ac_lwind` | fan speed (manual / high / low) |
| `tcl_vdir`, `tcl_hdir` | vertical / horizontal swing |
| `3dairmode` | 3D airflow |
| `ecomode`, `savemode` | eco mode |
| `tcl_slp` | sleep |
| `ac_health` | ionizer / health |
| `qtmode` | quiet mode |
| `pwfmode` | powerful / turbo |
| `el_heat`, `if_8heat`, `8heat` | electric heater / 8°C heat |
| `desicmode`, `smartdesic` | dehumidification |
| `bglight` | display light |
| `tempunit` | unit (°C/°F) |

### 📊 Sensors (read-only, were 0 — the board was NOT connected to the AC)
`envtemp` (room temp), `in_vent_temp`, `in_coil_temp`, `envtempoutdoor`,
`humidity`, `pm25`, `co2_data`, `hcho`, `tvoc_*`, `air_quality`,
`ac_errcode1/2` (error codes), `filter_check`, `clean_check`.

> All sensors were 0 because **the module was on the bench, without the AC main board**.
> When it is installed in the AC, the real values will appear here.

## How we obtain the complete mapping

With the module + UART running, press each function in the app in turn (mode, fan,
swing, eco, sleep...) and read the field that changes in `--> data:`. See
[`scripts/uart_capture.py`](scripts/uart_capture.py).

## Relevance for HA

- **Set:** send a JSON payload with the desired field over the Broadlink transport
  (`{"pwr":1}`, `{"temp":250}`, `{"tcl_mode":N}`, ...).
- **Get:** read the complete JSON object and map it into the HA `climate` entity
  (temperature, mode, fan, swing, plus sensors).
