"""Import a preserved external PNG through the existing recipe/export engine."""
import copy
import json
from pathlib import Path
import shutil
import tempfile

from PIL import Image
import sprite_postprocess as core
from . import VERSION
from .materials import dump, seal, verify, next_folder, implementation
from .raster import encode
from .registration import register
from .verification import compare, comparison


def open_request(folder, output):
    from sprite_editor_server import EditorSession
    verify(folder)
    request = json.loads((folder / "request.json").read_text())
    settings = request["settings"]
    args = core.parser().parse_args([str(folder / "source-sheet.png"), "--columns", str(settings["columns"]),
        "--rows", str(settings["rows"]), "--out", str(output)])
    for key in ("mode", "min_area", "alpha_threshold", "padding", "canvas", "duration", "reference"):
        setattr(args, key, settings[key])
    args.landmarks = folder / "project.json"
    return EditorSession(args), request


def import_candidate(folder, candidate_path, registration_path=None, generation_path=None, operation_id=None):
    folder = folder.resolve()
    destination = next_folder(folder.parent, folder.name + "-attempt")
    with tempfile.TemporaryDirectory(prefix=".patch-import-", dir=folder.parent) as temp:
        temporary = Path(temp)
        session, request = open_request(folder, temporary / "render")
        registration = json.loads(registration_path.read_text()) if registration_path else {}
        generation = json.loads(generation_path.read_text()) if generation_path else {}
        if not isinstance(generation, dict):
            raise ValueError("Metadati della generazione non validi")
        if generation.get("prompt_confirmed_exact") is not True:
            raise ValueError("Registrare prompt_confirmed_exact=true solo se prompt.txt è l'istruzione effettivamente inviata")
        required = ["original-frame.png", "context.png"] + [r["file"] for r in request["references"]]
        allowed = required + [n["file"] for n in request["neighbors"]] + ["mask-crop.png"]
        supplied = generation.get("supplied_files")
        if not isinstance(supplied, list) or any(p not in supplied for p in required) or any(p not in allowed for p in supplied):
            raise ValueError("Registrare supplied_files con originale, crop e riferimenti effettivamente forniti; vicini e maschera sono facoltativi")
        if not generation.get("service") or not generation.get("output_provenance"):
            raise ValueError("Registrare servizio e provenienza reale dell'output, senza inventare parametri")
        shutil.copyfile(candidate_path, temporary / "generated.png")
        with Image.open(temporary / "generated.png") as image:
            if image.format != "PNG" or image.width * image.height > 16_000_000 or getattr(image, "n_frames", 1) != 1:
                raise ValueError("La correzione deve essere un PNG entro 16 milioni di pixel")
            candidate = image.convert("RGBA")
        mask = Image.open(folder / "mask-crop.png").convert("L")
        registered, transform = register(candidate, mask, registration)
        op = {"type": "patch", "patch_version": VERSION, "id": operation_id or destination.name, "name": "Correzione locale esterna", "enabled": True,
            "package_id": folder.name, "attempt_id": operation_id or destination.name, "crop_box": request["crop_box"], "base_pixels_sha256": request["base_pixels_sha256"],
            "mask_outline": request["mask_polygon"], "mask_png": encode(mask), "patch_png": encode(registered), "feather_px": registration.get("feather_px", 0),
            "transform": transform, "approval": "pending_visual_review"}
        project = copy.deepcopy(session.project)
        i = request["frame"] - 1
        project["frames"][i]["edits"].append(op)
        # Replay in the SAME recipe engine used by CLI and live editor.
        import sprite_edits
        sprites, _ = sprite_edits.apply_all(session.sprites, [f["edits"] for f in project["frames"]], project["nearest"],
            [f["points"] if project["align_body"] else {} for f in project["frames"]])
        original = Image.open(folder / "original-frame.png").convert("RGBA")
        full_mask = Image.open(folder / "mask-frame.png").convert("L")
        final = sprites[i].image
        report = compare(original, final, full_mask)
        final.save(temporary / "final-frame.png")
        comparison(original, final, temporary / "before-after.png")
        l, t = request["snapshot_box"][:2]
        x0, y0, x1, y1 = request["crop_box"]
        local = (x0 - l, y0 - t, x1 - l, y1 - t)
        comparison(original.crop(local), final.crop(local), temporary / "before-after-crop.png")
        registered.save(temporary / "registered-crop.png")
        dump(temporary / "registration-input.json", registration)
        dump(temporary / "generation.json", generation)
        dump(temporary / "transform.json", transform)
        dump(temporary / "project-patched.json", project)
        dump(temporary / "verification.json", report)
        from .verification import CHECKS
        dump(temporary / "review-template.json", {"status": "pending", "reviewer": "", "notes": "",
            "checks": {k: False for k in CHECKS}, "evidence": []})
        result = session.export(project)
        rendered = Path(result["path"])
        shutil.move(str(rendered), temporary / "diagnostics")
        shutil.rmtree(temporary / "render")
        dump(temporary / "manifest.json", {"tool": "sprite_postprocess.local_patch", "version": VERSION,
            "request_folder": "../" + folder.name, "request_hashes_sha256": core.digest(folder / "hashes.json"),
            "source_sha256": request["source_sha256"], "status": "pending_visual_review",
            "frame": request["frame"], "crop_box": request["crop_box"], "transform": transform,
            "operation_id": operation_id or destination.name,
            "replay_of": operation_id if operation_id and operation_id != destination.name else None,
            "implementation_sha256": implementation(), "final_sha256": core.digest(temporary / "final-frame.png"),
            "diagnostic_gif": "diagnostics/aligned.gif", "pillow_version": Image.__version__,
            "limits": "Pixel proof is on native corrected frame before global registration. No anatomy or game certification."})
        seal(temporary)
        temporary.rename(destination)
    return destination


