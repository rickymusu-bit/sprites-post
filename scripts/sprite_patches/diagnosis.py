"""Route a diagnosed defect before exporting any generative request."""
ROUTES = {
    "position": "postprocess", "alignment": "postprocess", "scale": "postprocess",
    "color": "postprocess", "alpha": "postprocess", "rigid_rotation": "pivot",
    "missing_detail": "local_imagegen", "anatomy_detail": "local_imagegen",
    "hidden_surface": "local_imagegen_with_references",
    "impossible_pose": "new_keyframe", "perspective": "regenerate_frame",
}


def classify(spec):
    if not isinstance(spec, dict):
        raise ValueError("La diagnosi deve essere un oggetto JSON")
    kind = spec.get("error_type")
    if kind not in ROUTES:
        raise ValueError("Classificazione mancante o sconosciuta")
    route = ROUTES[kind]
    if not isinstance(spec.get("defect"), str) or not spec["defect"].strip():
        raise ValueError("Descrivere il difetto prima di intervenire")
    return {"error_type": kind, "route": route, "defect": spec["defect"]}


def require_local(spec):
    diagnosis = classify(spec)
    kind, route = diagnosis["error_type"], diagnosis["route"]
    if not route.startswith("local_imagegen"):
        raise ValueError(f"{kind}: procedura preferita {route}; nessuna richiesta ImageGen locale esportata")
    for field in ("subject", "correction", "geometry", "connections", "preserve", "prompt"):
        if not isinstance(spec.get(field), str) or not spec[field].strip():
            raise ValueError(f"Campo obbligatorio: {field}")
    if not isinstance(spec.get("references"), list) or not 1 <= len(spec["references"]) <= 32:
        raise ValueError("Fornire almeno un riferimento canonico approvato")
    return {"error_type": kind, "route": route, "defect": spec["defect"]}
