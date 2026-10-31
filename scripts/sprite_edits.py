"""Versioned, deterministic raster recipes. Immutable original pixels are samples.

Coordinates are native source-sheet coordinates. Local edits are independent of
the body registration; masked parts cannot move a registration landmark unless
that landmark is the fixed pivot. No inference, random input or image service.
"""

import copy
import math

from PIL import Image, ImageChops, ImageDraw

import sprite_postprocess as core

VERSION = "1.1.0"
SUPPORTED_VERSIONS = {"1.0.0", VERSION}
MAX_PIXELS = 16_000_000


def pair(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("Servono due coordinate per ogni punto della correzione")
    result = [float(v) for v in value]
    if not all(math.isfinite(v) and abs(v) <= 100_000 for v in result):
        raise ValueError("Coordinate della correzione non valide")
    return result


def number(value, lower, upper, name):
    result = float(value)
    if not math.isfinite(result) or not lower <= result <= upper:
        raise ValueError(f"{name}: valore fuori intervallo")
    return result


def validate(operations, frame_count):
    if not isinstance(operations, list) or len(operations) > 256:
        raise ValueError("Ricetta non valida: massimo 256 operazioni per frame")
    result = copy.deepcopy(operations)
    for i, op in enumerate(result):
        if not isinstance(op, dict) or op.get("type") not in ("part", "paint", "erase", "clone", "patch"):
            raise ValueError("Tipo di correzione non riconosciuto")
        op.setdefault("id", f"edit-{i + 1}")
        op.setdefault("name", f"Correzione {i + 1}")
        if not isinstance(op["name"], str) or not 1 <= len(op["name"]) <= 80:
            raise ValueError("Il nome della correzione deve contenere da 1 a 80 caratteri")
        op.setdefault("enabled", True)
        if type(op["enabled"]) is not bool:
            raise ValueError("Stato della correzione non valido")
        if op["type"] == "patch":
            from sprite_patches.raster import validate as validate_patch
            validate_patch(op)
        elif op["type"] == "part":
            polygon = op.get("mask")
            if not isinstance(polygon, list) or not 3 <= len(polygon) <= 256:
                raise ValueError("La maschera richiede da 3 a 256 vertici")
            op["mask"] = [pair(p) for p in polygon]
            area = sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(op["mask"], op["mask"][1:] + op["mask"][:1]))
            if abs(area) < 0.01:
                raise ValueError("La maschera ha area nulla")
            op["pivot"] = pair(op.get("pivot"))
            op["translate"] = pair(op.get("translate", [0, 0]))
            op["rotation_deg"] = number(op.get("rotation_deg", 0), -360, 360, "Rotazione")
            op["scale"] = number(op.get("scale", 1), 0.1, 8, "Scala uniforme")
            op.setdefault("cut", True)
            op.setdefault("pivot_confirmed", False)
            if type(op["cut"]) is not bool or type(op["pivot_confirmed"]) is not bool:
                raise ValueError("Impostazioni della parte non valide")
            if op["enabled"] and not op["pivot_confirmed"] and (op["rotation_deg"] != 0 or op["scale"] != 1):
                raise ValueError("Imposta esplicitamente il pivot prima di ruotare o scalare la parte")
        else:
            points = op.get("points")
            if not isinstance(points, list) or not 1 <= len(points) <= 4096:
                raise ValueError("Il tratto richiede da 1 a 4096 punti")
            op["points"] = [pair(p) for p in points]
            op["radius"] = number(op.get("radius", 4), 0.5, 256, "Raggio del pennello")
            if op["type"] == "paint":
                color = op.get("color")
                if not isinstance(color, list) or len(color) != 4 or any(type(v) is not int or not 0 <= v <= 255 for v in color):
                    raise ValueError("Il colore deve essere RGBA, quattro interi da 0 a 255")
            if op["type"] == "clone":
                if type(op.get("source_frame")) is not int or not 0 <= op["source_frame"] < frame_count:
                    raise ValueError("Frame sorgente del clone non valido")
                op["source_point"] = pair(op.get("source_point"))
    return result


def matrix(op):
    angle = math.radians(op["rotation_deg"])
    a, b = op["scale"] * math.cos(angle), op["scale"] * math.sin(angle)
    # Exact quadrants avoid accidental interpolation for integer transforms.
    a, b = [float(round(v)) if abs(v - round(v)) < 1e-12 else v for v in (a, b)]
    c, d = -b, a
    x, y = op["pivot"]
    dx, dy = op["translate"]
    return [a, b, c, d, x + dx - a * x - c * y, y + dy - b * x - d * y]


