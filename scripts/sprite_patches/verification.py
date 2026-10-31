"""Pixel checks and explicit human acceptance, never inferred from a GIF."""
import json
import hashlib
import re
from datetime import datetime, timezone
from PIL import Image, ImageDraw
from .materials import dump

CHECKS = ("defect_fixed", "identity", "anatomy_mechanics", "neighbor_continuity", "anchors", "materials_lighting", "no_halos_seams", "final_scale")


def compare(before, after, mask):
    if before.size != after.size or before.size != mask.size:
        raise ValueError("Canvas di verifica non corrispondenti")
    outside, inside, alpha = 0, 0, 0
    for a, b, m in zip(before.getdata(), after.getdata(), mask.getdata()):
        if a != b:
            if m:
                inside += 1
            else:
                outside += 1
            alpha += a[3] != b[3]
    if outside:
        raise ValueError(f"Correzione respinta: {outside} pixel modificati fuori maschera")
    return {"outside_mask_changed_pixels": outside, "inside_mask_changed_pixels": inside,
        "alpha_changed_pixels": alpha, "technical_pass": True, "status": "pending_visual_review",
        "visual_checks": {key: "not_reviewed" for key in CHECKS},
        "runtime_capture": "not_performed; diagnostic GIF is not game evidence"}


def comparison(before, after, path):
    sheet = Image.new("RGB", (before.width * 2, before.height + 24), (24, 27, 31))
    for i, image in enumerate((before, after)):
        sheet.paste(image, (i * before.width, 24), image.getchannel("A"))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 6), "PRIMA", fill="white")
    draw.text((before.width + 8, 6), "DOPO - CANDIDATO", fill="white")
    sheet.save(path)


def review(folder, decision):
    report = json.loads((folder / "verification.json").read_text())
    if not isinstance(decision, dict):
        raise ValueError("La decisione deve essere un oggetto JSON")
    if decision.get("status") not in ("approved", "rejected") or not decision.get("reviewer") or not decision.get("notes"):
        raise ValueError("Servono stato approved/rejected, reviewer e note")
    if decision["status"] == "approved":
        if not report["technical_pass"] or not report["inside_mask_changed_pixels"]:
            raise ValueError("Non approvabile: controllo tecnico fallito o nessun pixel corretto")
        if any(decision.get("checks", {}).get(k) is not True for k in CHECKS):
            raise ValueError("Completare tutti i controlli visivi, inclusa la scala finale")
        if not isinstance(decision.get("evidence"), list) or not decision["evidence"]:
            raise ValueError("Indicare le evidenze della verifica visiva alla scala finale")
    n = 1
    while (folder / f"review-{n:03d}.json").exists():
        n += 1
    binding = {"final_sha256": json.loads((folder / "manifest.json").read_text())["final_sha256"],
               "project_sha256": hashlib.sha256((folder / "project-patched.json").read_bytes()).hexdigest()}
    record = dict(decision, recorded_at=datetime.now(timezone.utc).isoformat(), binding=binding)
    while True:
        try:
            with (folder / f"review-{n:03d}.json").open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
            break
        except FileExistsError:
            n += 1
    # Immutable evidence plus append-only review; rejection never edits source.
    return {"review": f"review-{n:03d}.json", "status": decision["status"],
        "next_step": "load original project.json to discard derivative" if decision["status"] == "rejected" else "asset candidate only; no merge or runtime approval"}


def latest_review(folder):
    records = [(int(p.stem.split("-")[1]), p) for p in folder.glob("review-*.json")
               if re.fullmatch(r"review-\d{3,}", p.stem)]
    if not records:
        return {"status": "pending_visual_review"}
    path = max(records)[1]
    record = json.loads(path.read_text())
    manifest = json.loads((folder / "manifest.json").read_text())
    expected = {"final_sha256": manifest["final_sha256"],
                "project_sha256": hashlib.sha256((folder / "project-patched.json").read_bytes()).hexdigest()}
    if record.get("binding") != expected or record.get("status") not in ("approved", "rejected"):
        return {"status": "unverified_review", "file": path.name}
    return dict(record, file=path.name)
