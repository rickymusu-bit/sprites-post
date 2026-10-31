"""Raster/geometry regressions for reproducible local corrections, no generator."""

from io import BytesIO
import copy
from pathlib import Path
import sys
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sprite_postprocess as core
import sprite_edits as edits


def local_part(**options):
    op = {"type": "part", "mask": [[100, 200], [116, 200], [116, 216], [100, 216]],
          "pivot": [108, 208], "pivot_confirmed": True, "translate": [0, 0],
          "rotation_deg": 0, "scale": 1, "cut": True}
    op.update(options)
    return op


class RasterEditTests(unittest.TestCase):
    def setUp(self):
        image = Image.new("RGBA", (16, 16))
        image.putpixel((3, 3), (230, 30, 40, 255))
        image.putpixel((4, 3), (100, 80, 60, 128))
        image.putpixel((12, 12), (30, 210, 80, 255))
        self.source = core.Sprite(image, (100, 200, 116, 216))
        self.original_bytes = image.tobytes()

    def apply(self, operations, nearest=True, points=None):
        images, reports = edits.apply_all([self.source], [operations], nearest, [points or {}])
        self.assertEqual(self.source.image.tobytes(), self.original_bytes)
        return images[0], reports[0]

    def sample(self, sprite, x, y):
        return sprite.image.getpixel((x - sprite.box[0], y - sprite.box[1]))

    def test_identity_cut_keeps_original_rgba_and_hidden_colors(self):
        for nearest in [True, False]:
            image, _ = self.apply([local_part()], nearest)
            box = (100 - image.box[0], 200 - image.box[1], 116 - image.box[0], 216 - image.box[1])
            self.assertEqual(image.image.crop(box).tobytes(), self.original_bytes)

    def test_integer_part_translation_is_pixel_exact_and_only_changes_selected_pixels(self):
        mask = [[102, 202], [105, 202], [105, 204], [102, 204]]
        image, report = self.apply([local_part(mask=mask, translate=[5, 0])])
        self.assertEqual(self.sample(image, 108, 203), (230, 30, 40, 255))
        self.assertEqual(self.sample(image, 109, 203), (100, 80, 60, 128))
        self.assertEqual(self.sample(image, 103, 203)[3], 0)
        self.assertEqual(self.sample(image, 112, 212), (30, 210, 80, 255))
        self.assertEqual(report[0]["matrix"], [1, 0, 0, 1, 5, 0])

    def test_quarter_rotation_matches_lossless_pixel_transpose(self):
        image, _ = self.apply([local_part(rotation_deg=90)])
        self.assertEqual(image.image.tobytes(), self.source.image.transpose(Image.Transpose.ROTATE_270).tobytes())

    def test_rotated_tip_expands_canvas_instead_of_clipping(self):
        image, _ = self.apply([local_part(pivot=[100, 200], rotation_deg=90)])
        self.assertLess(image.box[0], self.source.box[0])
        self.assertEqual(sum(image.image.getchannel("A").tobytes()), sum(self.source.image.getchannel("A").tobytes()))

    def test_pivot_confirmation_is_required_for_rotation(self):
        with self.assertRaisesRegex(ValueError, "pivot"):
            self.apply([local_part(pivot_confirmed=False, rotation_deg=15)])

    def test_moving_registration_landmark_is_rejected_but_fixed_joint_allowed(self):
        points = {"joint": [103, 203]}
        with self.assertRaisesRegex(ValueError, "allineamento"):
            self.apply([local_part(translate=[1, 0])], points=points)
        image, _ = self.apply([local_part(pivot=[103, 203], rotation_deg=90)], points=points)
        self.assertIsNotNone(image.image.getchannel("A").getbbox())

    def test_single_pixel_paint_and_erase_are_replayable(self):
        operations = [{"type": "paint", "points": [[108, 208]], "radius": .5, "color": [10, 20, 250, 255]}]
        image, _ = self.apply(operations)
        self.assertEqual(self.sample(image, 108, 208), (10, 20, 250, 255))
        self.assertEqual(self.sample(image, 107, 208)[3], 0)
        operations.append({"type": "erase", "points": [[103, 203]], "radius": .5})
        erased, _ = self.apply(operations)
        self.assertEqual(self.sample(erased, 103, 203)[3], 0)
        self.assertEqual(self.sample(erased, 108, 208), (10, 20, 250, 255))
        repeated, _ = self.apply(copy.deepcopy(operations))
        a, b = BytesIO(), BytesIO()
        erased.image.save(a, format="PNG")
        repeated.image.save(b, format="PNG")
        self.assertEqual(a.getvalue(), b.getvalue())

    def test_clone_reads_immutable_original_not_a_previous_paint(self):
        operations = [{"type": "paint", "points": [[103, 203]], "radius": .5, "color": [10, 20, 250, 255]},
                      {"type": "clone", "points": [[108, 208]], "radius": .5, "source_frame": 0, "source_point": [103, 203]}]
        image, _ = self.apply(operations)
        self.assertEqual(self.sample(image, 103, 203), (10, 20, 250, 255))
        self.assertEqual(self.sample(image, 108, 208), (230, 30, 40, 255))

    def test_identity_source_part_restores_its_original_pixels_over_prior_paint(self):
        operations = [{"type": "paint", "points": [[103, 203]], "radius": .5, "color": [10, 20, 250, 255]},local_part()]
        image, _ = self.apply(operations)
        self.assertEqual(self.sample(image, 103, 203), (230, 30, 40, 255))

    def test_functional_anchor_follows_moved_part(self):
        operation = local_part(translate=[4, 2])
        image, _ = self.apply([operation])
        anchors = edits.map_anchors(self.source, image, [operation], {"mouth": [103, 203]})
        self.assertEqual(anchors["mouth"]["xy"], [107, 205])
        self.assertTrue(anchors["mouth"]["visible"])

    def test_clone_can_use_a_declared_second_source_pose(self):
        second = core.Sprite(Image.new("RGBA", (16, 16), (240, 100, 10, 255)), (500, 600, 516, 616))
        operations = [{"type": "clone", "points": [[108, 208]], "radius": .5, "source_frame": 1, "source_point": [505, 605]}]
        images, _ = edits.apply_all([self.source, second], [operations, []])
        self.assertEqual(self.sample(images[0], 108, 208), (240, 100, 10, 255))

    def test_painting_beyond_original_border_adds_canvas_and_preserves_source(self):
        image, _ = self.apply([{"type": "paint", "points": [[120, 208]], "radius": 1, "color": [30, 20, 10, 255]}])
        self.assertGreater(image.box[2], self.source.box[2])
        self.assertEqual(self.sample(image, 120, 208), (30, 20, 10, 255))

    def test_disabled_operation_changes_nothing(self):
        image, report = self.apply([local_part(enabled=False, pivot_confirmed=False, rotation_deg=15)])
        self.assertEqual(image.image.tobytes(), self.original_bytes)
        self.assertFalse(report[0]["enabled"])

    def test_invalid_recipes_and_excessive_canvas_are_rejected(self):
        cases = [local_part(mask=[[0, 0], [1, 1], [2, 2]]), local_part(scale=-1),
                 {"type": "paint", "points": [[float("nan"), 1]], "radius": 1, "color": [0, 0, 0, 255]},
                 {"type": "clone", "points": [[1, 1]], "radius": 1, "source_frame": 9, "source_point": [1, 1]}]
        for operation in cases:
            with self.assertRaises(ValueError):
                self.apply([operation])
        with self.assertRaisesRegex(ValueError, "troppo grande"):
            self.apply([local_part(translate=[50_000, 0])])


if __name__ == "__main__":
    unittest.main()
