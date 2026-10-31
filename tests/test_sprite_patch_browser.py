"""Browser adapter invariants using synthetic candidates, never ImageGen output."""
import copy
from io import BytesIO
import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import test_sprite_patches as fixture
from sprite_editor_server import EditorSession, make_server
from sprite_patches.raster import encode
from sprite_patches.materials import verify
from sprite_patches.verification import CHECKS, latest_review


class BrowserPatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.PatchTests()
        self.fixture.setUp()
        self.session = self.fixture.session
        self.project = self.fixture.project
        self.manager = self.session.patches
        self.payload = {"project": self.project, "spec": self.fixture.spec,
            "references_approved": True, "use_source_reference": True, "references": []}

    def tearDown(self):
        self.fixture.tearDown()

    def prepare(self):
        return self.manager.prepare(self.payload)

    def candidate(self):
        request = self.prepare()
        context = Image.open(self.manager.root / request["id"] / "context.png").convert("RGBA")
        image = Image.new("RGBA", (context.width * 4, context.height * 4), (200, 30, 80, 100))
        upload = self.manager.upload({"request_id": request["id"], "png": encode(image)})
        generation = {"service": "SYNTHETIC unit test", "output_provenance": "Pillow fixture, not ImageGen",
            "prompt_confirmed_exact": True, "supplied_files": request["required_files"]}
        return request, upload, generation

    def apply(self):
        request, upload, generation = self.candidate()
        result = self.manager.apply({"project": self.project, "request_id": request["id"], "upload_id": upload["id"],
            "registration": {"input_mapping": {"mode": "fit"}}, "generation": generation})
        return result

    def test_prepare_exports_only_confirmed_references_and_downloadable_archive(self):
        self.payload["references_approved"] = False
        with self.assertRaisesRegex(ValueError, "Conferma"):
            self.prepare()
        self.payload["references_approved"] = True
        self.payload["spec"] = dict(self.fixture.spec, references=[{"path": "/etc/passwd"}])
        request = self.prepare()
        data, kind = self.manager.resource(request["archive_url"])
        self.assertEqual(kind, "application/zip")
        with zipfile.ZipFile(BytesIO(data)) as archive:
            self.assertIn("mask-crop.png", archive.namelist())
            refs = json.loads(archive.read("request.json"))["references"]
            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0]["original_path"], str(self.fixture.sheet.resolve()))

    def test_preview_does_not_apply_and_apply_matches_preview_exactly(self):
        request, upload, generation = self.candidate()
        before = copy.deepcopy(self.project)
        payload = {"request_id": request["id"], "upload_id": upload["id"], "registration": {"input_mapping": {"mode": "fit"}}}
        preview = self.manager.registration_preview(payload)
        self.assertEqual(preview["verification"]["outside_mask_changed_pixels"], 0)
        self.assertEqual(self.project, before)
        self.assertEqual(self.manager.listing()["attempts"], [])
        result = self.manager.apply(dict(payload, project=self.project, generation=generation))
        self.assertTrue(result["project"]["frames"][0]["edits"])
        op = result["project"]["frames"][0]["edits"][-1]
        self.assertEqual(op["transform"]["candidate_size"], upload["size"])
        self.assertEqual(op["transform"]["mapping_mode"], "fit")
        self.assertEqual(result["attempt"]["status"], "pending_visual_review")

    def test_changed_project_blocks_import_and_resume_restores_request(self):
        request, upload, generation = self.candidate()
        project = copy.deepcopy(self.project)
        project["frames"][1]["edits"].append({"type": "erase", "points": [[40, 8]], "radius": 1})
        with self.assertRaisesRegex(ValueError, "cambiato"):
            self.manager.apply({"project": project, "request_id": request["id"], "upload_id": upload["id"],
                "registration": {"input_mapping": {"mode": "fit"}}, "generation": generation})
        resumed = self.manager.resume({"request_id": request["id"]})
        self.assertEqual(resumed["project"], self.session.validate(self.project))

    def test_approval_is_bound_to_candidate_and_persists_after_restart(self):
        result = self.apply()
        decision = {"status": "approved", "reviewer": "synthetic fixture", "notes": "Unit test of status binding only",
            "checks": {key: True for key in CHECKS}, "evidence": ["synthetic unit test, not artistic acceptance"]}
        response = self.manager.decide({"project": result["project"], "attempt_id": result["attempt"]["id"], "decision": decision})
        self.assertEqual(response["attempt"]["status"], "approved")
        op = result["project"]["frames"][0]["edits"][-1]
        restarted = EditorSession(self.session.args)
        self.assertEqual(restarted.patches.status_for(op)["status"], "approved")
        altered = copy.deepcopy(op); altered["feather_px"] = 2
        self.assertEqual(restarted.patches.status_for(altered)["status"], "unavailable")
        preview = self.session.compute(result["project"])
        self.assertEqual(self.session.describe(preview, 0)["frames"][0]["edit_operations"][-1]["review"]["status"], "approved")
        verify(self.manager.root / result["attempt"]["id"])

    def test_rejection_restores_previous_frame_and_preserves_other_frame_edits(self):
        result = self.apply()
        project = result["project"]
        project["frames"][0]["edits"].append({"type": "erase", "points": [[8, 8]], "radius": 1})
        project["frames"][1]["edits"].append({"type": "erase", "points": [[40, 8]], "radius": 1})
        decision = {"status": "rejected", "reviewer": "fixture", "notes": "Reject synthetic output"}
        response = self.manager.decide({"project": project, "attempt_id": result["attempt"]["id"], "decision": decision})
        self.assertEqual(response["project"]["frames"][0]["edits"], [])
        self.assertEqual(len(response["project"]["frames"][1]["edits"]), 1)
        self.assertEqual(response["attempt"]["status"], "rejected")
        self.assertTrue((self.manager.root / result["attempt"]["id"] / "generated.png").exists())

    def test_two_attempts_have_distinct_recipe_ids(self):
        request, upload, generation = self.candidate()
        payload = {"project": self.project, "request_id": request["id"], "upload_id": upload["id"],
            "registration": {"input_mapping": {"mode": "fit"}}, "generation": generation}
        a, b = self.manager.apply(payload), self.manager.apply(payload)
        self.assertNotEqual(a["project"]["frames"][0]["edits"][-1]["id"], b["project"]["frames"][0]["edits"][-1]["id"])

    def test_replay_preserves_recipe_identity_without_creating_a_second_review_target(self):
        from sprite_patches.workflow import run
        result = self.apply()
        self.session.args.patch_replay = self.manager.root / result["attempt"]["id"]
        replayed = run(self.session.args)
        self.assertTrue(replayed.is_dir())
        self.assertEqual(len(self.manager.listing()["attempts"]), 1)
        with self.assertRaisesRegex(ValueError, "replay"):
            self.manager.decide({"project": result["project"], "attempt_id": replayed.name,
                "decision": {"status": "rejected", "reviewer": "fixture", "notes": "test"}})

    def test_http_requires_token_for_upload_and_constrains_resource_paths(self):
        request = self.prepare()
        with make_server(self.session) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with self.assertRaises(HTTPError) as denied:
                    urlopen(Request(base + "/api/patch/upload", data=b"{}", headers={"Content-Type": "application/json"}))
                self.assertEqual(denied.exception.code, 403)
                for path in ("/api/patch/file/../../AGENTS.md", "/api/patch/upload/not-a-hash.png", f"/api/patch/file/{request['id']}/../../AGENTS.md"):
                    with self.assertRaises(HTTPError) as denied:
                        urlopen(base + path)
                    self.assertEqual(denied.exception.code, 404)
                data = json.loads(urlopen(base + "/api/patch/list").read())
                self.assertEqual(len(data["requests"]), 1)
            finally:
                server.shutdown(); thread.join()

    def test_request_without_global_landmarks_is_blocked_until_alignment_disabled(self):
        self.payload["project"] = copy.deepcopy(self.project)
        self.payload["project"]["align_body"] = True
        with self.assertRaisesRegex(ValueError, "allineamento"):
            self.prepare()
        self.assertFalse(self.manager.root.exists())


if __name__ == "__main__":
    unittest.main()
