# How the protocol was recovered

Written up so the next person does not repeat the dead ends. Short version:
**read the printer's own firmware off its USB stick, then `strings` it.** The
protocol turned out to be plain ASCII, so no disassembly was needed.

## 1. Network recon

Full TCP scan of the printer (`192.168.87.251`) found exactly two open ports:

| Port | Service |
|---|---|
| 80 | `USR-C322` WiFi module config UI (HTTP Basic, `admin:admin`) |
| 6000 | the protocol port |

The web UI is **not** the printer's — it is the config page of a USR IOT
`USR-C322` serial-to-WiFi module, module firmware `2.18.06`, MAC
`9C:A5:25:CF:64:45`, in `Station` mode. Its status page reports only the
module's own state, not the printer's. Useful fields are reachable through CGI
forms (`__SL_P_*` names, submitted to `do_cmd_en.html`).

A UDP discovery probe on the module's search port `48899` produced no reply,
so the vendor app most likely reaches the printer by direct IP.

## 2. Probing port 6000 (this is where effort was wasted)

The first assumption — that port 6000 spoke a checksummed binary protocol —
was wrong, and it cost time. Sending a dozen plausible binary headers
(`5a a5 …`, `aa 55 …`, MZ, 0x7e padding …) produced **no reply at all**. Every
frame was silently discarded, which reads exactly like "unknown binary
protocol, keep fuzzing". It was not.

### The single-connection trap

Several abandoned probe connections wedged port 6000 completely: new connects
simply hung for minutes, and the web UI still answered normally, so it did not
look like a printer fault. It cleared the instant the stale connections were
closed. **If port 6000 becomes unreachable, suspect your own leftover socket
before suspecting the printer.** `ss -tnp | grep 192.168.87.251:6000` is the
first thing to run.

## 3. The USB stick (the actual breakthrough)

The printer reads `WIFI.txt` from a FAT32 stick at boot to join WiFi, and the
same stick carries firmware images. That made the printer's own code available
offline — no MITM, no traffic capture, no ARP spoofing.

The stick also holds a 402 MB `Z2TAOL_P03.zip`. That is **not** a BIOS package:
it is a game mod (4.3 M entries, `D3DX9_43.dll`, `gmsched.dll`, tile JSON). It
contains no firmware and is a red herring.

`tools/extract_firmware.sh` copies out the real image. The significant files:

| File | What it is |
|---|---|
| `P_MXV5_4_0812(1).bin` | **ARM Cortex-M mainboard firmware** — the one that matters |
| `P_MXF021.bin`, `P_MXFA036.bin` | not ARM; unidentified, `file` says plain `data` |
| `history.bin` | 12876 bytes, starts with a single `0x64` then zeroes — print history |
| `WIFI.txt` | SSID + **plaintext WiFi password**; do not commit it |

`file` identifies the mainboard image and its vector table:

```
ARM Cortex-M firmware, initial SP at 0x2001cf70, reset at 0x080084bc, ...
```

so: flash based at `0x08000000`, ~115 KB of RAM, Thumb code, 303 492 bytes
total, and the file offset equals the address minus `0x08000000`.

## 4. `strings` gave up the protocol

```bash
strings -t x -n 4 mainboard.bin > so.txt
```

Most short matches are ARM instruction noise, but a **contiguous string pool**
sits at `0x8600`–`0x9c00` and is unmistakably the command layer:

```
0x08b2b  getpara
0x08b3b  getpara,%s,%s,%s,%s,%s,%s,%s,%s
0x08b90  gopause
0x08c14  getstatus
0x0903b  getstatus,%s,%s,%lu,%d,%lu,%lu,%lu,%s,%s,%s,%s,%u
0x095bc  sysinfo
0x095cf  sysinfo,%s,%s,%s,%s
0x09674  ,end
```

The comma-separated `%s`/`%lu` format strings are `sprintf` templates, so the
field *types* and the command/response pairing are both known directly.

Two strings also explain the whole network architecture:

```
AT+SOCKA=TCPS,192.168.3.56,6000
AT+UART=115200,8,1,NONE,NFC
```

The mainboard programs the WiFi module over AT commands: open a TCP **server**
on port 6000, and run the UART at 115200 8N1 (a 460800 variant also exists).
That is why port 6000 is a transparent bridge rather than a gateway.

## 5. Confirming on the wire

The payoff for reading the string table first: one test told us the framing.

```
$ printf 'getstatus' | nc 192.168.87.251 6000
getstatus,stop
,end
```

No prefix, no terminator required on send, no checksum. The binary probes had
failed simply because the protocol is text.

Verified live:

```
getstatus -> getstatus,stop\n,end
sysinfo   -> sysinfo,Photon Mono X,V3.5.4,203330345030500E,washburn home,end
getmode   -> getmode,0,end
getwifi   -> getwifi,washburn home,end
getpara   -> getpara,ERROR1,end          (needs arguments)
gethistory-> gethistory,ERROR2,end
getFirmware -> ERROR2,end
```

## What did not work, and why it is worth recording

**Static cross-referencing the status function.** The intent was to name the 12
`getstatus` fields straight from the code that builds the reply. Two dead
ends:

* No 32-bit literal in the file points into the string pool, so the usual
  `ldr rX, =0x0800903b` / literal-pool pattern is not how these strings are
  reached.
* No `movw`/`movt` pair builds a string address either. A linear Thumb sweep
  (with `skipdata` enabled — without it capstone silently stops at the first
  undecodable byte and reports nothing) finds 613 `movw` and **zero** `movt`,
  which is not a coherent Thumb-2 pattern.

Likely the string table is reached through some indirection (offset-from-base,
or a table) that a targeted analysis would find. This is untrialled, not
ruled out. Meanwhile the measurement approach — poll during a real print and
correlate against the printer's own screen — is cheaper and definitive, so
that is what `photonlink watch` is for.

`fw/xref.py` is left in the tree as the starting point for that work.

## Reproducing

```bash
./tools/extract_firmware.sh              # pull firmware off the USB stick
python3 -m pip install -e ".[analysis]"  # capstone, for the xref tool
strings -t x -n 4 fw/mainboard.bin | less
```

## Not attempted

No state-changing command was ever sent: no `goprint`, `setZmove`, `setZhome`,
`setZero`, `detect`, `stopUV`, `setpara`, `setwifi`, `delfile` or `delhistory`.
The printer was read from only. `photonlink raw` refuses those verbs unless
given `--yes`.
