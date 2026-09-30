"""Tests for the .pwmx reader.

These run against small synthetic files rather than real jobs, so they run
anywhere. The expected values are taken from the observed layout of real
version-516 files; see docs/PWMX-FORMAT.md.
"""
import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from pwmx import MAGIC, VERSION_MODERN, PwmxError, PwmxFile, _png  # noqa: E402

DITHER_A = (0x40, 0x62, 0x40)
DITHER_B = (0x62, 0x40, 0x62)


def build(tmp_path, *, version=VERSION_MODERN, layers=1691,
          panel=(3840, 2400), layer_height=0.05, preview=True,
          width=8, height=6, name="job.pwmx"):
    """Write a minimal file with the observed header layout."""
    head = bytearray(0x200)
    head[0:8] = MAGIC + b"\x00\x00"
    struct.pack_into("<I", head, 0x0C, version)
    struct.pack_into("<I", head, 0x14, 0x34)      # HEADER
    struct.pack_into("<I", head, 0x1C, 0x98)      # PREVIEW
    struct.pack_into("<f", head, 0x48, layer_height)
    struct.pack_into("<f", head, 0x68, 28.642)
    struct.pack_into("<I", head, 0x70, panel[0])
    struct.pack_into("<I", head, 0x74, panel[1])
    struct.pack_into("<I", head, 0x88, layers)
    if preview:
        head[0x98:0x9F] = b"PREVIEW"
        struct.pack_into("<IIII", head, 0x98 + 8, 0, 0, width, height)

    body = bytearray()
    if preview:
        # Preview pixels live inside the head, at PREVIEW + 0x1c.
        px_off = 0x98 + 0x1C
        # Row 0 and row 1 empty (dither), row 2 a lit block, then empty again,
        # so auto-crop has something real to find.
        rows = [[DITHER_A, DITHER_B, DITHER_A, DITHER_B, DITHER_A, DITHER_B,
                 DITHER_A, DITHER_B],
                [DITHER_B, DITHER_A, DITHER_B, DITHER_A, DITHER_B, DITHER_A,
                 DITHER_B, DITHER_A],
                [(0xFF, 0xFF, 0xFF), DITHER_A, (0xFF, 0xFF, 0xFF), DITHER_B,
                 (0xFF, 0xFF, 0xFF), DITHER_A, (0xFF, 0xFF, 0xFF), DITHER_B],
                [DITHER_A, DITHER_B, DITHER_A, DITHER_B, DITHER_A, DITHER_B,
                 DITHER_A, DITHER_B],
                [DITHER_B, DITHER_A, DITHER_B, DITHER_A, DITHER_B, DITHER_A,
                 DITHER_B, DITHER_A],
                [DITHER_A, DITHER_B, DITHER_A, DITHER_B, DITHER_A, DITHER_B,
                 DITHER_A, DITHER_B]]
        for y, row in enumerate(rows):
            o = px_off + y * width * 3
            for x, px in enumerate(row):
                head[o + 3 * x:o + 3 * x + 3] = bytes(px)
    body += b"EXTRA\x00" + b"\x00" * 8
    body += b"MACHINE\x00" + b"\x00" * 8 + b"Anycubic Photon Mono X\x00"

    path = tmp_path / name
    path.write_bytes(bytes(head) + bytes(body))
    return path


def test_reads_header_metadata(tmp_path):
    f = PwmxFile(build(tmp_path))
    assert f.version == VERSION_MODERN
    assert f.layer_count == 1691
    assert f.layer_height_mm == 0.05
    assert (f.panel_width, f.panel_height) == (3840, 2400)
    assert not f.is_legacy


def test_estimated_height_uses_layer_count(tmp_path):
    f = PwmxFile(build(tmp_path, layers=1691))
    assert f.estimated_height_mm == 84.6


def test_machine_name(tmp_path):
    f = PwmxFile(build(tmp_path))
    assert f.machine_name() == "Anycubic Photon Mono X"


def test_legacy_version_is_detected(tmp_path):
    f = PwmxFile(build(tmp_path, version=1, layers=0, preview=False))
    assert f.is_legacy
    assert f.layer_height_mm is None
    with pytest.raises(PwmxError, match="legacy"):
        f.preview()


def test_rejects_non_pwmx(tmp_path):
    p = tmp_path / "nope.bin"
    p.write_bytes(b"NOTANYCU" + b"\x00" * 64)
    with pytest.raises(PwmxError, match="not a .pwmx"):
        PwmxFile(p)


def test_dither_is_treated_as_empty_not_by_parity(tmp_path):
    """Regression: a low-bit test maps both dither colours to empty and leaves
    stray noise, which looked plausible but was wrong."""
    f = PwmxFile(build(tmp_path))
    w, h, mask = f.preview_raw()
    assert (w, h) == (8, 6)
    assert all(v == 0 for v in mask[0:8]), "dither row must decode as empty"
    assert mask[2 * 8 + 0] == 1, "lit pixel must decode as content"
    assert mask[2 * 8 + 1] == 0, "dither pixel must decode as empty"


def test_preview_autocrops_to_content(tmp_path):
    f = PwmxFile(build(tmp_path))
    w, h, rgb = f.preview()
    assert h == 1, "only the single lit row should survive cropping"
    assert w == 7, "crop should span lit columns 0..6 only"
    assert rgb[:3] == b"\xff\xff\xff"
    assert rgb[-3:] == b"\xff\xff\xff"


def test_preview_without_crop_keeps_full_frame(tmp_path):
    f = PwmxFile(build(tmp_path))
    w, h, _ = f.preview(crop=False)
    assert (w, h) == (8, 6)


def test_preview_raises_when_entirely_empty(tmp_path):
    path = build(tmp_path)
    # Blank the lit row so nothing survives the dither-only test.
    data = bytearray(path.read_bytes())
    off = 0x98 + 0x1C + 2 * 8 * 3
    for i in range(8):
        data[off + 3 * i:off + 3 * i + 3] = bytes(DITHER_A)
    path.write_bytes(bytes(data))
    with pytest.raises(PwmxError, match="no content"):
        PwmxFile(path).preview()


def test_png_writer_produces_a_valid_png(tmp_path):
    png = _png(2, 2, b"\xff\x00\x00" * 4)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert b"IHDR" in png and b"IDAT" in png and b"IEND" in png
    # IHDR carries width=2 height=2 bitdepth=8 colortype=2
    assert struct.unpack_from(">II", png, 16) == (2, 2)
    # zlib stream must decompress to 2 rows of (filter byte + 6 bytes)
    start = png.index(b"IDAT") + 4
    length = struct.unpack_from(">I", png, start - 8)[0]
    assert len(zlib.decompress(png[start:start + length])) == 2 * (1 + 2 * 3)
