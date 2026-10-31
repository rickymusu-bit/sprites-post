#!/usr/bin/env python3
"""Extract, register and onion-skin spritesheets. Requires only Pillow.

See docs/SPRITE_POSTPROCESS_v1.0.0_20261030.md for the CLI and landmark schema.
See docs/SPRITE_EDITOR_v1.2.0_20261031.md for the local visual editor and edits.
See docs/SPRITE_LOCAL_PATCHES_v1.1.0_20261031.md for external masked corrections.
"""

import argparse
from array import array
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat

VERSION = "1.4.0"


@dataclass
class Sprite:
    image: Image.Image
    box: tuple  # Source sheet coordinates, exclusive right/bottom.


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def alpha_components(image, threshold=0):
    """8-connected visible pixels; retain even faint alpha and tiny islands."""
    width, height = image.size
    alpha = image.getchannel("A").tobytes()
    labels = array("i", [-1]) * (width * height)
    components = []
    for start, value in enumerate(alpha):
        if value <= threshold or labels[start] != -1:
            continue
        label = len(components)
        labels[start] = label
        stack = [start]
        area = 0
        left = right = start % width
        top = bottom = start // width
        while stack:
            index = stack.pop()
            y, x = divmod(index, width)
            area += 1
            left, right = min(left, x), max(right, x)
            top, bottom = min(top, y), max(bottom, y)
            for ny in range(max(0, y - 1), min(height, y + 2)):
                for nx in range(max(0, x - 1), min(width, x + 2)):
                    neighbor = ny * width + nx
                    if alpha[neighbor] > threshold and labels[neighbor] == -1:
                        labels[neighbor] = label
                        stack.append(neighbor)
        components.append({"area": area, "box": (left, top, right + 1, bottom + 1)})
    return labels, components


def box_distance(a, b):
    dx = max(a[0] - b[2], b[0] - a[2], 0)
    dy = max(a[1] - b[3], b[1] - a[3], 0)
    return dx * dx + dy * dy


