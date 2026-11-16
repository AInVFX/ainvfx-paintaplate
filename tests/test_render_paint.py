"""A paint's verdict in the GPU report: inside the paint matte, how much of the export differs from the plate on the last
frames, against the first; and a paint that the shot still shows while its matte shrank away, lost from the composite."""
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gpu_matrix  # noqa: E402


def picture(path, square=None, ground=100, ink=250, size=(96, 64)):
    """One image of a grey ground, with a square of another grey on it."""
    from PIL import Image, ImageDraw
    os.makedirs(os.path.dirname(path), exist_ok=True)
    image = Image.new("RGB", size, (ground,) * 3)
    if square:
        ImageDraw.Draw(image).rectangle(square, fill=(ink,) * 3)
    image.save(path)
    return path


class Paint(unittest.TestCase):
    SQUARE = (30, 20, 60, 44)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="paint_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def verdict(self, lost_from=12, matte_until=12, shot_until=None):
        """12 frames numbered 480 to 491: the paint, a light square, holds until `lost_from`; its matte until `matte_until`;
        with `shot_until`, the full-size shot shows it until then, over the plate as its base."""
        plate, matte = os.path.join(self.tmp, "plate"), []
        with zipfile.ZipFile(os.path.join(self.tmp, "export.zip"), "w") as z:
            for k in range(12):
                picture(os.path.join(plate, f"plate.{480 + k:04d}.png"))
                matte.append(picture(os.path.join(self.tmp, "matte", f"m.{k + 1:04d}.png"), self.SQUARE if k < matte_until else None, ground=0, ink=255))
                z.write(picture(os.path.join(self.tmp, "made", f"{k}.png"), self.SQUARE if k < lost_from else None), f"export/plate.{480 + k:04d}.png")
        shot = None if shot_until is None else [picture(os.path.join(self.tmp, "shot", f"s.{k + 1:04d}.png"), self.SQUARE if k < shot_until else None)
                                                for k in range(12)]
        return gpu_matrix.paint_verdict(self.tmp, plate, matte, shot)

    def test_a_paint_that_stays_holds(self):
        made = self.verdict()
        self.assertIs(made["held"], True)
        self.assertEqual(made["text"], "Paint, frames 491 to 491: held (100% of its matte changed, against 100% on frame 480).")

    def test_a_paint_gone_from_the_shot_while_its_matte_stays_is_lost_and_fails_the_case(self):
        made = self.verdict(lost_from=6)
        self.assertIs(made["held"], False)
        self.assertEqual(made["text"], "Paint, frames 491 to 491: lost (0% of its matte changed, against 100% on frame 480).")
        self.assertEqual(gpu_matrix.paint_result(True, "", made), (False, made["text"] + " The case fails: the paint did not hold. Check its picture on the sheet."))
        self.assertEqual(gpu_matrix.paint_result(False, "an earlier fault", made), (False, "an earlier fault"))

    def test_a_paint_whose_matte_leaves_early_has_no_verdict(self):
        made = self.verdict(lost_from=6, matte_until=5)
        self.assertIsNone(made["held"])
        self.assertEqual(made["text"], "Paint: no verdict. Its matte is empty from frame 485.")
        self.assertEqual(gpu_matrix.paint_result(True, "", made), (True, ""))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "paint_files")))


    def test_a_paint_that_the_shot_keeps_while_its_matte_shrinks_away_is_lost_from_the_composite(self):
        made = self.verdict(lost_from=6, matte_until=6, shot_until=12)
        self.assertIs(made["held"], False)
        self.assertEqual(made["text"], "Paint, frames 491 to 491: lost from the composite (the shot shows it on 12.5% of the frame, "
                                       "the paint matte on 0.0%, against 12.6% on frame 480).")
        self.assertFalse(gpu_matrix.paint_result(True, "", made)[0])

    def test_a_paint_that_leaves_the_shot_with_its_matte_is_not_lost_from_the_composite(self):
        made = self.verdict(lost_from=5, matte_until=5, shot_until=5)
        self.assertIsNone(made["held"])
        self.assertEqual(made["text"], "Paint: no verdict. Its matte is empty from frame 485.")

    def test_a_paint_the_shot_keeps_inside_its_held_matte_holds(self):
        self.assertIs(self.verdict(shot_until=12)["held"], True)


if __name__ == "__main__":
    unittest.main()
