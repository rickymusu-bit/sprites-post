"""Geometric, persistence and local HTTP regressions for the landmark editor."""

import copy
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sprite_postprocess as core
from sprite_editor_server import EditorSession, make_server


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "sheet.png"
        image = Image.new("RGBA", (100, 50))
        draw = ImageDraw.Draw(image)
        draw.rectangle((5, 5, 35, 35), fill=(150, 30, 50, 230))
        draw.rectangle((60, 12, 90, 42), fill=(30, 150, 50, 220))
        image.save(self.source)
        self.source_hash = core.digest(self.source)
        args = core.parser().parse_args([str(self.source), "--columns", "2", "--rows", "1",
                                        "--out", str(self.root / "output"), "--mode", "grid"])
        self.session = EditorSession(args)
        self.project = copy.deepcopy(self.session.project)
        self.project["frames"][0]["points"] = {"a": [10, 10], "b": [30, 10], "c": [20, 30]}
        self.project["frames"][1]["points"] = {"a": [65, 17], "b": [85, 17], "c": [75, 37]}

    def tearDown(self):
        self.temporary.cleanup()

    def test_registration_and_source_coordinates_survive_shared_canvas(self):
        preview = self.session.compute(self.project)
        self.assertEqual(preview.reports[1]["weighted_rms_px"], 0)
        for p, q in zip(self.project["frames"][0]["points"].values(), self.project["frames"][1]["points"].values()):
            transform_a, transform_b = preview.transforms
            a = [p[k] + transform_a[k + 1] for k in (0, 1)]
            # The second crop's sheet origin is x50.
            b = [q[0] - 50 + transform_b[1], q[1] + transform_b[2]]
            self.assertEqual(a, b)
        self.assertEqual(preview.raw[0].size, preview.aligned[0].size)
        self.assertEqual(core.digest(self.source), self.source_hash)

    def test_missing_points_stay_provisional_and_block_export(self):
        empty = self.session.project
        preview = self.session.preview(empty)
        self.assertFalse(preview["can_export"])
        self.assertTrue(all(frame["check"]["status"] == "missing" for frame in preview["frames"]))
        self.assertTrue(all(not entry["points"] for entry in empty["frames"]))
        with self.assertRaisesRegex(ValueError, "Completa"):
            self.session.export(empty)
        self.assertFalse(self.session.output.exists())

    def test_single_point_report_is_explicitly_provisional(self):
        for frame in self.project["frames"]:
            frame["points"] = {"a": frame["points"]["a"]}
        preview = self.session.compute(self.project)
        self.assertTrue(preview.reports[1]["provisional"])
        self.assertEqual(preview.reports[1]["landmark_count"], 1)
        self.project["allow_scale"] = True
        preview = self.session.preview(self.project)
        self.assertFalse(preview["can_export"])

    def test_stale_hash_crop_and_invalid_numbers_rejected_without_writes(self):
        for mutation in (lambda p: p.update(source_sha256="old"),
                         lambda p: p.update(local_edits_version="99.0.0"),
                         lambda p: p["frames"][0].update(source_box=[0, 0, 1, 1]),
                         lambda p: p["frames"][0]["points"].update(a=[float("nan"), 10]),
                         lambda p: p.update(duration_ms=15)):
            project = copy.deepcopy(self.project)
            mutation(project)
            with self.assertRaises(ValueError):
                self.session.save(project)
        self.assertFalse(self.session.output.exists())

    def test_export_matches_live_preview_and_never_overwrites_prior_export(self):
        preview = self.session.compute(self.project)
        first = self.session.export(self.project)
        second = self.session.export(self.project)
        self.assertNotEqual(first["path"], second["path"])
        folder = Path(first["path"])
        with Image.open(folder / "aligned/002.png") as exported:
            self.assertEqual(exported.tobytes(), preview.aligned[1].tobytes())
        manifest = json.loads((folder / "manifest.json").read_text())
        self.assertEqual(manifest["gifs"]["aligned.gif"]["total_duration_ms"], 200)
        self.assertEqual(manifest["source_sha256"], self.source_hash)
        self.assertEqual(core.digest(self.source), self.source_hash)

    def test_save_and_reopen_preserve_annotations_motion_weights_and_anchors(self):
        self.project["frames"][1]["points"]["a"] = {"xy": [65, 17], "weight": 0.4}
        self.project["frames"][1]["motion"] = [2, -4]
        self.project["frames"][1]["anchors"] = {"pivot": [75, 27]}
        saved = self.session.save(self.project)
        project = json.loads(Path(saved["path"]).read_text())
        self.assertEqual(project["frames"][1]["points"]["a"]["weight"], 0.4)
        self.assertEqual(project["frames"][1]["motion"], [2, -4])
        self.assertEqual(project["frames"][1]["anchors"]["pivot"], [75, 27])
        self.assertEqual(self.session.compute(project).aligned[1].tobytes(), self.session.compute(self.project).aligned[1].tobytes())

    def test_local_recipe_exports_twice_with_identical_pngs_and_gifs(self):
        self.project["frames"][0]["edits"] = [{"type": "paint", "radius": .5, "points": [[20, 20]], "color": [1, 2, 230, 255]}]
        preview = self.session.compute(self.project)
        first, second = [Path(self.session.export(self.project)["path"]) for _ in range(2)]
        for name in ["aligned/001.png", "atlas.png", "aligned.gif", "onion.gif"]:
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
        with Image.open(first / "aligned/001.png") as im:
            self.assertEqual(im.tobytes(), preview.aligned[0].tobytes())
        saved = self.session.save(self.project)
        reopened = json.loads(Path(saved["path"]).read_text())
        self.assertEqual(self.session.compute(reopened).aligned[0].tobytes(), preview.aligned[0].tobytes())
        self.assertEqual(core.digest(self.source), self.source_hash)

    def test_local_corrections_can_export_without_body_landmarks(self):
        project = copy.deepcopy(self.session.project)
        project["align_body"] = False
        project["frames"][0]["edits"] = [{"type": "paint", "radius": .5, "points": [[20, 20]], "color": [1, 2, 230, 255]}]
        preview = self.session.preview(project)
        self.assertTrue(preview["can_export"])
        self.assertEqual(preview["frames"][0]["check"]["status"], "disabled")
        self.assertTrue(Path(self.session.export(project)["path"]).is_dir())

    def test_batch_cli_replays_editor_local_recipe(self):
        args = core.parser().parse_args([str(self.source), "--columns", "1", "--rows", "1",
            "--mode", "grid", "--out", str(self.root / "one-frame")])
        session = EditorSession(args)
        project = copy.deepcopy(session.project)
        project["align_body"] = False
        project["frames"][0]["edits"] = [{"type": "paint", "radius": .5, "points": [[20, 20]], "color": [1, 2, 230, 255]}]
        saved = session.save(project)
        exported = Path(session.export(project)["path"])
        args.landmarks = Path(saved["path"])
        args.out = self.root / "batch"
        core.run(args)
        self.assertEqual((args.out / "aligned/001.png").read_bytes(), (exported / "aligned/001.png").read_bytes())

    def test_external_source_change_invalidates_the_open_session(self):
        with Image.open(self.source) as opened:
            image = opened.copy()
        image.putpixel((10, 10), (10, 20, 30, 250))
        image.save(self.source)
        with self.assertRaisesRegex(ValueError, "cambiata su disco"):
            self.session.export(self.project)
        self.assertFalse(self.session.output.exists())

    def test_cli_editor_launches_the_local_server(self):
        log = self.root / "cli.log"
        with log.open("w") as stream:
            process = subprocess.Popen([sys.executable, str(Path(core.__file__)), str(self.source),
                "--columns", "2", "--rows", "1", "--mode", "grid", "--editor",
                "--out", str(self.root / "cli-output")], stdout=stream, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 10
                text = ""
                while time.monotonic() < deadline:
                    text = log.read_text()
                    if "Editor locale:" in text or process.poll() is not None:
                        break
                    time.sleep(0.02)
                self.assertIn("Editor locale:", text)
                address = text.split("Editor locale: ", 1)[1].splitlines()[0]
                with urlopen(address + "/api/state") as response:
                    self.assertEqual(json.load(response)["project"]["source_sha256"], self.source_hash)
            finally:
                process.terminate()
                process.wait(timeout=5)

    def test_http_restricts_mutations_and_does_not_expose_filesystem(self):
        with make_server(self.session) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/api/state") as response:
                    state = json.load(response)
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base + "/api/state", headers={"Host": "example.com"}))
                self.assertEqual(error.exception.code, 403)
                request = Request(base + "/api/save", data=json.dumps(self.project).encode(),
                                  headers={"Content-Type": "application/json"})
                with self.assertRaises(HTTPError) as error:
                    urlopen(request)
                self.assertEqual(error.exception.code, 403)
                request.add_header("X-Sprite-Token", state["token"])
                request.add_header("Origin", "https://example.com")
                with self.assertRaises(HTTPError) as error:
                    urlopen(request)
                self.assertEqual(error.exception.code, 403)
                request.remove_header("Origin")
                with urlopen(request) as response:
                    self.assertEqual(response.status, 200)
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + "/../../sheet.png")
                self.assertEqual(error.exception.code, 404)
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    unittest.main()
