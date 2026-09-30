#!/usr/bin/env python3
"""Reader for Anycubic ``.pwmx`` sliced print files.

Structure recovered by inspection of the jobs on the printer's USB stick
(see docs/PWMX-FORMAT.md). No printer access is required or involved: these
files are plain files on a FAT32 stick, so everything here works offline.

Layout of a version-516 file:

    0x00  magic "ANYCUBIC"
    0x0c  format version (516, or 1 for a legacy variant)
    0x14  offset of the HEADER section
    0x1c  offset of the PREVIEW section
    0x20  section offset table
    0x88  layer count
    0x98  PREVIEW section: tag, dims, then a 2-colour dithered mask
    ...   LAYERDEF section: per-layer record table
    ...   EXTRA, MACHINE sections
    ...   run-length encoded layer bitmaps

Only the header-level metadata and the preview image are decoded here. The
per-layer bitmap codec is not implemented yet; see docs/PWMX-FORMAT.md.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

MAGIC = b"ANYCUBIC"
VERSION_MODERN = 516

OFF_VERSION = 0x0C
OFF_HEADER_SEC = 0x14
OFF_PREVIEW_SEC = 0x1C
OFF_SECTION_TABLE = 0x20
OFF_LAYER_COUNT = 0x88

PREVIEW_TAG = 0x98
LAYERDEF_RECORD_SIZE = 32


class PwmxError(ValueError):
    pass


class PwmxFile:
    """A parsed ``.pwmx`` file. Only the header is read eagerly."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        with self.path.open("rb") as fh:
            self._head = fh.read(0x200)
        if self._head[:8] != MAGIC:
            raise PwmxError(f"{self.path}: not a .pwmx file (magic {self._head[:8]!r})")
        self.version = self._u(OFF_VERSION)
        self.layer_count = self._u(OFF_LAYER_COUNT)
        self.preview_offset = self._u(OFF_PREVIEW_SEC)
        self.header_offset = self._u(OFF_HEADER_SEC)
        self.section_offsets = [self._u(OFF_SECTION_TABLE + 4 * i) for i in range(5)]

    def _u(self, off: int) -> int:
        return struct.unpack_from("<I", self._head, off)[0]

    def _f(self, off: int) -> float:
        return struct.unpack_from("<f", self._head, off)[0]

    @property
    def is_legacy(self) -> bool:
        """Version 1 files use a different header layout entirely."""
        return self.version != VERSION_MODERN

    # -- header metadata ---------------------------------------------------
    @property
    def panel_width(self) -> int | None:
        return None if self.is_legacy else self._u(0x70)

    @property
    def panel_height(self) -> int | None:
        return None if self.is_legacy else self._u(0x74)

    @property
    def layer_height_mm(self) -> float | None:
        """Confirmed 0.05 on every version-516 job inspected."""
        return None if self.is_legacy else round(self._f(0x48), 4)

    @property
    def model_height_mm(self) -> float | None:
        """0x68, e.g. 28.642 - the physical height of the model."""
        return None if self.is_legacy else round(self._f(0x68), 3)

    @property
    def exposure(self) -> dict:
        """Exposure-related floats from HEADER. Names are inferred, not proven."""
        if self.is_legacy:
            return {}
        return {
            "bottom_exposure_s": self._f(0x44),
            "layer_height_mm": round(self._f(0x48), 4),
            "field_0x4c": self._f(0x4C),
            "field_0x50": self._f(0x50),
            "field_0x54": self._f(0x54),
            "field_0x58": self._f(0x58),
            "field_0x5c": self._f(0x5C),
            "field_0x60": self._f(0x60),
            "field_0x64": self._f(0x64),
        }

    @property
    def estimated_height_mm(self) -> float | None:
        if self.layer_height_mm is None:
            return None
        return round(self.layer_count * self.layer_height_mm, 1)

    def machine_name(self) -> str | None:
        """The MACHINE section holds e.g. "Anycubic Photon Mono X"."""
        with self.path.open("rb") as fh:
            blob = fh.read()
        i = blob.find(b"MACHINE")
        if i < 0:
            return None
        # Layout is: tag(8) + eight zero bytes + null-terminated text.
        text = blob[i + 16:].split(b"\x00", 1)[0]
        try:
            return text.decode("ascii")
        except UnicodeDecodeError:
            return None

    # -- preview -----------------------------------------------------------
    #: The preview is a 1-bit mask stored as an RGB image in which "empty"
    #: pixels alternate between these two colours. Anything else is content.
    DITHER = ((0x40, 0x62, 0x40), (0x62, 0x40, 0x62))

    def _decode_mask(self, data: bytes, width: int, height: int) -> bytearray:
        mask = bytearray(width * height)
        for i in range(width * height):
            r, g, b = data[3 * i], data[3 * i + 1], data[3 * i + 2]
            mask[i] = 0 if (r, g, b) in self.DITHER else 1
        return mask

    def preview_raw(self):
        """Decode the PREVIEW section to ``(width, height, mask)``.

        ``mask`` is one byte per pixel, 1 = part of the model. Dimensions come
        from the section header; the image is 224 px wide on every version-516
        job inspected, and the meaningful rows are a subset of the declared
        height (the rest is dithered filler).
        """
        if self.is_legacy:
            raise PwmxError("preview layout unknown for legacy (version 1) files")
        with self.path.open("rb") as fh:
            fh.seek(self.preview_offset)
            hdr = fh.read(0x1C)
            if hdr[:7] != b"PREVIEW":
                raise PwmxError(f"no PREVIEW section at 0x{self.preview_offset:x}")
            _reserved, _end, width, height = struct.unpack_from("<IIII", hdr, 8)
            fh.seek(self.preview_offset + 0x1C)
            data = fh.read(width * height * 3)
        if len(data) < width * height * 3:
            raise PwmxError("preview data truncated")
        return width, height, self._decode_mask(data, width, height)

    def preview(self, crop: bool = True):
        """Decode the preview to ``(width, height, rgb)``.

        With ``crop`` (the default) the uniform dithered filler is trimmed away,
        which is what you want for a thumbnail. The result is a greyscale image
        with white where the model is and black elsewhere.
        """
        width, height, mask = self.preview_raw()
        x0, y0, x1, y1 = 0, 0, width, height
        if crop:
            rows = [y for y in range(height) if any(mask[y * width:(y + 1) * width])]
            if not rows:
                raise PwmxError("preview contains no content")
            y0, y1 = rows[0], rows[-1] + 1
            cols = [x for x in range(width)
                    if any(mask[y * width + x] for y in range(y0, y1))]
            if cols:
                x0, x1 = cols[0], cols[-1] + 1
        w, h = x1 - x0, y1 - y0
        rgb = bytearray(w * h * 3)
        for y in range(h):
            for x in range(w):
                v = 0xFF if mask[(y0 + y) * width + (x0 + x)] else 0x00
                o = (y * w + x) * 3
                rgb[o] = rgb[o + 1] = rgb[o + 2] = v
        return w, h, bytes(rgb)

    def preview_png(self, crop: bool = True) -> bytes:
        w, h, rgb = self.preview(crop=crop)
        return _png(w, h, rgb)


def _png(width: int, height: int, rgb: bytes) -> bytes:
    """Minimal PNG writer, so this needs no image library."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + rgb[y * width * 3:(y + 1) * width * 3]
                   for y in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        p = PwmxFile(arg)
        print(f"{p.path.name}: version={p.version} layers={p.layer_count} "
              f"panel={p.panel_width}x{p.panel_height} "
              f"layer_h={p.layer_height_mm}mm "
              f"height={p.estimated_height_mm}mm machine={p.machine_name()!r}")