def transform(point, m):
    x, y = point
    a, b, c, d, dx, dy = m
    return [a * x + c * y + dx, b * x + d * y + dy]


def expanded(working, extent):
    left = math.floor(min(working.box[0], extent[0]))
    top = math.floor(min(working.box[1], extent[1]))
    right = math.ceil(max(working.box[2], extent[2]))
    bottom = math.ceil(max(working.box[3], extent[3]))
    if (right - left) * (bottom - top) > MAX_PIXELS or max(right - left, bottom - top) > 8192:
        raise ValueError("Correzione troppo grande: riduci spostamento, scala o dimensione del tratto")
    if (left, top, right, bottom) == working.box:
        return core.Sprite(working.image.copy(), working.box)
    image = Image.new("RGBA", (right - left, bottom - top))
    image.paste(working.image, (working.box[0] - left, working.box[1] - top))
    return core.Sprite(image, (left, top, right, bottom))


def polygon_mask(sprite, polygon):
    mask = Image.new("L", sprite.image.size)
    ImageDraw.Draw(mask).polygon([(x - sprite.box[0], y - sprite.box[1]) for x, y in polygon], fill=255)
    return mask


def part(original, working, op, nearest, registration_points):
    mask = polygon_mask(original, op["mask"])
    alpha = ImageChops.multiply(original.image.getchannel("A"), mask)
    bounds = alpha.getbbox()
    if not bounds:
        raise ValueError("La maschera non seleziona pixel visibili dell’originale")
    m = matrix(op)
    if op["cut"]:
        for value in registration_points.values():
            point, _ = core.point(value)
            x, y = math.floor(point[0] - original.box[0]), math.floor(point[1] - original.box[1])
            if 0 <= x < mask.width and 0 <= y < mask.height and mask.getpixel((x, y)):
                moved = transform(point, m)
                if math.dist(point, moved) > 1e-6:
                    raise ValueError("La parte muove un punto di allineamento: scegli punti stabili fuori dalla maschera")
    source_box = (original.box[0] + bounds[0], original.box[1] + bounds[1],
                  original.box[0] + bounds[2], original.box[1] + bounds[3])
    check = {"type": "part", "matrix": m, "source_mask_bbox": list(source_box),
             "pivot": op["pivot"], "cut": op["cut"]}
    if op["cut"] and m == [1, 0, 0, 1, 0, 0]:
        image = working.image.copy()
        image.paste(original.image, (original.box[0] - working.box[0], original.box[1] - working.box[1]), mask)
        return core.Sprite(image, working.box), check
    corners = [transform(p, m) for p in [(source_box[0], source_box[1]), (source_box[2], source_box[1]),
                                       (source_box[2], source_box[3]), (source_box[0], source_box[3])]]
    padding = 0 if nearest else 2
    working = expanded(working, [min(p[0] for p in corners) - padding, min(p[1] for p in corners) - padding,
                                max(p[0] for p in corners) + padding, max(p[1] for p in corners) + padding])
    if op["cut"]:
        cut = Image.new("L", working.image.size)
        cut.paste(mask, (original.box[0] - working.box[0], original.box[1] - working.box[1]))
        working.image = Image.composite(Image.new("RGBA", working.image.size), working.image, cut)
    patch = original.image.copy()
    patch.putalpha(alpha)
    patch = patch.crop(bounds)
    a, b, c, d, dx, dy = m
    if (a, b, c, d) == (1, 0, 0, 1) and dx == round(dx) and dy == round(dy):
        working.image.alpha_composite(patch, (int(source_box[0] + dx - working.box[0]), int(source_box[1] + dy - working.box[1])))
    else:
        determinant = a * d - b * c
        left, top = working.box[:2]
        inverse = (d / determinant, -c / determinant,
                   (d * (left - dx) - c * (top - dy)) / determinant - source_box[0],
                   -b / determinant, a / determinant,
                   (-b * (left - dx) + a * (top - dy)) / determinant - source_box[1])
        warped = patch.transform(working.image.size, Image.Transform.AFFINE, inverse,
            resample=Image.Resampling.NEAREST if nearest else Image.Resampling.BICUBIC)
        working.image = Image.alpha_composite(working.image, warped)
    return working, check