def extract(image, columns, rows, mode="components", min_area=128, threshold=2):
    width, height = image.size
    if min(columns, rows) < 1 or columns > width or rows > height:
        raise ValueError("Grid dimensions must be positive and fit the source image")
    count = columns * rows
    if mode == "grid":
        boxes = [(c * width // columns, r * height // rows,
                  (c + 1) * width // columns, (r + 1) * height // rows)
                 for r in range(rows) for c in range(columns)]
        sprites = [Sprite(image.crop(box), box) for box in boxes]
        if any(not s.image.getchannel("A").getbbox() for s in sprites):
            raise ValueError("Empty grid cell; check grid dimensions or use components mode")
        return sprites, {"mode": mode, "warnings": [
            "Grid cuts are literal; check the contact sheet for crossed boundaries."]}

    labels, components = alpha_components(image, threshold)
    major = [i for i, component in enumerate(components) if component["area"] >= min_area]
    if len(major) != count:
        raise ValueError(f"Expected {count} separate poses, found {len(major)} components "
                         f"with area >= {min_area}. Adjust --min-area or use --mode grid "
                         "after separating touching poses. No poses were silently dropped.")
    # Form rows by vertical center, then read left to right within each row.
    major.sort(key=lambda i: (sum(components[i]["box"][1::2]), components[i]["box"][0]))
    ordered = []
    for row in range(rows):
        ordered.extend(sorted(major[row * columns:(row + 1) * columns],
                              key=lambda i: components[i]["box"][0]))
    owner = {label: i for i, label in enumerate(ordered)}
    for label, component in enumerate(components):
        if label not in owner:
            owner[label] = min(range(count), key=lambda i: (
                box_distance(component["box"], components[ordered[i]]["box"]),
                sum((sum(component["box"][axis::2]) -
                     sum(components[ordered[i]]["box"][axis::2])) ** 2 for axis in (0, 1))))
    boxes = [list(components[label]["box"]) for label in ordered]
    for label, component in enumerate(components):
        box = boxes[owner[label]]
        other = component["box"]
        box[:] = [min(box[0], other[0]), min(box[1], other[1]),
                  max(box[2], other[2]), max(box[3], other[3])]
    # Detect with a threshold to avoid barely visible bridges joining poses,
    # then retain every faint source pixel by assigning it to a nearby pose.
    assignments = array("i", [-1]) * (width * height)
    alpha = image.getchannel("A").tobytes()
    faint = 0
    for index, label in enumerate(labels):
        if not alpha[index]:
            continue
        y, x = divmod(index, width)
        if label == -1:
            frame = min(range(count), key=lambda i: (
                box_distance((x, y, x + 1, y + 1), components[ordered[i]]["box"]),
                (2 * x - sum(components[ordered[i]]["box"][0::2])) ** 2 +
                (2 * y - sum(components[ordered[i]]["box"][1::2])) ** 2))
            faint += 1
            box = boxes[frame]
            box[:] = [min(box[0], x), min(box[1], y), max(box[2], x + 1), max(box[3], y + 1)]
        else:
            frame = owner[label]
        assignments[index] = frame
    masks = [Image.new("L", (box[2] - box[0], box[3] - box[1])) for box in boxes]
    pixels = [mask.load() for mask in masks]
    for index, frame in enumerate(assignments):
        if frame != -1:
            y, x = divmod(index, width)
            pixels[frame][x - boxes[frame][0], y - boxes[frame][1]] = 255
    sprites = []
    for box, mask in zip(boxes, masks):
        crop = image.crop(box)
        crop.putalpha(ImageChops.multiply(crop.getchannel("A"), mask))
        sprites.append(Sprite(crop, tuple(box)))
    return sprites, {"mode": mode, "min_area": min_area,
                     "detection_alpha_threshold": threshold, "faint_pixels_assigned": faint,
                     "minor_islands_assigned": len(components) - count,
                     "warnings": ["Reading order and nearest-pose assignment of detached "
                                  "islands are estimates; inspect extracted frames."]}


def stage(sprites, padding):
    width = max(s.image.width for s in sprites) + 2 * padding
    height = max(s.image.height for s in sprites) + 2 * padding
    transforms = []
    frames = []
    for sprite in sprites:
        x, y = (width - sprite.image.width) // 2, (height - sprite.image.height) // 2
        frame = Image.new("RGBA", (width, height))
        frame.paste(sprite.image, (x, y))
        frames.append(frame)
        transforms.append((1.0, x, y))
    return frames, transforms


def match_region(reference, target, roi, radius):
    """Translation only, coarse-to-fine photometric search in a stable body ROI."""
    x, y, width, height = roi
    if min(width, height) < 2 or x < 0 or y < 0 or x + width > reference.width or y + height > reference.height:
        raise ValueError("--body-roi must be a nonempty rectangle within reference-guide.png")
    box = (x, y, x + width, y + height)
    reference_alpha = reference.getchannel("A").crop(box)
    if ImageStat.Stat(reference_alpha).sum[0] == 0:
        raise ValueError("The reference body ROI is entirely transparent")

    def flattened(frame):
        background = Image.new("RGBA", frame.size, "#24262b")
        return Image.alpha_composite(background, frame).convert("RGB")

    ref = flattened(reference).crop(box)
    current = flattened(target)

    def score(dx, dy):
        # A destination shift (dx,dy) samples target at reference-(dx,dy).
        target_box = (x - dx, y - dy, x + width - dx, y + height - dy)
        if (target_box[0] < 0 or target_box[1] < 0 or
                target_box[2] > target.width or target_box[3] > target.height):
            return math.inf
        delta = ImageChops.difference(ref, current.crop(target_box))
        return sum(ImageStat.Stat(delta, reference_alpha).mean) / 3

    step = 4 if radius >= 4 else 1
    shifts = sorted(set(range(-radius, radius + 1, step)) | {0, radius})
    candidates = [(score(dx, dy), dx, dy) for dy in shifts for dx in shifts]
    best = min(candidates, key=lambda item: (item[0], item[1] ** 2 + item[2] ** 2, item[1], item[2]))
    _, bx, by = best
    candidates = [(score(dx, dy), dx, dy)
                  for dy in range(max(-radius, by - step), min(radius, by + step) + 1)
                  for dx in range(max(-radius, bx - step), min(radius, bx + step) + 1)]
    best = min(candidates, key=lambda item: (item[0], item[1] ** 2 + item[2] ** 2, item[1], item[2]))
    if not math.isfinite(best[0]):
        raise ValueError("No valid body-ROI samples; enlarge staging padding or reduce search")
    return best[1], best[2], best[0]


def point(value):
    if isinstance(value, dict):
        xy, weight = value["xy"], float(value.get("weight", 1))
    else:
        xy, weight = value, 1.0
    if len(xy) != 2 or not all(math.isfinite(float(v)) for v in xy) or not math.isfinite(weight) or weight <= 0:
        raise ValueError("Landmarks need two finite coordinates and positive weights")
    return (float(xy[0]), float(xy[1])), weight


def fit_landmarks(source, target, weights, allow_scale=False):
    total = sum(weights)
    source_center = [sum(w * p[k] for w, p in zip(weights, source)) / total for k in (0, 1)]
    target_center = [sum(w * p[k] for w, p in zip(weights, target)) / total for k in (0, 1)]
    variance = sum(w * sum((p[k] - source_center[k]) ** 2 for k in (0, 1))
                   for w, p in zip(weights, source))
    scale = 1.0
    if allow_scale:
        if variance <= 1e-12:
            raise ValueError("Uniform scale needs distinct body landmarks")
        scale = sum(w * sum((p[k] - source_center[k]) * (q[k] - target_center[k])
                            for k in (0, 1)) for w, p, q in zip(weights, source, target)) / variance
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("Landmarks imply a nonpositive scale; check names and coordinates")
    dx, dy = [target_center[k] - scale * source_center[k] for k in (0, 1)]
    # Floating-point fitting of exact integer translations must stay lossless.
    scale, dx, dy = [float(round(v)) if abs(v - round(v)) < 1e-10 else v
                     for v in (scale, dx, dy)]
    errors = [math.hypot(scale * p[0] + dx - q[0], scale * p[1] + dy - q[1])
              for p, q in zip(source, target)]
    # Full-rank body points are required for a non-provisional registration claim.
    xx = sum((p[0] - source_center[0]) ** 2 for p in source)
    yy = sum((p[1] - source_center[1]) ** 2 for p in source)
    xy = sum((p[0] - source_center[0]) * (p[1] - source_center[1]) for p in source)
    report = {"landmark_count": len(source), "provisional": len(source) < 3 or xx * yy - xy * xy <= 1e-9,
              "weighted_rms_px": math.sqrt(sum(w * e * e for w, e in zip(weights, errors)) / total),
              "maximum_residual_px": max(errors), "residuals_px": errors}
    return (scale, dx, dy), report


def landmark_transforms(sprites, staged, config, reference, allow_scale):
    entries = config["frames"]
    if len(entries) != len(sprites):
        raise ValueError("Landmark frames must match the extracted frame count in reading order")
    ref = entries[reference]["points"]
    ref_origin = sprites[reference].box[:2]
    _, ref_x, ref_y = staged[reference]
    transforms, reports = [], []
    for index, (sprite, entry) in enumerate(zip(sprites, entries)):
        if "source_box" in entry and list(entry["source_box"]) != list(sprite.box):
            raise ValueError(f"Frame {index + 1} crop changed; regenerate the landmark template")
        for value in entry.get("anchors", {}).values():
            point(value)
        names = sorted(set(ref) & set(entry["points"]))
        if not names:
            raise ValueError(f"Frame {index + 1} has no named landmarks shared with the reference")
        motion = entry.get("motion", [0, 0])
        if len(motion) != 2 or not all(math.isfinite(float(v)) for v in motion):
            raise ValueError("motion must contain two finite destination-pixel offsets")
        source, target, weights = [], [], []
        for name in names:
            p, pw = point(entry["points"][name])
            q, qw = point(ref[name])
            if not (sprite.box[0] <= p[0] < sprite.box[2] and sprite.box[1] <= p[1] < sprite.box[3]):
                raise ValueError(f"Frame {index + 1} landmark {name} is outside its source crop")
            source.append((p[0] - sprite.box[0], p[1] - sprite.box[1]))
            target.append((q[0] - ref_origin[0] + ref_x + float(motion[0]),
                           q[1] - ref_origin[1] + ref_y + float(motion[1])))
            weights.append(min(pw, qw))
        transform, report = fit_landmarks(source, target, weights, allow_scale)
        report.update({"names": names, "motion": motion})
        transforms.append(transform)
        reports.append(report)
    return transforms, reports


def render(sprites, transforms, padding, canvas=None, nearest=False):
    bounds = []
    for sprite, (scale, dx, dy) in zip(sprites, transforms):
        left, top, right, bottom = sprite.image.getchannel("A").getbbox()
        bounds.append((math.floor(scale * left + dx), math.floor(scale * top + dy),
                       math.ceil(scale * right + dx), math.ceil(scale * bottom + dy)))
    left, top = min(b[0] for b in bounds), min(b[1] for b in bounds)
    right, bottom = max(b[2] for b in bounds), max(b[3] for b in bounds)
    required = (right - left + 2 * padding, bottom - top + 2 * padding)
    width, height = canvas or required
    if width < required[0] or height < required[1]:
        raise ValueError(f"Canvas {width}x{height} would clip poses; need at least {required[0]}x{required[1]}")
    shift = ((width - (right - left)) // 2 - left, (height - (bottom - top)) // 2 - top)
    frames, final = [], []
    for sprite, (scale, dx, dy) in zip(sprites, transforms):
        dx, dy = dx + shift[0], dy + shift[1]
        if scale == 1 and dx == round(dx) and dy == round(dy):
            frame = Image.new("RGBA", (width, height))
            frame.paste(sprite.image, (int(dx), int(dy)))
        else:
            frame = sprite.image.transform((width, height), Image.Transform.AFFINE,
                (1 / scale, 0, -dx / scale, 0, 1 / scale, -dy / scale),
                resample=Image.Resampling.NEAREST if nearest else Image.Resampling.BICUBIC)
        frames.append(frame)
        final.append((scale, dx, dy))
    return frames, final


def onion_frames(frames, opacity):
    def tint(image, color):
        ghost = Image.new("RGBA", image.size, color)
        ghost.putalpha(image.getchannel("A").point(lambda a: round(a * opacity)))
        return ghost
    result = []
    for i, frame in enumerate(frames):
        overlay = Image.alpha_composite(frame, tint(frames[(i - 1) % len(frames)], "#ff5050"))
        result.append(Image.alpha_composite(overlay, tint(frames[(i + 1) % len(frames)], "#35e0ff")))
    return result


def atlas(frames, columns):
    width, height = frames[0].size
    result = Image.new("RGBA", (width * columns, height * math.ceil(len(frames) / columns)))
    for i, frame in enumerate(frames):
        result.paste(frame, (i % columns * width, i // columns * height))
    return result


def contact_sheet(frames, columns):
    width, height = frames[0].size
    result = Image.new("RGB", (width * columns, (height + 24) * math.ceil(len(frames) / columns)), "#24262b")
    draw = ImageDraw.Draw(result)
    for i, frame in enumerate(frames):
        x, y = i % columns * width, i // columns * (height + 24)
        draw.text((x + 8, y + 6), f"Frame {i + 1:03d}", fill="white")
        result.paste(frame, (x, y + 24), frame)
    return result


def save_gif(frames, path, duration):
    rgb = []
    samples = Image.new("RGB", (128 * len(frames), 128), "#24262b")
    for i, frame in enumerate(frames):
        image = Image.new("RGBA", frame.size, "#24262b")
        image = Image.alpha_composite(image, frame).convert("RGB")
        rgb.append(image)
        sample = image.copy()
        sample.thumbnail((128, 128))
        samples.paste(sample, (128 * i, 0))
    palette = samples.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    converted = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image in rgb]
    converted[0].save(path, save_all=True, append_images=converted[1:],
                      duration=duration, loop=0, disposal=2, optimize=False)
    with Image.open(path) as gif:
        durations = []
        for i in range(gif.n_frames):
            gif.seek(i)
            durations.append(gif.info["duration"])
        return {"encoded_frames": gif.n_frames, "durations_ms": durations,
                "total_duration_ms": sum(durations)}


def run(args):
    if (args.padding < 2 or args.min_area < 1 or args.search < 0 or not 0 <= args.alpha_threshold < 255 or
            args.duration < 10 or args.duration % 10 or not 0 <= args.onion_opacity <= 1):
        raise ValueError("Need padding >=2, min-area >=1, search >=0, duration a positive multiple of 10 ms, opacity in [0,1]")
    if args.landmarks and args.body_roi:
        raise ValueError("Choose either --landmarks or --body-roi")
    if args.allow_scale and not args.landmarks:
        raise ValueError("--allow-scale requires named body landmarks")
    if args.out.exists() and any(args.out.iterdir()):
        raise ValueError("Output directory must be new or empty; use a new revision directory")
    with Image.open(args.sheet) as opened:
        image = opened.convert("RGBA")
        if image.getchannel("A").getextrema()[0] == 255:
            raise ValueError("Input must have real alpha transparency; remove painted backgrounds first")
    sprites, extraction = extract(image, args.columns, args.rows, args.mode, args.min_area, args.alpha_threshold)
    reference = args.reference - 1
    if not 0 <= reference < len(sprites):
        raise ValueError("--reference is a 1-based extracted frame index")
    raw, staged = stage(sprites, args.padding)
    transforms = staged
    reports = [{} for _ in sprites]
    method = "layout-only; no anatomical alignment"
    config = None
    if args.landmarks:
        config = json.loads(args.landmarks.read_text())
        if config.get("source_sha256", digest(args.sheet)) != digest(args.sheet):
            raise ValueError("Landmark source hash differs from the input sheet")
        if len(config["frames"]) != len(sprites):
            raise ValueError("Recipe frame count differs from the input sheet")
        if config.get("align_body", True) and not args.no_align:
            transforms, reports = landmark_transforms(sprites, staged, config, reference, args.allow_scale)
            method = "weighted stable-body landmarks; rotation locked at zero"
        else:
            method = "layout only; body alignment disabled"
    elif args.body_roi and not args.no_align:
        method = "body-ROI template matching; translation only; provisional"
        transforms = []
        for i, frame in enumerate(raw):
            dx, dy, score = match_region(raw[reference], frame, args.body_roi, args.search)
            _, sx, sy = staged[i]
            transforms.append((1.0, sx + dx, sy + dy))
            reports[i] = {"provisional": True, "photometric_mean_absolute_error": score,
                          "search_boundary_reached": args.search > 0 and max(abs(dx), abs(dy)) == args.search}
    working = sprites
    edit_reports = [[] for _ in sprites]
    if config and any(frame.get("edits") for frame in config["frames"]):
        import sprite_edits
        if config.get("local_edits_version", sprite_edits.VERSION) not in sprite_edits.SUPPORTED_VERSIONS:
            raise ValueError("Unsupported local edit recipe version")
        working, edit_reports = sprite_edits.apply_all(sprites,
            [frame.get("edits", []) for frame in config["frames"]], args.nearest,
            [frame["points"] if config.get("align_body", True) and not args.no_align else {} for frame in config["frames"]])
        transforms = sprite_edits.adjust_transforms(sprites, working, transforms)
        method += "; deterministic local edits"
    frames, transforms = render(working, transforms, args.padding, args.canvas, args.nearest)
    onions = onion_frames(frames, args.onion_opacity)
    args.out.mkdir(parents=True, exist_ok=True)
    for name in ("extracted", "aligned", "onion"):
        (args.out / name).mkdir()
    for i, (sprite, frame, onion) in enumerate(zip(sprites, frames, onions), 1):
        sprite.image.save(args.out / "extracted" / f"{i:03d}.png")
        frame.save(args.out / "aligned" / f"{i:03d}.png")
        onion.save(args.out / "onion" / f"{i:03d}.png")
    atlas(frames, args.columns).save(args.out / "atlas.png")
    contact_sheet(raw, args.columns).save(args.out / "raw-contact.png")
    contact_sheet(frames, args.columns).save(args.out / "aligned-contact.png")
    contact_sheet(onions, args.columns).save(args.out / "onion-contact.png")
    guide = Image.alpha_composite(Image.new("RGBA", raw[reference].size, "#24262b"), raw[reference])
    draw = ImageDraw.Draw(guide)
    for x in range(0, guide.width, 50):
        draw.line((x, 0, x, guide.height - 1), fill=(255, 255, 255, 100))
        draw.text((x + 2, 2), str(x), fill="white")
    for y in range(50, guide.height, 50):
        draw.line((0, y, guide.width - 1, y), fill=(255, 255, 255, 100))
        draw.text((2, y + 2), str(y), fill="white")
    guide.save(args.out / "reference-guide.png")
    gifs = {name: save_gif(sequence, args.out / name, args.duration)
            for name, sequence in (("raw.gif", raw), ("aligned.gif", frames), ("onion.gif", onions))}
    template = {"source_sha256": digest(args.sheet),
                "notes": "Fill named stable-body points using source-sheet pixel coordinates, not guide coordinates. Use motion to preserve intended destination-pixel displacement.",
                "frames": [{"source_box": list(s.box), "points": {}, "motion": [0, 0]} for s in sprites]}
    (args.out / "landmarks-template.json").write_text(json.dumps(template, indent=2) + "\n")
    frame_records = []
    for i, (sprite, (scale, dx, dy), report) in enumerate(zip(sprites, transforms, reports), 1):
        origin_x, origin_y = working[i - 1].box[:2]
        matrix = [[scale, 0, dx - scale * origin_x], [0, scale, dy - scale * origin_y], [0, 0, 1]]
        anchors = {}
        if config:
            input_anchors = config["frames"][i - 1].get("anchors", {})
            if config["frames"][i - 1].get("edits"):
                local_anchor_map = sprite_edits.map_anchors(sprite, working[i - 1], config["frames"][i - 1]["edits"], input_anchors)
                input_anchors = {name: anchor["xy"] for name, anchor in local_anchor_map.items()}
            for name, value in input_anchors.items():
                xy, _ = point(value)
                anchors[name] = [scale * xy[0] + matrix[0][2], scale * xy[1] + matrix[1][2]]
        frame_records.append({"index": i, "source_box": sprite.box, "source_to_output_matrix": matrix,
            "edited_source_box": working[i - 1].box, "edit_operations": edit_reports[i - 1],
            "uniform_scale": scale, "rotation_degrees": 0, "transformed_anchors": anchors,
            "alignment_check": report, "png": f"aligned/{i:03d}.png",
            "sha256": digest(args.out / "aligned" / f"{i:03d}.png"),
            "duration_ms": args.duration})
    manifest = {"tool": "sprite_postprocess", "version": VERSION,
                "script_sha256": digest(__file__), "source": str(args.sheet), "source_sha256": digest(args.sheet),
                "source_size": image.size, "extraction": extraction, "reference_frame": args.reference,
                "method": method, "parameters": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                "landmark_input": config, "landmark_sha256": digest(args.landmarks) if args.landmarks else None,
                "canvas": frames[0].size, "frames": frame_records, "gifs": gifs,
                "onion_legend": "previous=red, current=original, next=cyan; neighbors wrap at the loop seam",
                "resampling": "integer translations are lossless; other transforms use " + ("nearest" if args.nearest else "bicubic"),
                "status": "candidate for human review; no anatomical or runtime approval",
                "limitations": ["Automatic body matching is provisional and can erase intended torso motion; use landmark motion offsets to preserve it.",
                                "Component order and island assignment need visual review; touching poses require manual separation.",
                                "GIFs use a shared 256-color palette on a dark background; PNG alpha/colors are retained.",
                                "Preview GIFs are derived from PNGs, not browser recordings. No anatomy, final-scale or game integration test is implied."]}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def parser():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("sheet", type=Path)
    p.add_argument("--out", type=Path, required=True, help="New or empty output directory")
    p.add_argument("--columns", type=int, required=True)
    p.add_argument("--rows", type=int, required=True)
    p.add_argument("--mode", choices=("components", "grid"), default="components")
    p.add_argument("--min-area", type=int, default=128, help="Minimum connected-pose area, not a noise deletion threshold")
    p.add_argument("--alpha-threshold", type=int, default=2, help="Detection threshold 0..254; faint source pixels are still retained")
    p.add_argument("--reference", type=int, default=1, help="1-based frame index")
    p.add_argument("--body-roi", type=int, nargs=4, metavar=("X", "Y", "W", "H"), help="Stable torso rectangle in staged reference-guide.png coordinates")
    p.add_argument("--search", type=int, default=48, help="Translation search radius in pixels")
    p.add_argument("--landmarks", type=Path, help="JSON body points in source-sheet coordinates")
    p.add_argument("--allow-scale", action="store_true", help="Fit a whole-frame uniform scale from body landmarks")
    p.add_argument("--no-align", action="store_true", help="Apply a recipe without fitting body landmarks")
    p.add_argument("--padding", type=int, default=16)
    p.add_argument("--canvas", type=int, nargs=2, metavar=("W", "H"), help="Optional fixed canvas; undersized values fail")
    p.add_argument("--nearest", action="store_true", help="Nearest-neighbor sampling for pixel art")
    p.add_argument("--duration", type=int, default=100, help="Milliseconds per frame, multiple of 10")
    p.add_argument("--onion-opacity", type=float, default=0.3)
    p.add_argument("--editor", action="store_true", help="Open the local landmark editor server instead of a batch export")
    p.add_argument("--port", type=int, default=0, help="Local editor port (0 chooses an available port)")
    patch = p.add_mutually_exclusive_group()
    patch.add_argument("--patch-diagnose", type=Path, help="Classify an annotated defect without generating anything")
    patch.add_argument("--patch-prepare", type=Path, help="Export a masked local-correction request from JSON")
    patch.add_argument("--patch-import", type=Path, help="Import an external candidate into a request folder")
    patch.add_argument("--patch-replay", type=Path, help="Reproduce and compare a preserved patch attempt")
    patch.add_argument("--patch-review", type=Path, help="Append an explicit visual review to an attempt")
    p.add_argument("--patch-candidate", type=Path)
    p.add_argument("--patch-registration", type=Path)
    p.add_argument("--patch-generation", type=Path)
    p.add_argument("--patch-review-file", type=Path)
    return p


def main():
    p = parser()
    args = p.parse_args()
    try:
        if args.patch_diagnose:
            from sprite_patches.diagnosis import classify
            print(json.dumps(classify(json.loads(args.patch_diagnose.read_text())), ensure_ascii=False))
            return
        if any((args.patch_prepare, args.patch_import, args.patch_replay, args.patch_review)):
            from sprite_patches.workflow import run as patch_run
            print(patch_run(args))
            return
        if args.editor:
            from sprite_editor_server import serve
            serve(args)
            return
        manifest = run(args)
    except (ValueError, OSError, KeyError, TypeError) as error:
        p.exit(2, f"sprite_postprocess: {error}\n")
    print(f"Wrote {len(manifest['frames'])} frames to {args.out}; {manifest['method']}")


if __name__ == "__main__":
    main()
