# `.pwmx` sliced file format

The print jobs on the printer's USB stick are `.pwmx` files. They are ordinary
files on a FAT32 stick, so everything here works **offline with no printer
access** — which is what makes a monitor practical to build.

Reader: [`tools/pwmx.py`](../tools/pwmx.py). Findings come from inspecting the
16 jobs on one printer's stick, so they are empirical, not from vendor
documentation.

## Container

```
0x00  magic "ANYCUBIC"
0x0c  format version        516 on modern files, 1 on one legacy file
0x14  offset of HEADER
0x1c  offset of PREVIEW
0x20  section offset table   5 x u32
0x34  HEADER   (tag "HEADER" + exposure/layout parameters)
0x98  PREVIEW  (tag "PREVIEW" + 224x120 1-bit thumbnail)
...   LAYERDEF (tag "LAYERDEF" + per-layer record table)
...   EXTRA    (tag "EXTRA" + several float tables)
...   MACHINE  (tag "MACHINE" + machine name string)
...   run-length encoded layer bitmaps
```

### Two format versions

`1xGargoyle_Kid_Guard.pwmx` is **version 1** and uses a different header layout
— its layer count reads as 0 and the parameter offsets hold unrelated values.
The reader detects this via `is_legacy` and refuses rather than returning
nonsense. Nothing else on the stick uses it.

## HEADER parameters (version 516)

Identical across all 15 modern jobs:

| Offset | Type | Value | Reading |
|---|---|---|---|
| `0x44` | f32 | 50.0 | bottom-layer exposure, s |
| `0x48` | f32 | 0.05 | **layer height, mm** |
| `0x4c` | f32 | 2.0 | unlabelled |
| `0x50` | f32 | 0.5 | unlabelled |
| `0x54` | f32 | 28.0 | unlabelled |
| `0x58` | f32 | 4.0 | unlabelled |
| `0x5c` | f32 | 8.0 | unlabelled |
| `0x60` | f32 | 2.0 | unlabelled |
| `0x64` | f32 | 3.0 | unlabelled |
| `0x68` | f32 | 28.642 | model height, mm |
| `0x6c` | u32 | 1 | unlabelled |
| `0x70` | u32 | 3840 | panel width |
| `0x74` | u32 | 2400 | panel height |
| `0x7c` | f32 | 0.63 | unlabelled |
| `0x80` | u32 | 36 | unlabelled |
| `0x88` | u32 | varies | **layer count** |
| `0x8c` | u32 | 10 | unlabelled, constant |

Only `0x48`, `0x68`, `0x70`, `0x74` and `0x88` are confirmed by cross-checking
against physically plausible values. The exposure-related floats are grouped
plausibly — several distinct values, consistent with separate bottom-layer and
normal-layer exposure times — but their individual meanings are **not** proven.

### Confirming the layer count

`0x88` is validated physically. `base_test_10_sec.pwmx` holds 1691 layers at
0.05 mm = **84.6 mm**, a sensible size for a 10-second test print. Across the
stick the value ranges from 1691 to 49325 and correlates with file size, which
is what you would expect if it counts layer bitmaps.

| File | Layers | Height |
|---|---|---|
| base_test_10_sec | 1691 | 84.6 mm |
| wash_platform | 7127 | 356.4 mm |
| b_squad | 12312 | 615.6 mm |
| Trees | 25047 | 1252.4 mm |
| Adult_Green_Dragon | 42273 | 2113.7 mm |
| Plate-01 | 49325 | 2466.2 mm |

This gives a monitor total-layer count and print height with **no printer
communication at all**.

## PREVIEW

`PREVIEW` holds a 1-bit thumbnail, stored as a 224 x 120 RGB image in which
**empty** pixels alternate between two colours:

```
(0x40, 0x62, 0x40)   and   (0x62, 0x40, 0x62)
```

Content pixels are any other colour. This is the trap that makes a naive decode
produce garbage: testing a colour's low bit maps *both* dither colours to
"empty" and looks plausible, while leaving rows of noise at the top and bottom.

The declared height includes dithered filler, so the reader auto-crops to the
content bounding box. Cropped thumbnails come out 224 px wide and 82–98 px tall
depending on the model.

The decode is verified visually: `Adult_Green_Dragon` renders four dragon
silhouettes, `Trees` four trees, `wash_platform` four wash basins — each
matching its filename and the number of parts in the model.

## LAYERDEF (partially decoded)

`LAYERDEF` contains a table of **32-byte per-layer records** starting 60 bytes
after the tag, one per layer. The first fields are four f32s that look like
exposure parameters, with the last confirmed as layer height (0.05):

```
+0   f32  exposure A      (8.0)
+4   f32  exposure B      (2.0)
+8   f32  exposure C      (10.0)
+12  f32  layer height    (0.05)
+16  u32  value A         (increasing, irregular steps)
+20  u32  zero
+24  u32  offset          (cumulative)
+28  u32  length
```

For the first records of `base_test_10_sec` the last two fields satisfy
`offset[n] == offset[n-1] + length[n-1]`, which is the signature of a
contiguous stream of length-prefixed blobs — almost certainly the run-length
encoded layer bitmaps.

**This does not hold for the whole file.** Across 1691 records only ~120
consecutive pairs satisfy it, and the table degenerates into non-ASCII well
before the end. So the 32-byte stride is right near the start and wrong
later — the layout probably varies, or there are sub-records.

### What is not done

The **per-layer bitmap codec is not implemented.** Consequently:

* thumbnails work (PREVIEW is decoded)
* layer count, height and exposure parameters work
* **rendering the individual layer currently being exposed does not** — that
  needs the LAYERDEF codec

This is the main open item for a monitor that shows the current layer the way
the printer's own screen and the vendor app do. The next step is to find where
the 32-byte stride breaks and re-derive the record layout from there; a useful
handle is that real bitmap data is high-entropy, while the filler is the
`0f ff` pattern, so the two are easy to tell apart while stepping through the
file.

## Reproducing

```bash
python3 tools/pwmx.py "/run/media/$USER/<STICK>/"*.pwmx
```

To dump a thumbnail:

```python
from pwmx import PwmxFile
open("thumb.png", "wb").write(PwmxFile("job.pwmx").preview_png())
```
