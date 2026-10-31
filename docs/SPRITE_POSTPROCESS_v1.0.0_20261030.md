# Spritesheet alignment and onion skinning

Version 1.0.0 · 2026-10-30 · Source: the Cerbero spritesheet review following PR #93 and the request for a reusable post-processing script. New standalone tooling; no game runtime or approved reference is changed. Follows the global registration rules in [sprite protocol v12 §4.1](PROTOCOLLO_SPRITE_ANIMATI_v12.0.0_20261030.md).

The CLI is [`scripts/sprite_postprocess.py`](../scripts/sprite_postprocess.py). It requires Python 3.10+ and Pillow (tested against the repository pin, Pillow 11.3.0). No ImageMagick, NumPy, SciPy, network or image generation service is needed.

```bash
python3 -m pip install -r requirements-test.txt
python3 scripts/sprite_postprocess.py path/to/sheet.png \
  --columns 4 --rows 2 --out artifacts/sprites/run-001
```

This first pass extracts poses and prepares inspection files. Without an alignment input it explicitly reports **layout only**, not anatomical alignment. The original PNG stays unchanged. Output directories must be new or empty; use a new revision directory for each run.

## Extraction

Default `--mode components` detects separate alpha-connected poses even when they cross nominal grid lines. Poses are sorted into `--rows` rows by vertical center, then left to right within each row. Check `raw-contact.png` and `extracted/` to confirm the intended sequence.

`--min-area 128` selects the minimum area for a principal pose, not a deletion threshold. Smaller detached islands are assigned to the nearest principal pose; faint pixels are retained too. `--alpha-threshold 2` affects detection only, preventing almost invisible alpha bridges from joining two poses. RGBA source pixels are retained without changing their color or alpha. Nearest-pose assignment is a heuristic: inspect detached claws, horns, effects, or overlapping bounding boxes. A transparent gap does not necessarily separate two characters, and disconnected anatomy is not necessarily a new pose.

If the number of principal components differs from rows × columns, the tool stops instead of silently keeping the largest few. Adjust the detection threshold/minimum area or separate touching poses in an editor. `--mode grid` performs literal cell crops for regular sheets, distributing remainder pixels across cells. Grid mode cannot repair poses crossing cell boundaries. Painted checkerboards and opaque backgrounds must be removed before processing.

## Automatic first-pass body matching

Inspect `reference-guide.png`. Choose a rectangle containing relatively stable **torso texture**, excluding moving legs, tail, wings and heads. The guide has a 50-pixel coordinate grid. Coordinates refer to the staged guide, not the source sheet or the labeled contact sheet.

```bash
python3 scripts/sprite_postprocess.py path/to/sheet.png \
  --columns 4 --rows 2 --body-roi 220 245 85 65 --search 48 \
  --out artifacts/sprites/run-002
```

The ROI numbers above are an example from the generated second Cerbero sheet; choose the region for each asset. Keep extraction settings and padding identical to the guide-producing run. `--reference 1` selects the 1-based reference pose. Coarse-to-fine matching estimates a single integer translation per frame against that reference, with rotation and scale locked. The manifest records the photometric score and whether a search boundary was reached. Boundary hits, wrong matches, or changing torso anatomy require reviewing the region/search or using landmarks. The photometric score is not an anatomical error measurement.

Automatic matching is provisional. It can remove intentional body rise/fall or forward movement. It does not repair limb anatomy, estimate body size from silhouette width, or certify the gallop. Use landmarks with explicit motion offsets when intentional movement must be retained.

## Precise body landmark alignment

Copy `landmarks-template.json` outside the run directory, fill its `points` for every frame, and run:

```bash
python3 scripts/sprite_postprocess.py path/to/sheet.png \
  --columns 4 --rows 2 --landmarks path/to/landmarks.json \
  --out artifacts/sprites/run-003
```

Points use **original source-sheet pixel coordinates**, with origin at the upper left. `source_box` uses exclusive right/bottom bounds and is provided for each extracted pose. For crop-local coordinates, add the first two values of `source_box`. The template includes the sheet hash; stale hashes/crop boxes are rejected. Record stable body points with the same anatomical names in every pose. Omit occluded/unreliable points instead of inventing them.

