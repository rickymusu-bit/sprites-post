"""Geometric and output regressions for the standalone sprite tool."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sprite_postprocess.py"
SPEC = importlib.util.spec_from_file_location("sprite_postprocess", SCRIPT)
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


class SpritePostprocessTests(unittest.TestCase):
    def test_components_cross_grid_boundaries_and_keep_faint_islands(self):
        sheet = Image.new("RGBA", (100, 50))
        draw = ImageDraw.Draw(sheet)
        draw.rectangle((5, 20, 55, 30), fill=(180, 20, 30, 255))
        draw.rectangle((60, 2, 90, 15), fill=(20, 180, 30, 255))
        sheet.putpixel((4, 19), (1, 2, 3, 3))
        sheet.putpixel((94, 8), (3, 4, 5, 1))
        sprites, report = TOOL.extract(sheet, 2, 1, min_area=100, threshold=8)
        self.assertEqual(len(sprites), 2)
        # All visible alpha is assigned once, including an isolated faint pixel.
        before = sum(sheet.getchannel("A").tobytes())
        after = sum(sum(s.image.getchannel("A").tobytes()) for s in sprites)
        self.assertEqual(before, after)
        self.assertEqual(sprites[0].image.getpixel((0, 0)), (1, 2, 3, 3))
        self.assertEqual(report["faint_pixels_assigned"], 2)

    def test_touching_poses_fail_instead_of_silently_losing_a_frame(self):
        image = Image.new("RGBA", (30, 20), "red")
        with self.assertRaisesRegex(ValueError, "Expected 2"):
            TOOL.extract(image, 2, 1)

    def test_uneven_grid_uses_every_source_pixel(self):
        sheet = Image.new("RGBA", (11, 7), (1, 2, 3, 100))
        sprites, _ = TOOL.extract(sheet, 3, 2, mode="grid")
        self.assertEqual(sum(s.image.width * s.image.height for s in sprites), 77)

    def test_weighted_uniform_fit_and_preserved_intentional_motion(self):
        source = [(0, 0), (10, 0), (0, 10), (10, 10)]
        target = [(2 * x + 7, 2 * y - 3) for x, y in source]
        transform, report = TOOL.fit_landmarks(source, target, [1, 2, 1, 2], True)
        for value, expected in zip(transform, (2, 7, -3)):
            self.assertAlmostEqual(value, expected)
        self.assertAlmostEqual(report["weighted_rms_px"], 0)
        self.assertFalse(report["provisional"])
        sprite = TOOL.Sprite(Image.new("RGBA", (30, 30), "red"), (50, 50, 80, 80))
        points = {"shoulder": [55, 55], "chest": [60, 55], "pelvis": [60, 65]}
        config = {"frames": [{"points": points}, {"points": points, "motion": [3, -4]}]}
        transforms, _ = TOOL.landmark_transforms([sprite, sprite], [(1, 10, 10)] * 2, config, 0, False)
        self.assertEqual(transforms[1], (1, 13, 6))

    def test_single_anchor_is_provisional_and_degenerate_scale_fails(self):
        _, report = TOOL.fit_landmarks([(1, 2)], [(3, 5)], [1])
        self.assertTrue(report["provisional"])
        with self.assertRaisesRegex(ValueError, "distinct"):
            TOOL.fit_landmarks([(1, 2)], [(3, 5)], [1], True)

    def test_roi_follows_body_while_tail_changes(self):
        reference = Image.new("RGBA", (100, 80))
        draw = ImageDraw.Draw(reference)
        draw.rectangle((30, 20, 59, 49), fill="#9b3322")
        draw.rectangle((35, 25, 41, 33), fill="#f3bb33")
        draw.rectangle((50, 37, 54, 46), fill="#220011")
        target = Image.new("RGBA", reference.size)
        target.paste(reference, (7, -5))
        ImageDraw.Draw(target).rectangle((5, 55, 80, 65), fill="cyan")
        dx, dy, score = TOOL.match_region(reference, target, (30, 20, 30, 30), 12)
        self.assertEqual((dx, dy), (-7, 5))
        self.assertEqual(score, 0)

    def test_lossless_translation_and_clipping_guard(self):
        image = Image.new("RGBA", (20, 20))
        image.putpixel((3, 7), (155, 44, 22, 7))
        sprite = TOOL.Sprite(image, (0, 0, 20, 20))
        frames, transforms = TOOL.render([sprite], [(1, -200, 100)], 2)
        _, x, y = transforms[0]
        self.assertEqual(frames[0].getpixel((3 + int(x), 7 + int(y))), (155, 44, 22, 7))
        with self.assertRaisesRegex(ValueError, "would clip"):
            TOOL.render([sprite], [(1, 0, 0)], 2, (2, 2))

    def test_onion_wraps_last_to_first(self):
        frames = [Image.new("RGBA", (10, 10)) for _ in range(3)]
        frames[0].putpixel((1, 1), (100, 90, 80, 255))
        frames[1].putpixel((2, 2), (100, 90, 80, 255))
        frames[2].putpixel((3, 3), (100, 90, 80, 255))
        onions = TOOL.onion_frames(frames, 0.5)
        self.assertEqual(onions[0].getpixel((3, 3)), (255, 80, 80, 128))
        self.assertEqual(onions[0].getpixel((2, 2)), (53, 224, 255, 128))
        self.assertEqual(onions[0].getpixel((1, 1)), (100, 90, 80, 255))

    def test_cli_outputs_manifest_palette_gifs_and_protects_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sheet.png"
            image = Image.new("RGBA", (80, 40))
            draw = ImageDraw.Draw(image)
            draw.rectangle((5, 5, 20, 25), fill="red")
            draw.rectangle((45, 10, 70, 30), fill="green")
            image.save(source)
            before = TOOL.digest(source)
            args = TOOL.parser().parse_args([str(source), "--columns", "2", "--rows", "1", "--out", str(root / "out")])
            report = TOOL.run(args)
            self.assertEqual(TOOL.digest(source), before)
            self.assertEqual(report["source_sha256"], before)
            self.assertEqual(report["gifs"]["aligned.gif"]["total_duration_ms"], 200)
            self.assertEqual(len(report["frames"]), 2)
            self.assertEqual(len(list((root / "out/onion").glob("*.png"))), 2)
            with Image.open(root / "out/atlas.png") as atlas:
                self.assertEqual(atlas.width, report["canvas"][0] * 2)
                self.assertIn(0, atlas.getchannel("A").getextrema())
            manifest = json.loads((root / "out/manifest.json").read_text())
            self.assertIn("layout-only", manifest["method"])
            with self.assertRaisesRegex(ValueError, "new or empty"):
                TOOL.run(args)

    def test_gif_duplicate_hold_keeps_total_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            a = Image.new("RGBA", (10, 10), "red")
            b = Image.new("RGBA", (10, 10), "blue")
            report = TOOL.save_gif([a, a, b], Path(directory) / "hold.gif", 120)
            self.assertEqual(report["total_duration_ms"], 360)

    def test_landmark_manifest_anchors_and_stale_annotations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sheet.png"
            image = Image.new("RGBA", (80, 40))
            draw = ImageDraw.Draw(image)
            draw.rectangle((5, 5, 25, 30), fill="red")
            draw.rectangle((45, 5, 65, 30), fill="blue")
            image.save(source)
            points = {"shoulder": [10, 10], "chest": [20, 10], "pelvis": [15, 25]}
            shifted = {name: [xy[0] + 40, xy[1]] for name, xy in points.items()}
            config = {"source_sha256": TOOL.digest(source), "frames": [
                {"points": points, "anchors": {"pivot": [15, 15]}},
                {"points": shifted, "anchors": {"pivot": [55, 15]}, "motion": [2, -3]}]}
            landmarks = root / "points.json"
            landmarks.write_text(json.dumps(config))
            args = TOOL.parser().parse_args([str(source), "--columns", "2", "--rows", "1",
                "--landmarks", str(landmarks), "--out", str(root / "aligned")])
            result = TOOL.run(args)
            a, b = [frame["transformed_anchors"]["pivot"] for frame in result["frames"]]
            self.assertEqual([b[0] - a[0], b[1] - a[1]], [2, -3])
            self.assertFalse(result["frames"][1]["alignment_check"]["provisional"])
            config["source_sha256"] = "wrong-source"
            landmarks.write_text(json.dumps(config))
            args.out = root / "stale"
            with self.assertRaisesRegex(ValueError, "source hash"):
                TOOL.run(args)
            self.assertFalse(args.out.exists())

    def test_faint_bridge_does_not_join_poses_or_lose_source_pixels(self):
        image = Image.new("RGBA", (40, 20))
        draw = ImageDraw.Draw(image)
        draw.rectangle((2, 2, 10, 15), fill="red")
        draw.rectangle((25, 2, 35, 15), fill="blue")
        draw.line((11, 7, 24, 7), fill=(200, 10, 10, 1))
        sprites, _ = TOOL.extract(image, 2, 1, min_area=20)
        self.assertEqual(len(sprites), 2)
        self.assertEqual(sum(image.getchannel("A").tobytes()),
                         sum(sum(s.image.getchannel("A").tobytes()) for s in sprites))

    def test_palette_png_transparency_and_invalid_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "indexed.png"
            image = Image.new("P", (20, 20), 0)
            image.putpalette([0, 0, 0, 255, 0, 0] + [0, 0, 0] * 254)
            ImageDraw.Draw(image).rectangle((3, 3, 16, 16), fill=1)
            image.save(source, transparency=0)
            args = TOOL.parser().parse_args([str(source), "--columns", "1", "--rows", "1", "--out", str(root / "out")])
            self.assertEqual(len(TOOL.run(args)["frames"]), 1)
            args.out = root / "bad-time"
            args.duration = 15
            with self.assertRaisesRegex(ValueError, "duration"):
                TOOL.run(args)
            self.assertFalse(args.out.exists())


if __name__ == "__main__":
    unittest.main()
