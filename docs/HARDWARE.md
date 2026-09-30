# Hardware and network notes

## USR-C322 WiFi module

The printer's only network hardware is a Shenzhen USR IOT `USR-C322`
serial-to-WiFi module, reported as `USR-WIFI-SET` by its own web UI.

| | |
|---|---|
| Module firmware | `2.18.06` (UI says `Web Ver: 1.0.1`) |
| Vendor | USR IOT Technology Limited, Jinan |
| MAC | `9C:A5:25:CF:64:45` (OUI belongs to Anycubic) |
| Role | Transparent TCP ⇄ UART bridge for the printer mainboard |
| Config UI | `http://<printer-ip>/`, HTTP Basic `admin` / `admin` |
| Search port | UDP `48899` (no reply observed) |
| Protocol port | TCP `6000` |

The mainboard programs the module over AT commands at boot — strings such as
`AT+SOCKA=TCPS,<ip>,6000` and `AT+UART=115200,8,1,NONE,NFC` are in its
firmware. So the module holds no printer logic of its own; it moves bytes.

### Web UI

An iframe shell (`index_en.html`) loading pages per topic, with a CGI command
endpoint at `do_cmd_en.html` taking `__SL_P_*` form fields:

| Page | Purpose |
|---|---|
| `sys_status_en.html` | module uptime, MAC, firmware, mode, SSID/IP/gateway |
| `WiFi_set_en.html` | wireless configuration |
| `Peripherals_uart0_en.html` | UART0 settings, baud, flow control |
| `special_function_en.html` | module search (port `48899`), module ID |
| `web_account_en.html` | credentials |
| `reload_reset_en.html` | module reload/restart |

The UI is entirely about the module. It exposes **no** printer telemetry — no
temperatures, no print progress, no resin data. Everything useful about the
printer itself is only reachable over port 6000.

### Changing the baud rate would break the app

`Peripherals_uart0_en.html` can rewrite the UART settings the mainboard
configured at boot. Doing so would desynchronise the mainboard from the module
and lose the app's connection. Leave it alone.

## Printer

| | |
|---|---|
| Model | Photon Mono X |
| Firmware | `V3.5.4` |
| Serial | `203330345030500E` |

## USB stick

FAT32, label `SNAZZYJOE`. Holds print jobs plus the configuration and firmware
the printer reads directly.

| Contents | Notes |
|---|---|
| `WIFI.txt` | SSID + **plaintext WiFi password**; read at boot. Never commit this. |
| `*.pwmx` | print jobs, ~5–95 MB each |
| `P_MXV5_4_0812(1).bin` | ARM Cortex-M mainboard firmware |
| `P_MXF021.bin`, `P_MXFA036.bin` | unidentified non-ARM blobs |
| `history.bin` | print history |
| `Z2TAOL_P03.zip` | 402 MB **game mod**, not firmware — ignore |

Job extensions seen: `.photon`, `.photons`, `.PHOTON`, `.PHOTONS`. The
`history.bin` reference in the firmware shows the printer maintains its own
print history on the stick.

Keep the stick mounted read-only when poking at it; the printer is happy with
the original files back in place.

## Network

The printer is on `192.168.87.0/24` in `Station` mode, joined to the same SSID
as the workstation. Port 6000 is reachable from the LAN — no firewall in the
way — but the app and this library contend for the same single slot, so pick
one at a time.
