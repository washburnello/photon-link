# Protocol reference

Everything here was recovered from the printer's own mainboard firmware and
confirmed by talking to a real unit. Unknowns are marked **unconfirmed**.

## Transport

| | |
|---|---|
| Protocol | Plain ASCII over TCP |
| Default port | `6000` |
| Framing | **None.** No length prefix, no magic bytes, no checksum |
| Field separator | `,` |
| Response terminator | `,end` (some replies also contain `\r\n`) |
| Transport path | iOS app → WiFi (LAN) → `USR-C322` module → UART → mainboard |

The WiFi module is a *transparent* serial-to-Ethernet bridge. Port 6000 delivers
bytes to the mainboard's serial port unchanged, so the language below is the
mainboard's own, not a gateway's translation of it.

### The one-connection rule (important)

The `USR-C322` TCP server accepts **exactly one client at a time** and has a
near-zero accept backlog. Consequences, all observed in practice:

* While any client holds the connection, nothing else can connect — including
  the vendor app. This is why the app appeared to "refuse to connect".
* A connection that is opened and abandoned without being closed wedges port
  6000 entirely. New connections then hang until the stale socket is closed.
* Always close your socket. Reuse one connection for a batch of commands
  rather than reconnecting per command.

`photonlink.client.AnycubicPrinter` enforces this by being a context manager
that always closes.

## Response shapes

Replies are not uniformly terminated. Observed forms:

```
getstatus,stop
,end
```

```
sysinfo,Photon Mono X,V3.5.4,203330345030500E,washburn home,end
```

Commands can produce **multiple** replies coalesced into a single read, and the
printer also emits **unsolicited** lines — most often `getmode,0,end` — at
apparently arbitrary moments. Clients must tolerate extra data in a read
rather than assuming one reply per command.

## Command table

Format strings are quoted exactly as they appear in the firmware's string
table, so the field *types* are known even where the field *names* are not.

### Verified on hardware

| Command | Response | Notes |
|---|---|---|
| `getstatus` | `getstatus,stop` + `,end` when idle | Full 12-field form while printing — see below |
| `sysinfo` | `sysinfo,%s,%s,%s,%s` | model, firmware, serial, SSID |
| `getmode` | `getmode,%d` | integer operating mode |
| `getwifi` | `getwifi,%s` | joined SSID |

### Known from firmware, not yet exercised

| Command | Response | Notes |
|---|---|---|
| `getpara` | `getpara,%s,%s,%s,%s,%s,%s,%s,%s` | 8 string args. Answers `getpara,ERROR1` with no args — **argument list still unknown** |
| `setpara` | `setpara,OK` / `setpara,ERROR1` | state-changing |
| `gopause` | `gopause,OK` / `gopause,ERROR1` | state-changing |
| `goresume` | `goresume,OK` / `goresume,ERROR1` | state-changing |
| `gostop` | `gostop,OK` / `gostop,ERROR1` | state-changing |
| `goprint` | `goprint,OK` / `goprint,ERROR1..4` | start a print; **arguments unknown**, 4 distinct error paths |
| `gethistory` | `gethistory,ERROR2` observed | answers an error even on a healthy unit |
| `delhistory` | `delhistory,%d,OK,end` / `ERROR2`, `ERROR3` | **deletes data** |
| `delfile` | `delfile,%s,OK,end` / `ERROR2`, `ERROR3` | **deletes a file** |
| `setZhome` | `setZhome,OK` / `ERROR1`, `ERROR2` | motion |
| `setZmove` | `setZmove,OK` / `setZmove,ERROR1` | motion |
| `setZstop` | `setZstop,OK` / `setZstop,ERROR1` | motion |
| `setZero` | `setZero,OK` / `setZero,ERROR1` | homing |
| `detect` | `detect,OK` / `detect,ERROR1` | likely auto-level / probe |
| `stopUV` | `stopUV,OK` / `stopUV,ERROR1` | kills UV exposure |
| `getmode` | `getmode,%d` | also emitted unsolicitedly |
| `setwifi` | `setwifi,OK` / `setwifi,ERROR1` | reconfigure networking |
| `getFirmware` | `ERROR2,end` observed | answers an error even on a healthy unit |
| `getfile` | `getfile,ERROR1` observed | pull a file **off** the printer; argument format unknown |
| `getPreview1` | `getPreview1,%s,%lu,%lu,%lu` | preview metadata: name + 3 unsigned longs (unconfirmed) |
| `getPreview2` | `getPreview2,ERROR3,end` seen in firmware | second preview variant, probably image data |

