"""Explicit candidate-to-crop similarity mapping; native landmark coordinates."""
import math
from PIL import Image


def finite(value, name, minimum=-100000, maximum=100000):
    if type(value) not in (float, int) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name}: valore finito fuori intervallo")
    return float(value)


def point(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("Landmark: servono due coordinate native")
    return complex(*(finite(v, "Coordinata") for v in value))


def initial_mapping(candidate_size, target_size, settings, pairs):
    mapping = settings.get("input_mapping")
    if mapping is None:
        if candidate_size != target_size and not (len(pairs) >= 2 and settings.get("allow_scale")):
            raise ValueError("Dimensioni diverse dal crop: scegliere adattamento uniforme esplicito o almeno due landmark con scala abilitata")
        return 1.0, 0j, "identity" if candidate_size == target_size else "landmarks"
    if not isinstance(mapping, dict):
        raise ValueError("Adattamento delle dimensioni non valido")
    mode = mapping.get("mode")
    if mode == "fit":
        scale = min(t / c for c, t in zip(candidate_size, target_size))
        offset = complex(*((t - scale * c) / 2 for c, t in zip(candidate_size, target_size)))
    elif mode == "uniform":
        scale = finite(mapping.get("scale"), "Scala input", 1 / 4096, 4096)
        offset = point(mapping.get("offset"))
    else:
        raise ValueError("Adattamento: usare fit oppure uniform con scala e offset espliciti")
    return scale, offset, mode


def register(candidate, mask, settings):
    if not isinstance(settings, dict):
        raise ValueError("Registrazione non valida")
    for field in ("allow_scale", "allow_rotation", "nearest"):
        if type(settings.get(field, False)) is not bool:
            raise ValueError(f"{field}: usare un booleano")
    pairs = settings.get("landmarks", [])
    if not isinstance(pairs, list) or len(pairs) > 128:
        raise ValueError("Landmark di registrazione non validi")
    src, dst = [], []
    for pair in pairs:
        if not isinstance(pair, dict):
            raise ValueError("Landmark non valido")
        p, q = point(pair.get("generated")), point(pair.get("target"))
        if not (0 <= p.real < candidate.width and 0 <= p.imag < candidate.height and
                0 <= q.real < mask.width and 0 <= q.imag < mask.height):
            raise ValueError("Landmark fuori dalle immagini")
        src.append(p)
        dst.append(q)
    scale0, offset0, mapping_mode = initial_mapping(candidate.size, mask.size, settings, pairs)
    mapped = [scale0 * p + offset0 for p in src]
    a, shift = 1 + 0j, 0j
    if pairs:
        u, v = sum(mapped) / len(mapped), sum(dst) / len(dst)
        if len(pairs) > 1:
            denominator = sum(abs(p - u) ** 2 for p in mapped)
            if denominator < 1e-10:
                raise ValueError("Landmark coincidenti")
            correlation = sum((q - v) * (p - u).conjugate() for p, q in zip(mapped, dst))
            scale = abs(correlation) / denominator if settings.get("allow_scale", False) else 1
            angle = math.atan2(correlation.imag, correlation.real) if settings.get("allow_rotation", False) else 0
            a = scale * complex(math.cos(angle), math.sin(angle))
        elif settings.get("allow_scale") or settings.get("allow_rotation"):
            raise ValueError("Scala e rotazione richiedono almeno due landmark")
        shift = v - a * u
    total_a, total_shift = a * scale0, a * offset0 + shift
    if not math.isfinite(abs(total_a)) or not 1 / 4096 <= abs(total_a) <= 4096:
        raise ValueError("Scala di registrazione fuori intervallo")
    tolerance = finite(settings.get("max_residual_px", 2), "Tolleranza", 0, 128)
    residuals = [abs(total_a * p + total_shift - q) for p, q in zip(src, dst)]
    residual = max(residuals, default=0)
    if residual > tolerance:
        raise ValueError("Residuo landmark oltre la tolleranza: correggere punti o rigenerare")
    inv, off = 1 / total_a, -total_shift / total_a
    coeff = (inv.real, -inv.imag, off.real, inv.imag, inv.real, off.imag)
    coverage = Image.new("L", candidate.size, 255).transform(mask.size, Image.Transform.AFFINE, coeff, Image.Resampling.NEAREST)
    if any(m and not c for m, c in zip(mask.tobytes(), coverage.tobytes())):
        raise ValueError("La trasformazione non copre tutta la maschera; ampliare esplicitamente il crop o correggere l'adattamento")
    resampling = Image.Resampling.NEAREST if settings.get("nearest") else Image.Resampling.BICUBIC
    transformed = candidate.copy() if total_a == 1 and total_shift == 0 and candidate.size == mask.size else candidate.transform(
        mask.size, Image.Transform.AFFINE, coeff, resampling)
    return transformed, {"matrix": [total_a.real, -total_a.imag, total_shift.real, total_a.imag, total_a.real, total_shift.imag],
        "landmark_count": len(pairs), "max_residual_px": residual, "residuals_px": residuals,
        "candidate_size": list(candidate.size), "target_size": list(mask.size), "mapping_mode": mapping_mode,
        "input_mapping_matrix": [scale0, 0, offset0.real, 0, scale0, offset0.imag],
        "registration": "explicit_mapping_unverified" if not pairs else "annotated_landmarks",
        "resampling": "nearest" if settings.get("nearest") else "bicubic"}
