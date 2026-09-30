#!/usr/bin/env bash
# Pull the printer's mainboard firmware off its own USB stick and report it.
#
# The Photon Mono X reads /WIFI.txt at boot to join WiFi, and the same stick
# carries the mainboard firmware images. This copies the ARM image out so the
# protocol can be studied offline. Nothing is written to the stick.
#
# Usage:  ./tools/extract_firmware.sh [mountpoint]
set -euo pipefail

MOUNT="${1:-/run/media/$USER/SNAZZYJOE}"
OUT="fw"

if [[ ! -d "$MOUNT" ]]; then
    echo "USB stick not found at $MOUNT" >&2
    echo "Pass the mountpoint as an argument, e.g. $0 /run/media/\$USER/LABEL" >&2
    exit 1
fi

mkdir -p "$OUT"

echo "== printer WiFi config =="
if [[ -f "$MOUNT/WIFI.txt" ]]; then
    # Contains the user's network password, so do not echo it.
    echo "$MOUNT/WIFI.txt present ($(wc -c <"$MOUNT/WIFI.txt") bytes, contents withheld)"
fi

echo
echo "== firmware images =="
shopt -s nullglob
found=0
for f in "$MOUNT"/*.bin; do
    base=$(basename "$f")
    # Skip the AppleDouble sidecar files and the print-history blob.
    [[ "$base" == ._* || "$base" == "history.bin" ]] && continue
    kind=$(file -b "$f")
    printf '  %-28s %10s  %s\n' "$base" "$(stat -c %s "$f")" "$kind"
    if [[ "$kind" == *ARM*Cortex-M* ]]; then
        cp "$f" "$OUT/mainboard.bin"
        echo "      -> copied to $OUT/mainboard.bin (ARM Cortex-M mainboard image)"
    fi
    found=1
done
[[ $found -eq 0 ]] && echo "  (no .bin firmware images found)"

echo
echo "== next =="
echo "  strings -n 4 $OUT/mainboard.bin | less"
echo "  see docs/REVERSE-ENGINEERING.md for the full procedure"
