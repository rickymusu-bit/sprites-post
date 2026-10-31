"""Local-only landmark editor, sharing the existing extraction/registration code."""

import copy
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import math
from pathlib import Path
import secrets
import tempfile
import threading
from urllib.parse import urlsplit

from PIL import Image

import sprite_postprocess as core
import sprite_edits as local_edits

STATIC = Path(__file__).with_name("sprite_editor")


def png(image):
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def finite_pair(value, description):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{description}: servono due coordinate")
    values = [float(v) for v in value]
    if not all(math.isfinite(v) for v in values):
        raise ValueError(f"{description}: coordinate non valide")
    return values


@dataclass
class Preview:
    project: dict
    raw: list
    aligned: list
    raw_transforms: list
    transforms: list
    reports: list
    images: dict
    working_boxes: list
    edit_reports: list
    edited_anchors: list


class EditorSession:
    def __init__(self, args):
        self.args = args
        self.sheet = args.sheet.resolve()
        self.output = args.out.resolve()
        if args.padding < 2 or args.min_area < 1 or not 0 <= args.alpha_threshold < 255:
            raise ValueError("Padding, area minima o soglia alpha non validi")
        with Image.open(self.sheet) as source:
            self.image = source.convert("RGBA")
        if self.image.getchannel("A").getextrema()[0] == 255:
            raise ValueError("L'immagine deve avere uno sfondo realmente trasparente")
        self.source_hash = core.digest(self.sheet)
        self.sprites, self.extraction = core.extract(self.image, args.columns, args.rows,
            args.mode, args.min_area, args.alpha_threshold)
        _, self.staged = core.stage(self.sprites, args.padding)
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.revision = 0
        self.cache = {}
        self.project = {"source_sha256": self.source_hash,
            "frames": [{"source_box": list(s.box), "points": {}, "motion": [0, 0]} for s in self.sprites]}
        if args.landmarks:
            self.project = json.loads(args.landmarks.read_text())
        self.project.setdefault("reference_frame", args.reference)
        self.project.setdefault("allow_scale", args.allow_scale)
        self.project.setdefault("duration_ms", args.duration)
        self.project.setdefault("nearest", args.nearest)
        if args.no_align:
            self.project["align_body"] = False
        self.project = self.validate(self.project)
        from sprite_patches.browser import BrowserPatches
        self.patches = BrowserPatches(self)

    def validate(self, project):
        if core.digest(self.sheet) != self.source_hash:
            raise ValueError("La sorgente è cambiata su disco: riapri l’editor prima di continuare")
        if not isinstance(project, dict) or project.get("source_sha256") != self.source_hash:
            raise ValueError("Questo progetto appartiene a un'altra immagine sorgente")
        result = copy.deepcopy(project)
        if result.get("local_edits_version", local_edits.VERSION) not in local_edits.SUPPORTED_VERSIONS:
            raise ValueError("Versione delle correzioni locali non supportata")
        result["local_edits_version"] = local_edits.VERSION
        reference = result.get("reference_frame", self.args.reference)
        if type(reference) is not int or not 1 <= reference <= len(self.sprites):
            raise ValueError("Frame di riferimento non valido")
        duration = result.get("duration_ms", self.args.duration)
        if type(duration) is not int or not 10 <= duration <= 60000 or duration % 10:
            raise ValueError("La durata deve essere un multiplo di 10 ms, da 10 a 60000")
        for field in ("allow_scale", "nearest", "align_body"):
            default = field == "align_body"
            if type(result.get(field, default)) is not bool:
                raise ValueError(f"Valore {field} non valido")
            result[field] = result.get(field, default)
        entries = result.get("frames")
        if not isinstance(entries, list) or len(entries) != len(self.sprites):
            raise ValueError("Il numero di frame del progetto non corrisponde alla sorgente")
        for index, (entry, sprite) in enumerate(zip(entries, self.sprites), 1):
            if not isinstance(entry, dict) or entry.get("source_box") != list(sprite.box):
                raise ValueError(f"Il ritaglio del frame {index} è cambiato: verifica le impostazioni")
            if not isinstance(entry.get("points"), dict):
                raise ValueError(f"Punti del frame {index} non validi")
            for name, value in entry["points"].items():
                if not isinstance(name, str) or not name.strip() or len(name) > 80:
                    raise ValueError("Il nome del punto deve contenere da 1 a 80 caratteri")
                xy, weight = core.point(value)
                left, top, right, bottom = sprite.box
                if not left <= xy[0] < right or not top <= xy[1] < bottom:
                    raise ValueError(f"Il punto {name} è fuori dal frame {index}")
                entry["points"][name] = {"xy": list(xy), "weight": weight}
            entry["motion"] = finite_pair(entry.get("motion", [0, 0]), "Movimento intenzionale")
            entry["edits"] = local_edits.validate(entry.get("edits", []), len(self.sprites))
            if not isinstance(entry.get("anchors", {}), dict):
                raise ValueError("Ancoraggi non validi")
            for value in entry.get("anchors", {}).values():
                core.point(value)
        result.update(reference_frame=reference, duration_ms=duration,
                      editor_version="1.2.0")
        return result

    def compute(self, project):
        project = self.validate(project)
        ref_index = project["reference_frame"] - 1
        reference = project["frames"][ref_index]
        transforms, reports = [], []
        for i, (sprite, entry) in enumerate(zip(self.sprites, project["frames"])):
            if not project["align_body"]:
                transforms.append(self.staged[i])
                reports.append({"status": "disabled", "provisional": False, "landmark_count": 0,
                    "message": "Solo correzioni locali; allineamento del corpo disattivato"})
                continue
            shared = set(reference["points"]) & set(entry["points"])
            if not shared:
                transforms.append(self.staged[i])
                reports.append({"provisional": True, "landmark_count": 0,
                    "status": "missing", "message": "Aggiungi punti corrispondenti al riferimento"})
                continue
            try:
                fitted, checks = core.landmark_transforms(
                    [self.sprites[ref_index], sprite], [self.staged[ref_index], self.staged[i]],
                    {"frames": [reference, entry]}, 0, project["allow_scale"])
                transforms.append(fitted[1])
                reports.append(dict(checks[1], status="provisional" if checks[1]["provisional"] else "fitted"))
            except ValueError as error:
                transforms.append(self.staged[i])
                reports.append({"provisional": True, "landmark_count": len(shared),
                    "status": "error", "message": str(error)})
        corrected, edit_reports = local_edits.apply_all(self.sprites,
            [frame["edits"] for frame in project["frames"]], project["nearest"],
            [frame["points"] if project["align_body"] else {} for frame in project["frames"]])
        transforms = local_edits.adjust_transforms(self.sprites, corrected, transforms)
        # Local masks remain in source coordinates; the body registration is
        # unchanged. Expanded corrected canvases keep all transformed parts.
        combined, final = core.render(self.sprites + corrected, self.staged + transforms,
            self.args.padding, self.args.canvas, project["nearest"])
        count = len(self.sprites)
        raw, aligned = combined[:count], combined[count:]
        images = {(kind, i): png(image) for kind, sequence in (("raw", raw), ("aligned", aligned))
                  for i, image in enumerate(sequence)}
        anchors = [local_edits.map_anchors(original, changed, frame["edits"], frame.get("anchors", {}))
                   for original, changed, frame in zip(self.sprites, corrected, project["frames"])]
        return Preview(project, raw, aligned, final[:count], final[count:], reports, images,
                       [list(s.box) for s in corrected], edit_reports, anchors)

    def describe(self, preview, revision):
        frames = []
        for i, sprite in enumerate(self.sprites):
            def matrix(transform, origin):
                scale, x, y = transform
                return [scale, 0, 0, scale, x - scale * origin[0], y - scale * origin[1]]
            aligned_matrix = matrix(preview.transforms[i], preview.working_boxes[i])
            anchors = {}
            for name, anchor in preview.edited_anchors[i].items():
                x, y = anchor["xy"]
                anchors[name] = dict(anchor, xy=[aligned_matrix[0] * x + aligned_matrix[4], aligned_matrix[3] * y + aligned_matrix[5]])
            for operation in preview.edit_reports[i]:
                if operation.get("type") == "patch" or any(op["id"] == operation["id"] and op["type"] == "patch" for op in preview.project["frames"][i]["edits"]):
                    recipe = next(op for op in preview.project["frames"][i]["edits"] if op["id"] == operation["id"])
                    operation["review"] = self.patches.status_for(recipe)
            frames.append({"index": i, "source_box": list(sprite.box), "anchors": anchors,
                "working_box": preview.working_boxes[i], "edit_operations": preview.edit_reports[i],
                "raw_matrix": matrix(preview.raw_transforms[i], sprite.box),
                "aligned_matrix": aligned_matrix, "check": preview.reports[i],
                "raw_url": f"/api/image/{revision}/raw/{i}.png",
                "aligned_url": f"/api/image/{revision}/aligned/{i}.png"})
        return {"revision": revision, "canvas": list(preview.aligned[0].size), "frames": frames,
                "project": preview.project,
                "can_export": not any(r["status"] in ("missing", "error") for r in preview.reports)}

    def preview(self, project):
        with self.lock:
            result = self.compute(project)
            self.revision += 1
            self.cache[self.revision] = result
            for key in sorted(self.cache)[:-3]:
                del self.cache[key]
            return self.describe(result, self.revision)

    def save(self, project):
        with self.lock:
            validated = self.validate(project)
            self.output.mkdir(parents=True, exist_ok=True)
            path = self.output / "project.json"
            if path.resolve() == self.sheet:
                raise ValueError("La sorgente non può essere sovrascritta dal progetto")
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.output, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(json.dumps(validated, ensure_ascii=False, indent=2) + "\n")
            temporary.replace(path)
            self.project = validated
            return {"file": "project.json", "path": str(path)}

    def export(self, project):
        with self.lock:
            preview = self.compute(project)
            if any(r["status"] in ("missing", "error") for r in preview.reports):
                raise ValueError("Completa i punti corrispondenti di tutti i frame prima di esportare")
            self.output.mkdir(parents=True, exist_ok=True)
            index = 1
            while (self.output / f"export-{index:03d}").exists():
                index += 1
            destination = self.output / f"export-{index:03d}"
            with tempfile.TemporaryDirectory(prefix=".sprite-export-", dir=self.output) as temporary:
                folder = Path(temporary)
                (folder / "aligned").mkdir()
                (folder / "onion").mkdir()
                onions = core.onion_frames(preview.aligned, 0.3)
                for i, (frame, onion) in enumerate(zip(preview.aligned, onions), 1):
                    frame.save(folder / "aligned" / f"{i:03d}.png")
                    onion.save(folder / "onion" / f"{i:03d}.png")
                core.atlas(preview.aligned, self.args.columns).save(folder / "atlas.png")
                gifs = {name: core.save_gif(sequence, folder / name, preview.project["duration_ms"])
                        for name, sequence in (("raw.gif", preview.raw), ("aligned.gif", preview.aligned), ("onion.gif", onions))}
                (folder / "landmarks.json").write_text(json.dumps(preview.project, ensure_ascii=False, indent=2) + "\n")
                frames = self.describe(preview, 0)["frames"]
                for i, record in enumerate(frames):
                    record.pop("raw_url")
                    record.pop("aligned_url")
                    record.update(png=f"aligned/{i + 1:03d}.png", sha256=core.digest(folder / "aligned" / f"{i + 1:03d}.png"),
                                  duration_ms=preview.project["duration_ms"])
                manifest = {"tool": "sprite_editor", "version": "1.2.0", "source": str(self.sheet),
                    "source_sha256": self.source_hash, "project": "landmarks.json",
                    "local_edits_version": local_edits.VERSION, "render_engine": f"Pillow {Image.__version__}",
                    "canvas": list(preview.aligned[0].size), "frames": frames, "gifs": gifs,
                    "extraction": self.extraction, "status": "candidate for visual review",
                    "canvas_policy": "shared union of raw and fitted poses; identical preview and export",
                    "limitations": "Landmark residuals do not certify anatomy; no runtime test or upload is implied."}
                (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
                folder.rename(destination)
            return {"path": str(destination), "file": destination.name,
                    "gif_url": f"/api/export/{destination.name}/aligned.gif"}


def make_server(session, port=0):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, data, kind="application/json; charset=utf-8"):
            if not isinstance(data, bytes):
                data = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.headers.get("Host") not in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"):
                self.send(403, {"error": "Host non valido per l’editor locale"})
                return
            path = urlsplit(self.path).path
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/editor.js": ("editor.js", "text/javascript; charset=utf-8"),
                      "/edits.js": ("edits.js", "text/javascript; charset=utf-8"),
                      "/patches.js": ("patches.js", "text/javascript; charset=utf-8"),
                      "/editor.css": ("editor.css", "text/css; charset=utf-8")}
            if path in assets:
                filename, kind = assets[path]
                self.send(200, (STATIC / filename).read_bytes(), kind)
            elif path.startswith("/api/patch/"):
                try:
                    with session.lock:
                        data, kind = session.patches.resource(path)
                    self.send(200, data, kind)
                except (ValueError, KeyError, OSError) as exc:
                    self.send(404, {"error": str(exc)})
            elif path == "/api/state":
                self.send(200, {"project": session.project, "token": session.token,
                    "source_name": session.sheet.name, "source_size": list(session.image.size),
                    "frame_count": len(session.sprites), "output": str(session.output)})
            elif path.startswith("/api/image/"):
                try:
                    _, _, _, revision, kind, filename = path.split("/")
                    if kind not in ("raw", "aligned") or not filename.endswith(".png"):
                        raise ValueError()
                    with session.lock:
                        data = session.cache[int(revision)].images[(kind, int(filename[:-4]))]
                    self.send(200, data, "image/png")
                except (KeyError, ValueError, IndexError):
                    self.send(404, {"error": "Anteprima non disponibile: aggiorna il frame"})
            elif path.startswith("/api/export/"):
                parts = path.split("/")
                if (len(parts) == 5 and parts[3].startswith("export-") and parts[3][7:].isdigit()
                        and parts[4] == "aligned.gif"):
                    file = session.output / parts[3] / "aligned.gif"
                    if file.is_file():
                        self.send(200, file.read_bytes(), "image/gif")
                        return
                self.send(404, {"error": "Esportazione non disponibile"})
            else:
                self.send(404, {"error": "Risorsa non disponibile"})

        def do_POST(self):
            origin = self.headers.get("Origin")
            expected = f"http://{self.headers.get('Host')}"
            host_valid = self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")
            if not host_valid or self.headers.get("X-Sprite-Token") != session.token or (origin and origin != expected):
                self.send(403, {"error": "Richiesta non autorizzata per questa sessione locale"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                limit = 24_000_000
                if not 0 < length <= limit:
                    raise ValueError("Progetto troppo grande o vuoto")
                project = json.loads(self.rfile.read(length))
                if self.path.startswith("/api/patch/"):
                    self.send(200, session.patches.dispatch(self.path, project))
                    return
                method = {"/api/preview": session.preview, "/api/save": session.save, "/api/export": session.export}.get(self.path)
                if method is None:
                    self.send(404, {"error": "Operazione non disponibile"})
                    return
                self.send(200, method(project))
            except (ValueError, TypeError, KeyError, OSError) as error:
                self.send(400, {"error": str(error)})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(args):
    session = EditorSession(args)
    with make_server(session, args.port) as server:
        print(f"Editor locale: http://127.0.0.1:{server.server_port}", flush=True)
        print(f"Progetti ed esportazioni: {session.output}\nCTRL+C per chiudere. Nessun caricamento su GitHub.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