def stroke_mask(size, origin, points, radius):
    mask = Image.new("L", size)
    draw = ImageDraw.Draw(mask)
    local = [(x - origin[0], y - origin[1]) for x, y in points]
    draw.line(local, fill=255, width=max(1, round(2 * radius)), joint="curve")
    for x, y in local:
        if radius == 0.5:
            draw.point((math.floor(x), math.floor(y)), fill=255)
        else:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
    return mask


def brush(originals, working, op):
    radius, points = op["radius"], op["points"]
    if op["type"] != "erase":
        working = expanded(working, [min(p[0] for p in points) - radius - 1, min(p[1] for p in points) - radius - 1,
                                    max(p[0] for p in points) + radius + 2, max(p[1] for p in points) + radius + 2])
    else:
        working = core.Sprite(working.image.copy(), working.box)
    mask = stroke_mask(working.image.size, working.box[:2], points, radius)
    if op["type"] == "erase":
        working.image = Image.composite(Image.new("RGBA", working.image.size), working.image, mask)
    else:
        if op["type"] == "paint":
            overlay = Image.new("RGBA", working.image.size, tuple(op["color"]))
        else:
            source = originals[op["source_frame"]]
            sx, sy = op["source_point"]
            tx, ty = points[0]
            # Sampling origin is immutable, including when previous strokes
            # painted over it. Nearest native pixels make cloning repeatable.
            overlay = source.image.transform(working.image.size, Image.Transform.AFFINE,
                (1, 0, working.box[0] + sx - tx - source.box[0],
                 0, 1, working.box[1] + sy - ty - source.box[1]), resample=Image.Resampling.NEAREST)
        overlay.putalpha(ImageChops.multiply(overlay.getchannel("A"), mask))
        working.image = Image.alpha_composite(working.image, overlay)
    return working, {"type": op["type"], "point_count": len(points), "radius": radius}


def apply_all(originals, frame_operations, nearest=False, registration_points=None):
    if len(frame_operations) != len(originals):
        raise ValueError("La ricetta deve avere un elenco di correzioni per ogni frame")
    result, reports = [], []
    registration_points = registration_points or [{} for _ in originals]
    if len(registration_points) != len(originals):
        raise ValueError("Punti di registrazione non corrispondenti ai frame")
    for original, operations, points in zip(originals, frame_operations, registration_points):
        working = core.Sprite(original.image.copy(), original.box)
        checks = []
        for op in validate(operations, len(originals)):
            if not op["enabled"]:
                checks.append({"id": op["id"], "enabled": False})
                continue
            if op["type"] == "patch":
                from sprite_patches.raster import apply as apply_patch
                working, check = apply_patch(working, op)
            elif op["type"] == "part":
                working, check = part(original, working, op, nearest, points)
            else:
                working, check = brush(originals, working, op)
            checks.append(dict(check, id=op["id"], enabled=True))
        result.append(working)
        reports.append(checks)
    return result, reports


def adjust_transforms(originals, edited, transforms):
    return [(scale, x + scale * (changed.box[0] - old.box[0]),
             y + scale * (changed.box[1] - old.box[1]))
            for old, changed, (scale, x, y) in zip(originals, edited, transforms)]


def map_anchors(original, corrected, operations, anchors):
    """Functional anchors follow moved source parts; copies retain the original.

    Sampling alpha reports visibility only, not anatomical correctness.
    """
    mapped = {}
    validated = validate([op for op in operations if op.get("type") == "part"], 1)
    for name, value in anchors.items():
        source, _ = core.point(value)
        point = list(source)
        for op in validated:
            if op["enabled"] and op["type"] == "part" and op["cut"]:
                mask = polygon_mask(original, op["mask"])
                x, y = math.floor(source[0] - original.box[0]), math.floor(source[1] - original.box[1])
                if 0 <= x < mask.width and 0 <= y < mask.height and mask.getpixel((x, y)):
                    point = transform(source, matrix(op))
        x, y = math.floor(point[0] - corrected.box[0]), math.floor(point[1] - corrected.box[1])
        visible = 0 <= x < corrected.image.width and 0 <= y < corrected.image.height and corrected.image.getpixel((x, y))[3] > 0
        mapped[name] = {"xy": point, "source_xy": list(source), "visible": visible}
    return mapped
