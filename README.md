# photon-link

Talk to an **Anycubic Photon Mono X** over the network — no vendor app, no
cloud account, no MITM.

The printer's WiFi module is a transparent serial-to-Ethernet bridge, so its
mainboard speaks a plain ASCII command language straight to TCP port 6000.
This project documents that language and wraps it in a small client.

```python
>>> from photonlink import AnycubicPrinter
>>> with AnycubicPrinter("192.168.87.251") as p:
...     p.sysinfo()
{'model': 'Photon Mono X', 'firmware': 'V3.5.4',
 'serial': '203330345030500E', 'ssid': 'washburn home'}
```

```console
$ photonlink info
$ photonlink status
$ photonlink watch --seconds 300
```

## Status

Alpha. Read-only monitoring works today. The `getstatus` payload during a print
is decoded but not yet fully labelled (see below). Nothing that moves the
printer, starts a print, or deletes a file has been sent.

The protocol was recovered by static analysis of the printer's own mainboard
firmware — see [docs/REVERSE-ENGINEERING.md](docs/REVERSE-ENGINEERING.md) for
the full story, including the dead ends.

## Install

```bash
git clone https://github.com/washburnello/photon-link
cd photon-link
python3 -m pip install -e .
```

Python 3.10+, no runtime dependencies.

## Usage

### Read-only commands

| Command | What it returns |
|---|---|
| `photonlink info` | model, firmware version, serial, SSID |
| `photonlink status` | current print state |
| `photonlink wifi` | joined SSID |
| `photonlink watch` | poll `getstatus`, printing each change once |

Point it at your printer with `--host`:

```bash
photonlink --host 192.168.87.251 info
```

### Raw commands

```bash
photonlink raw getmode
```

`raw` refuses verbs that change printer state unless you pass `--yes`. Read
[docs/PROTOCOL.md](docs/PROTOCOL.md) first — several of them move the Z axis,
kill UV exposure, or delete files.

### As a library

```python
from photonlink import AnycubicPrinter

with AnycubicPrinter("192.168.87.251") as p:   # one connection for the batch
    print(p.sysinfo())
    print(p.status())
    print(p.getmode())
```

## The one rule that bites everyone

**Port 6000 accepts one client at a time.** Hold the connection and the vendor
app cannot connect — that alone makes the app look broken. Open a connection
and abandon it without closing, and port 6000 stops responding to *everything*
until that socket dies, while the printer's web UI keeps working fine and makes
it look like the printer has faulted.

So: always close. `AnycubicPrinter` is a context manager that does it for you.
If port 6000 goes unreachable, check for your own leftover socket first:

```bash
ss -tnp | grep 192.168.87.251:6000
```

## What you can read

- model, firmware version, serial number, joined SSID
- operating mode
- print state, and a 12-field status payload while printing
- files off the USB stick (`getfile`) and preview metadata (`getPreview1`) —
  both still to be worked out

## Files go on and off the stick as a filesystem

The protocol can pull files *off* the printer (`getfile`) and delete them
(`delfile`), but it has **no upload command** — all 25 verbs were enumerated
and none of them sends a file to the printer. That matches how firmware updates
work: the `.bin` images already live on the stick and are flashed from there.

So to add a print job, copy it onto the FAT32 stick with any filesystem and
refresh the printer's file list. No protocol needed, and none exists to use.

## What is not decoded yet

`getstatus` answers `getstatus,%s,%s,%lu,%d,%lu,%lu,%lu,%s,%s,%s,%s,%u` while
printing — 12 values whose types are known but whose meanings are not. To finish
the mapping, start a print and run `photonlink watch`; the fields can be
correlated against the printer's own screen.

`getpara` answers `getpara,ERROR1` without arguments, so its argument list is
still unknown. `gethistory` and `getFirmware` answer errors even on a healthy
unit.

## Documentation

- [docs/PROTOCOL.md](docs/PROTOCOL.md) — the full command reference
- [docs/REVERSE-ENGINEERING.md](docs/REVERSE-ENGINEERING.md) — how it was found
- [docs/HARDWARE.md](docs/HARDWARE.md) — the WiFi module, USB stick, network

## Layout

```
src/photonlink/      client + CLI
docs/                protocol, RE writeup, hardware notes
tools/               firmware extraction, traffic proxy
fw/                  firmware analysis (image itself is not committed)
```

## Scope

Read and control of a printer you own. The vendor firmware image is Anycubic's
copyrighted binary and is deliberately **not** committed — `tools/extract_firmware.sh`
pulls it off your own USB stick.

## Licence

MIT
