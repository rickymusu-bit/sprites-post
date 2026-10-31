"""Local-patch safety and replay invariants; candidate fixtures are NOT ImageGen."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sprite_postprocess as core
import sprite_edits
from sprite_editor_server import EditorSession
from sprite_patches.diagnosis import classify, require_local
from sprite_patches.materials import prepare, dump, verify
from sprite_patches.raster import replace
from sprite_patches.registration import register
from sprite_patches.verification import compare, review, CHECKS
from sprite_patches.workflow import import_candidate, run


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sheet = self.root / "source.png"
        image = Image.new("RGBA", (64, 32), (71, 17, 29, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((3, 3, 28, 28), fill=(100, 50, 20, 230))
        draw.rectangle((35, 3, 60, 28), fill=(50, 100, 20, 230))
        image.save(self.sheet)
        args = core.parser().parse_args([str(self.sheet), "--out", str(self.root / "out"), "--columns", "2", "--rows", "1", "--mode", "grid"])
        self.session = EditorSession(args)
        self.project = copy.deepcopy(self.session.project)
        self.project["align_body"] = False
        self.spec = {"frame": 1, "error_type": "anatomy_detail", "defect": "Synthetic test only",
            "subject": "fixture", "correction": "one simulated missing detail", "geometry": "square",
            "connections": "fixed", "preserve": "all other pixels, palette, light, material",
            "prompt": "TEST FIXTURE. No generator called.", "mask_polygon": [[5, 5], [14, 5], [14, 14], [5, 14]],
            "context_padding": 4, "references": [{"path": str(self.sheet), "role": "test-only canonical fixture", "revision": "fixture-v1", "approved": True}]}
        self.folder = self.root / "patch-001"

    def tearDown(self):
        self.tmp.cleanup()

    def request(self):
        prepare(self.session, self.project, self.spec, self.folder, self.root)
        return json.loads((self.folder / "request.json").read_text())

    def candidate(self):
        request = self.request()
        crop = Image.open(self.folder / "context.png").convert("RGBA")
        # Deliberately corrupt the WHOLE crop: reinsertion must limit it.
        crop.paste((240, 5, 180, 90), (0, 0, crop.width, crop.height))
        path = self.root / "simulated.png"
        crop.save(path)
        generation = self.root / "generation.json"
        dump(generation, {"service": "synthetic test fixture; NOT ImageGen", "output_provenance": "test-generated RGBA crop",
            "prompt_confirmed_exact": True, "supplied_files": ["original-frame.png", "context.png", "references/001.png"]})
        return import_candidate(self.folder, path, generation_path=generation)

    def test_classification_routes_all_errors_without_image_service(self):
        expected = {"position": "postprocess", "alignment": "postprocess", "scale": "postprocess", "color": "postprocess",
            "alpha": "postprocess", "rigid_rotation": "pivot", "missing_detail": "local_imagegen", "anatomy_detail": "local_imagegen",
            "hidden_surface": "local_imagegen_with_references", "impossible_pose": "new_keyframe", "perspective": "regenerate_frame"}
        for kind, route in expected.items():
            spec = dict(self.spec, error_type=kind)
            self.assertEqual(classify(spec)["route"], route)
            if not route.startswith("local_imagegen"):
                with self.assertRaises(ValueError):
                    require_local(spec)

    def test_prepare_keeps_mask_separate_from_larger_context_and_source(self):
        old = core.digest(self.sheet)
        request = self.request()
        self.assertEqual(request["status"], "prepared_not_sent")
        self.assertLess(Image.open(self.folder / "mask-crop.png").getbbox()[0], 6)
        mask = Image.open(self.folder / "mask-crop.png")
        self.assertEqual(mask.getpixel((0, 0)), 0)
        self.assertEqual((self.folder / "prompt.txt").read_text(), self.spec["prompt"])
        self.assertEqual(core.digest(self.sheet), old)
        self.assertEqual(core.digest(self.folder / "source-sheet.png"), old)
        verify(self.folder)

    def test_unapproved_reference_is_rejected_before_creating_request(self):
        self.spec["references"][0]["approved"] = False
        with self.assertRaisesRegex(ValueError, "riferimento"):
            self.request()
        self.assertFalse(self.folder.exists())

    def test_masks_outside_frame_rejected_without_clipping(self):
        self.spec["mask_polygon"][0] = [-5, 5]
        with self.assertRaisesRegex(ValueError, "fuori"):
            self.request()

    def test_external_import_exact_outside_rgba_and_reuses_editor_export(self):
        attempt = self.candidate()
        original = Image.open(self.folder / "original-frame.png").convert("RGBA")
        final = Image.open(attempt / "final-frame.png").convert("RGBA")
        mask = Image.open(self.folder / "mask-frame.png")
        report = compare(original, final, mask)
        self.assertGreater(report["inside_mask_changed_pixels"], 0)
        self.assertEqual(report["outside_mask_changed_pixels"], 0)
        self.assertEqual(final.getpixel((0, 0)), (71, 17, 29, 0))
        project = json.loads((attempt / "project-patched.json").read_text())
        preview = self.session.compute(project)
        self.assertEqual(preview.aligned[0].tobytes(), Image.open(attempt / "diagnostics/aligned/001.png").tobytes())
        self.assertEqual(json.loads((attempt / "verification.json").read_text())["status"], "pending_visual_review")
        verify(attempt)

    def test_feather_is_confined_inside_hard_mask_and_premultiplied(self):
        source = Image.new("RGBA", (11, 11), (200, 80, 10, 0))
        patch = Image.new("RGBA", (11, 11), (10, 150, 220, 255))
        mask = Image.new("L", (11, 11)); ImageDraw.Draw(mask).rectangle((3, 3, 7, 7), fill=255)
        result = replace(source, patch, mask, 2)
        self.assertEqual(result.getpixel((2, 5)), source.getpixel((2, 5)))
        self.assertEqual(result.getpixel((3, 5))[:3], patch.getpixel((3, 5))[:3])
        self.assertGreater(result.getpixel((3, 5))[3], 0)
        self.assertLess(result.getpixel((3, 5))[3], 255)
        compare(source, result, mask)

    def test_opaque_weight_replaces_alpha_zero_without_ghost_pixels(self):
        source = Image.new("RGBA", (1, 1), (20, 30, 40, 255))
        patch = Image.new("RGBA", (1, 1), (70, 80, 90, 0))
        self.assertEqual(replace(source, patch, Image.new("L", (1, 1), 255)).tobytes(), patch.tobytes())

    def test_stale_prior_edits_block_patch_replay(self):
        attempt = self.candidate()
        project = json.loads((attempt / "project-patched.json").read_text())
        project["frames"][0]["edits"].insert(0, {"type": "erase", "points": [[8, 8]], "radius": 1})
        with self.assertRaisesRegex(ValueError, "Snapshot"):
            self.session.compute(project)

    def test_disabled_patch_restores_source_exactly(self):
        attempt = self.candidate()
        project = json.loads((attempt / "project-patched.json").read_text())
        project["frames"][0]["edits"][0]["enabled"] = False
        a = self.session.compute(project)
        b = self.session.compute(self.project)
        self.assertEqual(a.aligned[0].tobytes(), b.aligned[0].tobytes())

    def test_request_tampering_blocks_import(self):
        self.candidate()
        (self.folder / "prompt.txt").write_text("tampered")
        with self.assertRaisesRegex(ValueError, "modificato"):
            verify(self.folder)

    def test_repeatable_replay_after_relocating_bundle(self):
        attempt = self.candidate()
        moved = self.root / "relocated"
        moved.mkdir()
        shutil.move(str(self.folder), moved / self.folder.name)
        new_attempt = moved / attempt.name
        shutil.move(str(attempt), new_attempt)
        self.session.args.patch_replay = new_attempt
        replayed = run(self.session.args)
        self.assertEqual(core.digest(new_attempt / "final-frame.png"), core.digest(replayed / "final-frame.png"))
        self.assertEqual(core.digest(new_attempt / "diagnostics/aligned.gif"), core.digest(replayed / "diagnostics/aligned.gif"))

    def test_explicit_landmark_registration_translation_and_rotation(self):
        candidate = Image.new("RGBA", (20, 20)); candidate.putpixel((5, 5), (255, 20, 30, 255))
        mask = Image.new("L", (20, 20)); mask.putpixel((7, 5), 255)
        output, report = register(candidate, mask, {"landmarks": [{"generated": [5, 5], "target": [7, 5]}], "nearest": True})
        self.assertEqual(output.getpixel((7, 5)), (255, 20, 30, 255))
        self.assertEqual(report["max_residual_px"], 0)
        _, report = register(candidate, Image.new("L", (20, 20)), {"allow_rotation": True, "landmarks": [
            {"generated": [5, 5], "target": [10, 5]}, {"generated": [10, 5], "target": [10, 10]}]})
        self.assertAlmostEqual(report["matrix"][3], 1)

    def test_transformed_crop_must_cover_mask(self):
        with self.assertRaisesRegex(ValueError, "copre"):
            register(Image.new("RGBA", (20, 20)), Image.new("L", (20, 20), 255), {"landmarks": [{"generated": [0, 0], "target": [2, 0]}]})

    def test_dimension_mismatch_and_false_prompt_logs_are_rejected(self):
        self.request()
        candidate = self.root / "bad.png"; Image.new("RGBA", (5, 5)).save(candidate)
        generation = self.root / "generation.json"
        dump(generation, {"prompt_confirmed_exact": False})
        with self.assertRaisesRegex(ValueError, "prompt_confirmed"):
            import_candidate(self.folder, candidate, generation_path=generation)
        dump(generation, {"prompt_confirmed_exact": True, "supplied_files": ["original-frame.png", "context.png", "references/001.png"],
            "service": "fixture", "output_provenance": "fixture"})
        with self.assertRaisesRegex(ValueError, "Dimensioni"):
            import_candidate(self.folder, candidate, generation_path=generation)
        self.assertFalse(list(self.root.glob("patch-001-attempt-*")))

    def test_visual_approval_requires_every_check_and_evidence_rejection_is_append_only(self):
        attempt = self.candidate()
        with self.assertRaisesRegex(ValueError, "controlli"):
            review(attempt, {"status": "approved", "reviewer": "fixture", "notes": "test"})
        decision = {"status": "rejected", "reviewer": "fixture", "notes": "simulated detail fails visual quality"}
        self.assertEqual(review(attempt, decision)["status"], "rejected")
        self.assertEqual(review(attempt, decision)["review"], "review-002.json")
        verify(attempt)
        self.assertEqual(core.digest(self.sheet), core.digest(self.folder / "source-sheet.png"))

    def test_different_size_requires_explicit_uniform_mapping(self):
        candidate = Image.new("RGBA", (80, 40), (200, 20, 30, 150))
        mask = Image.new("L", (40, 20), 255)
        with self.assertRaisesRegex(ValueError, "Dimensioni"):
            register(candidate, mask, {})
        output, report = register(candidate, mask, {"input_mapping": {"mode": "fit"}, "nearest": True})
        self.assertEqual(output.size, mask.size)
        self.assertEqual(report["matrix"], [0.5, 0.0, 0.0, 0.0, 0.5, 0.0])
        self.assertEqual(output.getpixel((10, 10)), (200, 20, 30, 150))

    def test_different_aspect_ratio_never_stretches_and_rejects_missing_coverage(self):
        candidate = Image.new("RGBA", (80, 40), (50, 80, 100, 255))
        mask = Image.new("L", (40, 40)); ImageDraw.Draw(mask).rectangle((5, 15, 30, 25), fill=255)
        output, report = register(candidate, mask, {"input_mapping": {"mode": "fit"}})
        self.assertEqual(report["matrix"], [0.5, 0.0, 0.0, 0.0, 0.5, 10.0])
        self.assertEqual(output.size, (40, 40))
        with self.assertRaisesRegex(ValueError, "copre"):
            register(candidate, Image.new("L", (40, 40), 255), {"input_mapping": {"mode": "fit"}})

    def test_native_landmarks_fit_different_size_without_implicit_resize(self):
        candidate = Image.new("RGBA", (200, 100), (100, 60, 30, 255))
        mask = Image.new("L", (40, 20), 255)
        settings = {"allow_scale": True, "landmarks": [{"generated": [25, 25], "target": [5, 5]}, {"generated": [175, 25], "target": [35, 5]}]}
        output, report = register(candidate, mask, settings)
        self.assertEqual(output.size, mask.size)
        self.assertAlmostEqual(report["matrix"][0], 0.2)
        self.assertEqual(report["max_residual_px"], 0)
        self.assertEqual(report["mapping_mode"], "landmarks")

    def test_explicit_uniform_offset_and_invalid_mappings(self):
        candidate = Image.new("RGBA", (50, 50), (80, 20, 10, 255))
        mask = Image.new("L", (20, 20), 255)
        _, report = register(candidate, mask, {"input_mapping": {"mode": "uniform", "scale": 1, "offset": [-10, -10]}})
        self.assertEqual(report["matrix"], [1, 0, -10, 0, 1, -10])
        for mapping in ({"mode": "uniform", "scale": 0, "offset": [0,0]}, {"mode": "stretch"}, {"mode": "uniform", "scale": [1,2], "offset": [0,0]}):
            with self.assertRaises(ValueError):
                register(candidate, mask, {"input_mapping": mapping})

    def test_explicit_context_box_must_contain_mask(self):
        self.spec["context_box"] = [2, 2, 22, 22]
        request = self.request()
        self.assertEqual(request["crop_box"], [2, 2, 22, 22])
        with Image.open(self.folder / "context.png") as context:
            self.assertEqual(context.size, (20,20))

    def test_same_cli_dispatches_prepare_import_and_replay(self):
        spec_path = self.root / "spec.json"
        project_path = self.root / "project.json"
        dump(spec_path, self.spec)
        dump(project_path, self.project)
        base = [sys.executable, str(Path(core.__file__)), str(self.sheet), "--columns", "2", "--rows", "1",
                "--mode", "grid", "--out", str(self.root / "cli"), "--landmarks", str(project_path)]
        def command(*options):
            result = subprocess.run(base + list(options), capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.strip()
        diagnosed = json.loads(command("--patch-diagnose", str(spec_path)))
        self.assertEqual(diagnosed["route"], "local_imagegen")
        request = Path(command("--patch-prepare", str(spec_path)))
        candidate = self.root / "candidate.png"
        image = Image.open(request / "context.png").convert("RGBA")
        ImageDraw.Draw(image).rectangle((0, 0, image.width - 1, image.height - 1), fill=(210, 80, 15, 200))
        image.save(candidate)
        generation = self.root / "generation.json"
        dump(generation, {"service": "test fixture", "output_provenance": "synthetic test fixture, not ImageGen",
            "prompt_confirmed_exact": True, "supplied_files": ["original-frame.png", "context.png", "references/001.png"]})
        attempt = Path(command("--patch-import", str(request), "--patch-candidate", str(candidate), "--patch-generation", str(generation)))
        replay = Path(command("--patch-replay", str(attempt)))
        self.assertEqual(core.digest(attempt / "final-frame.png"), core.digest(replay / "final-frame.png"))

    def test_verifier_checks_hidden_rgb_and_all_channels(self):
        source = Image.new("RGBA", (2, 2), (1, 2, 3, 0)); result = source.copy()
        result.putpixel((1, 1), (2, 2, 3, 0))
        with self.assertRaisesRegex(ValueError, "fuori"):
            compare(source, result, Image.new("L", (2, 2)))


if __name__ == "__main__":
    unittest.main()
