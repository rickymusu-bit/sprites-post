"""Pure mask/context geometry; no files or generation calls."""
from PIL import Image, ImageDraw
import sprite_edits


def region(snapshot, spec, entry):
    l, t, r, b = snapshot.box
    polygon = spec.get("mask_polygon")
    if polygon is None and spec.get("mask_from_edit"):
        selected = next((op for op in entry["edits"] if op["id"] == spec["mask_from_edit"] and op["type"] == "part"), None)
        if selected:
            polygon = selected["mask"]
    if not isinstance(polygon, list) or not 3 <= len(polygon) <= 256:
        raise ValueError("Maschera: servono da 3 a 256 vertici in coordinate sorgente")
    polygon = [sprite_edits.pair(p) for p in polygon]
    area = sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(polygon, polygon[1:] + polygon[:1]))
    if abs(area) < 0.01:
        raise ValueError("La maschera ha area nulla")
    if any(not l <= x < r or not t <= y < b for x, y in polygon):
        raise ValueError("Maschera fuori dal frame originale: ridefinire la regione esplicitamente")
    mask = Image.new("L", snapshot.image.size)
    ImageDraw.Draw(mask).polygon([(x - l, y - t) for x, y in polygon], fill=255)
    bounds = mask.getbbox()
    padding = spec.get("context_padding", 32)
    if type(padding) is not int or not 0 <= padding <= 1024:
        raise ValueError("Padding del contesto non valido")
    x0, y0, x1, y1 = bounds
    crop = [max(l, l + x0 - padding), max(t, t + y0 - padding), min(r, l + x1 + padding), min(b, t + y1 + padding)]
    if "context_box" in spec:
        crop = spec["context_box"]
        if (not isinstance(crop, list) or len(crop) != 4 or any(type(v) is not int for v in crop) or
                not (l <= crop[0] <= l + x0 < l + x1 <= crop[2] <= r and
                     t <= crop[1] <= t + y0 < t + y1 <= crop[3] <= b)):
            raise ValueError("Il contesto esplicito deve essere dentro il frame e contenere tutta la maschera")
    local = (crop[0] - l, crop[1] - t, crop[2] - l, crop[3] - t)
    return mask, crop, local, polygon
