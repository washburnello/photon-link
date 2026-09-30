# Firmware analysis

The `.bin` images here are **not committed** — they are Anycubic's copyrighted
firmware. Get your own copy off the printer's USB stick:

```bash
../tools/extract_firmware.sh
```

That writes `mainboard.bin` (the ARM Cortex-M mainboard image, ~296 KB), which
is what all the analysis was done against.

## Scripted checks

```bash
file mainboard.bin       # ARM Cortex-M firmware, reset at 0x080084bc
strings -n 4 mainboard.bin | less
```

The interesting strings sit in a contiguous pool at offsets `0x8600`-`0x9c00`;
everything outside it is mostly ARM instruction noise. The file offset equals
`address - 0x08000000`.

`xref.py` tries to locate the code that formats a `getstatus` reply. It is a
starting point rather than a working tool — see the "What did not work"
section of [../docs/REVERSE-ENGINEERING.md](../docs/REVERSE-ENGINEERING.md)
for why the straightforward approaches came up empty.

```bash
python xref.py mainboard.bin 0x903b
```

## Caution

`WIFI.txt` on the same USB stick contains the printer's WiFi password in
plaintext. It must never be committed.