### Other firmware strings of interest

States and UI text observed in the string table: `pause`, `print`, `end`,
`Print finished`, `Resume last printing?`, `Stop Printing?`,
`Door opened, Pause to printing!`, `Door closed, Resume to printing!`,
`ExposureOff`, `Exposuring`, `Updating firmware...`, `Update firmware?`.

File extensions: `.photon`, `.photons`, `.PHOTON`, `.PHOTONS`, plus
`history.bin` — so jobs are sliced files on the USB stick.

Two `getstatus` variants carry extra trailing data rather than the bare state:

```
getstatus,stop
getstatus,finish,%s
getstatus,stop,end
getstatus,print,end
```

## Files: the protocol is read-only

The complete verb set recovered from the firmware is 25 commands — listed
across the tables above. **None of them sends a file to the printer.** There is
no `sendfile`, `upload`, `putfile`, `write` or equivalent; this was checked both
by enumerating every token in the command string pool and by searching the
whole image for upload-style verbs. Both came back empty.

What exists instead:

| Direction | Command | |
|---|---|---|
| printer → client | `getfile` | pull a file off the USB stick |
| client → printer | *(none)* | **no upload path exists** |
| client → printer | `delfile,%s` | delete a file |
| client → printer | `delhistory,%d` | delete print history |

So the protocol can *read* files and *delete* them, but not create them.

This is consistent with how firmware updates work: the `.bin` images already
sit on the USB stick, and the mainboard flashes them from there after the user
confirms "Update firmware?". Nothing needs to be transferred over the network,
so no upload command was ever written.

**To get a file onto the stick, copy it with a filesystem.** The stick is plain
FAT32, so plug it into any machine and copy the file on; the printer re-scans it
(the "refresh file list" action on the printer). No protocol involvement, and no
reason to want one.

### File addressing

A `%s/%s,` format string in the firmware suggests the printer addresses files
as a directory plus a name, even though files appear flat on the stick. The
internal directory layout is unknown.

`getfile` answers `getfile,ERROR1` both with no argument and with a
non-existent filename, so it is not yet known whether that is a malformed-argument
error or a missing-file error — the argument format remains the open question
here.

### Recognised file extensions

`.photon`, `.photons`, `.PHOTON`, `.PHOTONS`, `.pws`, `.PWS`

Print jobs are sliced `.pwmx` files on the stick, which is a different
extension from the ones the protocol's preview commands appear to expect.
`getPreview1`'s reply shape (`%s,%lu,%lu,%lu`) suggests it returns a name plus
three dimensions, and `getPreview2` plausibly returns image data — which would
make on-printer thumbnails obtainable. Unconfirmed.

## `getstatus` fields (in progress)


The firmware's format string is:

```
getstatus,%s,%s,%lu,%d,%lu,%lu,%lu,%s,%s,%s,%s,%u
```

So a printing unit answers with a verb plus **12** values whose C types are
`str, str, ulong, int, ulong, ulong, ulong, str, str, str, str, uint`. The
*names* are not yet mapped.

These are believed to be layer/print state, filename, and timing/progress
values, but **that is inference, not measurement.** To finish the mapping,
start a print and poll `getstatus` while it runs, then correlate the fields
against the printer's own on-screen display:

```bash
photonlink watch --seconds 300
```

## Firmware-version dependence

The observations above are from firmware **V3.5.4** (serial
`203330345030500E`). The string table examined is
`P_MXV5_4_0812(1).bin` from the USB stick. Field layouts may differ on other
firmware versions, so treat the tables as version-scoped and re-check
`sysinfo` before trusting them.