Example frame entry (illustrative coordinates, not annotations for Cerbero):

```json
{
  "source_box": [0, 0, 200, 160],
  "points": {
    "shoulder": {"xy": [120, 65], "weight": 1.0},
    "sternum": {"xy": [115, 95], "weight": 0.8},
    "pelvis": {"xy": [65, 80], "weight": 1.0}
  },
  "motion": [0, -4],
  "anchors": {"mouth_left": [165, 40], "pivot": [90, 80]}
}
```

Weights express relative annotation confidence; record uncertainty and anatomical definitions in your asset report. Simple `[x,y]` points default to weight 1. Reference/frame confidence is combined using the smaller weight. The script fits all frames independently against the canonical reference frame, avoiding accumulated drift. Default fitting is translation only. Add `--allow-scale` only when annotated stable body measurements justify correcting size drift: it fits **one uniform whole-frame scale**, with rotation locked at zero. No per-axis scaling, separate limb adjustment, warp or morphing is available.

`motion` preserves intentional destination-pixel displacement relative to the reference body position. Use a nonzero vertical offset for an intended airborne rise, for example. Optional `anchors` (including a pivot) are transformed by exactly the same matrix and exported in the manifest.

At least three reliable, noncollinear body points are needed for a non-provisional landmark report. Fewer points can initialize a translation, but the report marks it provisional. Residual RMS and maximum errors are measured in output pixels; choose acceptance tolerances for the asset, annotation uncertainty and actual display scale. Low residuals do not certify anatomy, proportions or topology.

## Outputs and review

| Output | Purpose |
| --- | --- |
| `extracted/NNN.png` | Source pixels for each detected/cropped pose |
| `aligned/NNN.png` | Common canvas with global transforms applied |
| `atlas.png` | Transparent aligned sheet in the declared column order |
| `raw-contact.png`, `aligned-contact.png` | Numbered before/after contact sheets |
| `reference-guide.png` | Staged reference with coordinates for selecting a body ROI |
| `onion/NNN.png`, `onion-contact.png` | Current frame plus previous in red and next in cyan |
| `raw.gif`, `aligned.gif`, `onion.gif` | Local diagnostic animations with a shared palette |
| `landmarks-template.json` | Empty, source-linked annotation template |
| `manifest.json` | Source/script/output hashes, settings, matrices, residuals, anchors and actual GIF timings |

Onion neighbors wrap at the last→first seam; the tool assumes a loop. `--onion-opacity 0.3` controls ghost opacity. `--duration 100` gives each pose 100 ms; GIF delays must be positive multiples of 10 ms. Identical GIF frames may be encoded as longer holds; actual encoded frame count/delays are recorded. No motion interpolation is performed. GIF previews use a dark background and 256-color shared palette to avoid palette flicker; aligned PNGs/atlas retain RGBA.

The common canvas automatically includes the union of transformed poses and `--padding 16`. `--canvas WIDTH HEIGHT` selects a fixed export size and fails if it would clip the computed bounds. Integer translations copy pixels losslessly. Fractional translation/uniform scale resample once from the extracted original using bicubic filtering; use `--nearest` for pixel art. Compare fine detail and alpha edges after any resampling.

Review the raw and aligned loops, temporal onion skins (especially the loop seam), anatomy and intended body trajectory. Compare to approved A/B references separately. These PNG-derived GIFs are post-processing diagnostics, not browser recordings or evidence of game integration. Approval of a generated reference does not approve its cycle; aligned outputs remain candidates until visual review.

## Verification

```bash
python3 -m unittest discover -s tests -p 'test_sprite_postprocess.py' -v
```

Tests exercise crossed grid boundaries, faint-pixel conservation, touching-pose rejection, uneven grid partitioning, body-region matching with a moving tail, weighted registration, intentional motion, anchors, clipping guards, transparent PNGs, shared-palette GIF timing, and output/source protection. A dedicated CI workflow runs these checks alongside the unchanged full game CI. Temporary previews belong in ignored `artifacts/`; version only approved asset outputs and essential review evidence.
