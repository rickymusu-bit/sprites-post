"""Immutable request materials, separate context crop and editable mask."""
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil

from PIL import Image
import sprite_postprocess as core
from .diagnosis import require_local
from .raster import pixels


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def seal(folder):
    dump(folder / "hashes.json", {str(p.relative_to(folder)): core.digest(p)
        for p in sorted(folder.rglob("*")) if p.is_file() and p.name != "hashes.json"})


def verify(folder):
    entries = json.loads((folder / "hashes.json").read_text())
    for name, expected in entries.items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file() or core.digest(path) != expected:
            raise ValueError(f"Materiale assente o modificato: {name}")


def prepare(session, project, spec, folder, spec_root):
    diagnosis = require_local(spec)
    if type(spec.get("frame")) is not int:
        raise ValueError("Frame della richiesta non valido (intero da 1)")
    index = spec["frame"] - 1
    if type(index) is not int or not 0 <= index < len(session.sprites):
        raise ValueError("Frame della richiesta non valido (indice da 1)")
    import sprite_edits
    originals, _ = sprite_edits.apply_all(session.sprites, [f["edits"] for f in project["frames"]], project["nearest"],
        [f["points"] if project["align_body"] else {} for f in project["frames"]])
    snapshot = originals[index]
    from .preparation import region
    mask, crop, local, polygon = region(snapshot, spec, project["frames"][index])
    refs = []
    for i, ref in enumerate(spec["references"], 1):
        if not isinstance(ref, dict) or ref.get("approved") is not True or not ref.get("revision") or not ref.get("role"):
            raise ValueError("Ogni riferimento richiede approved=true, revisione e ruolo")
        path = (spec_root / ref["path"]).resolve()
        with Image.open(path) as image:
            if image.format != "PNG":
                raise ValueError("I riferimenti devono essere PNG")
            image.verify()
        refs.append(dict(ref, original_path=str(path), file=f"references/{i:03d}.png", sha256=core.digest(path)))
    folder.mkdir()
    (folder / "references").mkdir()
    shutil.copyfile(session.sheet, folder / "source-sheet.png")
    snapshot.image.save(folder / "original-frame.png")
    mask.save(folder / "mask-frame.png")
    snapshot.image.crop(local).save(folder / "context.png")
    mask.crop(local).save(folder / "mask-crop.png")
    for ref in refs:
        shutil.copyfile(ref["original_path"], folder / ref["file"])
    neighbors = []
    if len(originals) > 1:
        for label, number in (("previous", (index - 1) % len(originals)), ("next", (index + 1) % len(originals))):
            originals[number].image.save(folder / f"{label}.png")
            neighbors.append({"file": f"{label}.png", "frame": number + 1, "source_box": originals[number].box})
    dump(folder / "generation-template.json", {"service": "", "output_provenance": "",
        "prompt_confirmed_exact": False, "supplied_files": ["original-frame.png", "context.png"] + [r["file"] for r in refs] + [n["file"] for n in neighbors],
        "notes": "Copy this template outside the sealed request. Record only actually supplied files and exposed service parameters."})
    dump(folder / "registration-template.json", {"landmarks": [], "allow_scale": False, "allow_rotation": False,
        "nearest": project["nearest"], "max_residual_px": 2, "feather_px": 0})
    (folder / "prompt.txt").write_text(spec["prompt"], encoding="utf-8")
    dump(folder / "project.json", project)
    settings = {k: str(v) if isinstance(v, Path) else v for k, v in vars(session.args).items() if not k.startswith("patch_")}
    dump(folder / "request.json", {"schema_version": "1.0.0", "prepared_at": datetime.now(timezone.utc).isoformat(), "status": "prepared_not_sent", "diagnosis": diagnosis,
        "specification": spec, "frame": index + 1, "snapshot_box": snapshot.box, "crop_box": crop,
        "mask_polygon": polygon, "base_pixels_sha256": pixels(snapshot.image, snapshot.box), "source_sha256": session.source_hash,
        "references": refs, "neighbors": neighbors, "settings": settings,
        "generator": "external/manual; no API assumed", "prompt_scope": "exact explicit instruction; hidden service context unavailable"})
    seal(folder)


def implementation():
    scripts = Path(core.__file__).parent
    files = [scripts / name for name in ("sprite_postprocess.py", "sprite_edits.py", "sprite_editor_server.py")]
    files += sorted((scripts / "sprite_patches").glob("*.py"))
    return {str(file.relative_to(scripts)): core.digest(file) for file in files}


def next_folder(parent, prefix):
    number = 1
    while (parent / f"{prefix}-{number:03d}").exists():
        number += 1
    return parent / f"{prefix}-{number:03d}"


