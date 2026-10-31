"""Local HTTP adapter for the SAME request/import/review pipeline."""
import base64
import copy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import tempfile
import zipfile

from PIL import Image
import sprite_postprocess as core
from .importer import import_candidate
from .materials import prepare, next_folder, verify
from .raster import encode, replace
from .registration import register, finite
from .verification import compare, review, latest_review

REQUEST = re.compile(r"patch-\d{3,}$")
ATTEMPT = re.compile(r"patch-\d{3,}-attempt-\d{3,}$")
UPLOAD = re.compile(r"[a-f0-9]{64}$")
REQUEST_FILES = {"context.png", "mask-crop.png", "mask-frame.png", "original-frame.png", "source-sheet.png",
                 "previous.png", "next.png", "prompt.txt", "project.json", "request.json", "generation-template.json", "registration-template.json"}
ATTEMPT_FILES = {"before-after.png", "before-after-crop.png", "final-frame.png", "registered-crop.png", "generated.png",
                 "diagnostics/aligned.gif", "diagnostics/onion.gif", "verification.json"}


class BrowserPatches:
    def __init__(self, session):
        self.session = session
        self.root = session.output / "patches"
        self.uploads = session.output / "patch-uploads"

    def request(self, identifier):
        if not isinstance(identifier, str) or not REQUEST.fullmatch(identifier):
            raise ValueError("Richiesta locale non valida")
        folder = self.root / identifier
        data = json.loads((folder / "request.json").read_text())
        if data["source_sha256"] != self.session.source_hash:
            raise ValueError("La richiesta appartiene a un'altra sorgente")
        return folder, data

    def attempt(self, identifier):
        if not isinstance(identifier, str) or not ATTEMPT.fullmatch(identifier):
            raise ValueError("Tentativo locale non valido")
        folder = self.root / identifier
        data = json.loads((folder / "manifest.json").read_text())
        if data["source_sha256"] != self.session.source_hash:
            raise ValueError("Il tentativo appartiene a un'altra sorgente")
        return folder, data

    def uploaded(self, identifier):
        if not isinstance(identifier, str) or not UPLOAD.fullmatch(identifier):
            raise ValueError("PNG caricato non valido")
        path = self.uploads / (identifier + ".png")
        if core.digest(path) != identifier:
            raise ValueError("Il PNG caricato è cambiato")
        return path

    def store_png(self, encoded):
        if not isinstance(encoded, str) or len(encoded) > 22_000_000:
            raise ValueError("PNG mancante o troppo grande")
        data = base64.b64decode(encoded, validate=True)
        with Image.open(BytesIO(data)) as image:
            if image.format != "PNG" or image.width * image.height > 16_000_000 or getattr(image, "n_frames", 1) != 1:
                raise ValueError("Serve un singolo PNG entro 16 milioni di pixel")
            image.load()
            size = list(image.size)
        identifier = hashlib.sha256(data).hexdigest()
        self.uploads.mkdir(parents=True, exist_ok=True)
        path = self.uploads / (identifier + ".png")
        try:
            with path.open("xb") as stream:
                stream.write(data)
        except FileExistsError:
            if core.digest(path) != identifier:
                raise ValueError("Archivio upload incoerente")
        return identifier, path, size

    def summary_request(self, folder, data):
        return {"id": folder.name, "frame": data["frame"], "subject": data["specification"]["subject"],
            "defect": data["diagnosis"]["defect"], "prompt": data["specification"]["prompt"], "crop_box": data["crop_box"],
            "mask_polygon": data["mask_polygon"], "required_files": ["original-frame.png", "context.png"] + [r["file"] for r in data["references"]],
            "optional_files": [n["file"] for n in data["neighbors"]] + ["mask-crop.png"],
            "url": f"/api/patch/file/{folder.name}/", "archive_url": f"/api/patch/archive/{folder.name}.zip"}

    def summary_attempt(self, folder, data):
        decision = latest_review(folder)
        return {"id": folder.name, "request_id": Path(data["request_folder"]).name,
            "frame": data["frame"], "status": decision["status"],
            "review": decision, "has_crop_comparison": (folder / "before-after-crop.png").is_file(), "url": f"/api/patch/attempt/{folder.name}/"}

    def listing(self):
        requests, attempts = [], []
        if self.root.is_dir():
            for folder in sorted(self.root.iterdir()):
                if not folder.is_dir():
                    continue
                try:
                    if REQUEST.fullmatch(folder.name):
                        _, data = self.request(folder.name)
                        requests.append(self.summary_request(folder, data))
                    elif ATTEMPT.fullmatch(folder.name):
                        _, data = self.attempt(folder.name)
                        if not data.get("replay_of"):
                            attempts.append(self.summary_attempt(folder, data))
                except (OSError, ValueError, KeyError):
                    continue
        return {"requests": requests, "attempts": attempts}

    def prepare(self, payload):
        project = self.session.validate(payload["project"])
        spec = copy.deepcopy(payload["spec"])
        if not isinstance(spec, dict):
            raise ValueError("La richiesta deve essere un oggetto JSON")
        references = payload.get("references", [])
        if not isinstance(references, list) or len(references) > 32 or any(not isinstance(ref, dict) for ref in references):
            raise ValueError("Elenco dei riferimenti non valido")
        if payload.get("references_approved") is not True:
            raise ValueError("Conferma che i riferimenti selezionati siano approvati")
        refs = []
        if payload.get("use_source_reference") is True:
            refs.append({"path": str(self.session.sheet), "revision": self.session.source_hash,
                "role": "Sorgente confermata approvata dall'operatore", "approved": True})
        for ref in references:
            _, path, _ = self.store_png(ref["png"])
            refs.append({"path": str(path), "revision": ref.get("revision"),
                "role": ref.get("role"), "approved": True, "upload_name": str(ref.get("name", "reference.png"))[:160]})
        spec["references"] = refs
        preview = self.session.compute(project)
        if not self.session.describe(preview, 0)["can_export"]:
            raise ValueError("Completa l'allineamento corporeo o disattivalo esplicitamente prima di preparare l'intervento")
        self.root.mkdir(parents=True, exist_ok=True)
        destination = next_folder(self.root, "patch")
        with tempfile.TemporaryDirectory(prefix=".prepare-", dir=self.root) as temporary:
            folder = Path(temporary) / "request"
            prepare(self.session, project, spec, folder, self.root)
            folder.rename(destination)
        return self.summary_request(*self.request(destination.name))

    def upload(self, payload):
        self.request(payload["request_id"])
        identifier, _, size = self.store_png(payload["png"])
        return {"id": identifier, "size": size, "url": f"/api/patch/upload/{identifier}.png"}

    def registration_preview(self, payload):
        folder, _ = self.request(payload["request_id"])
        verify(folder)
        candidate = Image.open(self.uploaded(payload["upload_id"])).convert("RGBA")
        mask = Image.open(folder / "mask-crop.png").convert("L")
        original = Image.open(folder / "context.png").convert("RGBA")
        settings = payload.get("registration", {})
        registered, transform = register(candidate, mask, settings)
        feather = finite(settings.get("feather_px", 0), "Sfumatura", 0, 32)
        composite = replace(original, registered, mask, feather)
        return {"registered_png": encode(registered), "composite_png": encode(composite), "transform": transform,
            "verification": compare(original, composite, mask)}

    def base_project(self, identifier, project):
        folder, data = self.request(identifier)
        verify(folder)
        current = self.session.validate(project)
        saved = self.session.validate(json.loads((folder / "project.json").read_text()))
        if current != saved:
            raise ValueError("Il progetto è cambiato dopo la preparazione: riprendi il progetto della richiesta o prepara un nuovo intervento")
        return folder, data, current

    def resume(self, payload):
        folder, _ = self.request(payload["request_id"])
        verify(folder)
        return {"project": self.session.validate(json.loads((folder / "project.json").read_text()))}

    def apply(self, payload):
        folder, _, _ = self.base_project(payload["request_id"], payload["project"])
        candidate = self.uploaded(payload["upload_id"])
        with tempfile.TemporaryDirectory(prefix=".import-", dir=self.root) as temporary:
            temp = Path(temporary)
            for name, value in (("registration", payload.get("registration", {})), ("generation", payload["generation"])):
                (temp / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False))
            attempt = import_candidate(folder, candidate, temp / "registration.json", temp / "generation.json")
        project = self.session.validate(json.loads((attempt / "project-patched.json").read_text()))
        self.session.compute(project)
        return {"project": project, "attempt": self.summary_attempt(*self.attempt(attempt.name))}

    def expected_operation(self, folder, manifest):
        frozen = json.loads((folder / "project-patched.json").read_text())
        frame = manifest["frame"] - 1
        identifier = manifest.get("operation_id", folder.name)
        expected = next((op for op in frozen["frames"][frame]["edits"] if op["id"] == identifier), None)
        return frame, expected

    @staticmethod
    def matches(expected, current):
        return bool(expected and current) and all(current.get(k) == v for k, v in expected.items() if k not in ("name", "enabled"))

    def operation(self, project, folder, manifest):
        frame, expected = self.expected_operation(folder, manifest)
        current = next((op for op in project["frames"][frame]["edits"] if op["id"] == manifest.get("operation_id", folder.name)), None)
        if not expected or not current:
            raise ValueError("La correzione selezionata non è presente nel progetto corrente")
        if not self.matches(expected, current):
            raise ValueError("La correzione corrente differisce dal tentativo conservato")
        return frame, current

    def decide(self, payload):
        project = self.session.validate(payload["project"])
        folder, manifest = self.attempt(payload["attempt_id"])
        verify(folder)
        if manifest.get("replay_of"):
            raise ValueError("Questo fascicolo è un replay: revisiona il tentativo originale")
        index, op = self.operation(project, folder, manifest)
        decision = payload["decision"]
        if not isinstance(decision, dict):
            raise ValueError("La decisione deve essere un oggetto JSON")
        if decision.get("status") == "approved" and not op["enabled"]:
            raise ValueError("Attiva la correzione prima di revisionarla")
        self.session.compute(project)
        if decision.get("status") == "rejected":
            request_id = Path(manifest["request_folder"]).name
            request_folder, _ = self.request(request_id)
            verify(request_folder)
            previous = json.loads((request_folder / "project.json").read_text())
            project["frames"][index]["edits"] = copy.deepcopy(previous["frames"][index]["edits"])
            project = self.session.validate(project)
            self.session.compute(project)
        result = review(folder, decision)
        return {"project": project, "decision": result, "attempt": self.summary_attempt(folder, manifest)}

    def status_for(self, op):
        identifier = op.get("attempt_id", op.get("id"))
        if not isinstance(identifier, str) or not ATTEMPT.fullmatch(identifier):
            return {"status": "pending_visual_review"}
        try:
            folder, manifest = self.attempt(identifier)
            _, expected = self.expected_operation(folder, manifest)
            if not self.matches(expected, op):
                raise ValueError("Operazione non corrispondente al tentativo")
            return latest_review(folder)
        except (ValueError, OSError, KeyError):
            return {"status": "unavailable"}

    def resource(self, path):
        prefix = "/api/patch/"
        if path == prefix + "list":
            return self.listing(), "application/json; charset=utf-8"
        if path.startswith(prefix + "upload/") and path.endswith(".png"):
            identifier = path[len(prefix + "upload/"):-4]
            return self.uploaded(identifier).read_bytes(), "image/png"
        if path.startswith(prefix + "archive/") and path.endswith(".zip"):
            identifier = path[len(prefix + "archive/"):-4]
            folder, _ = self.request(identifier)
            verify(folder)
            stream = BytesIO()
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                for file in sorted(folder.rglob("*")):
                    if file.is_file() and file.resolve().is_relative_to(folder.resolve()):
                        archive.write(file, str(file.relative_to(folder)))
            return stream.getvalue(), "application/zip"
        for category, resolver, allowed in (("file", self.request, REQUEST_FILES), ("attempt", self.attempt, ATTEMPT_FILES)):
            start = prefix + category + "/"
            if path.startswith(start):
                identifier, name = path[len(start):].split("/", 1)
                if name not in allowed and not (category == "file" and re.fullmatch(r"references/\d{3}.png", name)):
                    raise ValueError("File del fascicolo non disponibile")
                folder, _ = resolver(identifier)
                file = (folder / name).resolve()
                if not file.is_relative_to(folder.resolve()):
                    raise ValueError("Percorso non valido")
                kind = "image/png" if name.endswith(".png") else "image/gif" if name.endswith(".gif") else "text/plain; charset=utf-8"
                return file.read_bytes(), kind
        raise ValueError("Risorsa della correzione non disponibile")

    def dispatch(self, path, payload):
        actions = {"prepare": self.prepare, "upload": self.upload, "registration": self.registration_preview,
                   "resume": self.resume, "apply": self.apply, "review": self.decide}
        action = path.removeprefix("/api/patch/")
        if action not in actions:
            raise ValueError("Operazione di correzione non disponibile")
        if not isinstance(payload, dict):
            raise ValueError("La richiesta deve essere un oggetto JSON")
        with self.session.lock:
            return actions[action](payload)
