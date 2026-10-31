"""Bounded RGBA codec and exact masked replacement (not alpha-over)."""
import base64
import hashlib
from io import BytesIO
import math

from PIL import Image, ImageChops, ImageFilter

MAX_PIXELS = 16_000_000


def pixels(image, box):
    return hashlib.sha256(str(tuple(box)).encode() + image.convert("RGBA").tobytes()).hexdigest()


def encode(image):
    stream = BytesIO()
    image.save(stream, format="PNG")
    return base64.b64encode(stream.getvalue()).decode("ascii")


def decode(value, mode):
    if not isinstance(value, str) or len(value) > 12_000_000:
        raise ValueError("PNG incorporato troppo grande o non valido")
    try:
        data = base64.b64decode(value, validate=True)
        with Image.open(BytesIO(data)) as source:
            if source.format != "PNG" or source.width * source.height > MAX_PIXELS:
                raise ValueError("Serve un PNG entro 16 milioni di pixel")
            source.load()
            return source.convert(mode)
    except (OSError, ValueError) as exc:
        raise ValueError("PNG incorporato non valido") from exc


def validate(op):
    from . import SUPPORTED_VERSIONS
    if op.get("patch_version") not in SUPPORTED_VERSIONS:
        raise ValueError("Versione della correzione esterna non supportata")
    box = op.get("crop_box")
    if not isinstance(box, list) or len(box) != 4 or any(type(x) is not int for x in box):
        raise ValueError("Coordinate intere del crop richieste")
    if not 0 < box[2] - box[0] <= 8192 or not 0 < box[3] - box[1] <= 8192:
        raise ValueError("Dimensioni crop non valide")
    mask, patch = decode(op.get("mask_png"), "L"), decode(op.get("patch_png"), "RGBA")
    if mask.size != patch.size or mask.size != (box[2] - box[0], box[3] - box[1]):
        raise ValueError("Maschera e correzione devono avere le dimensioni del crop")
    if set(mask.getdata()) - {0, 255} or not mask.getbbox():
        raise ValueError("Maschera binaria non vuota richiesta")
    outline = op.get("mask_outline", [])
    if not isinstance(outline, list) or len(outline) > 256 or any(
            not isinstance(point, list) or len(point) != 2 or any(
                not isinstance(v, (int, float)) or not math.isfinite(v) for v in point) for point in outline):
        raise ValueError("Contorno diagnostico non valido")
    feather = op.get("feather_px", 0)
    if not isinstance(feather, (int, float)) or not math.isfinite(feather) or not 0 <= feather <= 32:
        raise ValueError("Sfumatura non valida (0–32 pixel)")
    if not isinstance(op.get("base_pixels_sha256"), str) or len(op["base_pixels_sha256"]) != 64:
        raise ValueError("Hash dello snapshot precedente richiesto")
    return mask, patch


def replace(original, patch, hard_mask, feather=0):
    """Feather only INSIDE hard support; premultiplied alpha avoids dark fringes.

    Weight 0 preserves all four source bytes, including RGB under alpha zero.
    Weight 255 copies all four candidate bytes, including alpha zero.
    """
    weight = ImageChops.multiply(hard_mask, hard_mask.filter(ImageFilter.GaussianBlur(feather))) if feather else hard_mask
    a, b, output = original.tobytes(), patch.tobytes(), bytearray(original.tobytes())
    for i, w in enumerate(weight.tobytes()):
        if not w:
            continue
        j = i * 4
        if w == 255:
            output[j:j + 4] = b[j:j + 4]
            continue
        aa, ba = a[j + 3], b[j + 3]
        alpha = aa * (255 - w) + ba * w
        output[j + 3] = (alpha + 127) // 255
        for c in range(3):
            output[j + c] = ((a[j + c] * aa * (255 - w) + b[j + c] * ba * w + alpha // 2) // alpha
                             if alpha else (a[j + c] * (255 - w) + b[j + c] * w + 127) // 255)
    return Image.frombytes("RGBA", original.size, bytes(output))


def apply(working, op):
    import sprite_postprocess as core
    mask, patch = validate(op)
    if pixels(working.image, working.box) != op["base_pixels_sha256"]:
        raise ValueError("Snapshot della correzione cambiato: ripartire dall'originale e preparare un nuovo intervento")
    x0, y0, x1, y1 = op["crop_box"]
    l, t, r, b = working.box
    if not l <= x0 < x1 <= r or not t <= y0 < y1 <= b:
        raise ValueError("Crop fuori dallo snapshot")
    box = (x0 - l, y0 - t, x1 - l, y1 - t)
    output = working.image.copy()
    output.paste(replace(output.crop(box), patch, mask, op.get("feather_px", 0)), box[:2])
    return core.Sprite(output, working.box), {"type": "patch", "outside_mask_changed_pixels": 0,
        "approval": "pending_visual_review", "crop_box": op["crop_box"], "package_id": op.get("package_id")}
