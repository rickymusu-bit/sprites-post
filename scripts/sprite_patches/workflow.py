"""CLI orchestration of the single sprite pipeline; no generation service."""
import json
from pathlib import Path
import tempfile

from PIL import Image
import sprite_postprocess as core
from .materials import prepare, verify, next_folder, implementation
from .importer import import_candidate
from .verification import review


def run(args):
    from sprite_editor_server import EditorSession
    if args.patch_prepare:
        session = EditorSession(args)
        spec = json.loads(args.patch_prepare.read_text())
        session.output.mkdir(parents=True, exist_ok=True)
        destination = next_folder(session.output, "patch")
        with tempfile.TemporaryDirectory(prefix=".patch-prepare-", dir=session.output) as temp:
            folder = Path(temp) / "request"
            prepare(session, session.project, spec, folder, args.patch_prepare.resolve().parent)
            folder.rename(destination)
        return destination
    if args.patch_import:
        if not args.patch_candidate:
            raise ValueError("Specificare --patch-candidate")
        return import_candidate(args.patch_import, args.patch_candidate, args.patch_registration, args.patch_generation)
    if args.patch_replay:
        attempt = args.patch_replay.resolve()
        verify(attempt)
        manifest = json.loads((attempt / "manifest.json").read_text())
        if manifest.get("implementation_sha256") != implementation():
            raise ValueError("Riproduzione esatta: usare la revisione del tool registrata nel manifest")
        if manifest["pillow_version"] != Image.__version__:
            raise ValueError("Riproduzione esatta: usare la stessa versione Pillow registrata")
        request = (attempt / manifest["request_folder"]).resolve()
        if core.digest(request / "hashes.json") != manifest["request_hashes_sha256"]:
            raise ValueError("Il fascicolo sorgente della riproduzione è cambiato")
        replayed = import_candidate(request, attempt / "generated.png", attempt / "registration-input.json", attempt / "generation.json", operation_id=manifest.get("operation_id", attempt.name))
        for file in ("final-frame.png", "diagnostics/atlas.png", "diagnostics/aligned.gif", "project-patched.json"):
            if core.digest(attempt / file) != core.digest(replayed / file):
                raise ValueError(f"Riproduzione non identica: {file}")
        return replayed
    if args.patch_review:
        if not args.patch_review_file:
            raise ValueError("Specificare --patch-review-file")
        verify(args.patch_review.resolve())
        return review(args.patch_review, json.loads(args.patch_review_file.read_text()))
    raise ValueError("Azione di correzione mancante")
