"""Follow Matte for a paint made over a Clean edit. Inside the Clean matte the shot shows the cleaned place and the
plate still shows the object, so they differ on every frame: there a change joins the paint's matte only where it
touches the tracker's mask, within a zone of it."""
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mathops  # noqa: E402

H, W, N = 64, 128, 12
CAR = (slice(28, 52), slice(70, 104))  # the object that the Clean edit removed, as the plate shows it


def scene(rows, cols):
    """A plate with an object, a shot where it is cleaned and a square is painted at (rows, cols), the paint zone
    that reaches the cleaned place, the tracker's masks on the square, and the Clean matte."""
    plate = np.clip(0.45 + 0.05 * np.random.default_rng(3).standard_normal((H, W, 3)), 0, 1).astype(np.float32)
    shot = plate.copy()
    plate[CAR] = 0.9
    shot[rows, cols] = 0.05
    sam = np.zeros((N, H, W), np.float32)
    sam[:, rows, cols] = 1
    zone = np.zeros((1, H, W), np.float32)
    zone[0, 20:58, 36:76] = 1
    clean = np.zeros((N, H, W), np.float32)
    clean[:, 26:54, 68:106] = 1
    return dict(masks=sam, n=N, first=zone, shot=np.repeat(shot[None], N, 0), base=np.repeat(plate[None], N, 0)), clean


class PaintOverClean(unittest.TestCase):
    def test_cleaned_place_stays_out(self):
        args, clean = scene(slice(34, 42), slice(44, 54))
        before, _ = mathops.follow_matte(**args)
        after, summary = mathops.follow_matte(**args, erased=clean)
        self.assertGreater(int((before[-1][CAR] > 0.5).sum()), 200)  # through the paint zone, the cleaned place joined
        self.assertEqual(int((after[:, CAR[0], CAR[1]] > 0.5).sum()), 0)
        self.assertTrue((after[:, 34:42, 44:54] > 0.5).all())
        self.assertIn("Removed: areas the shot changed inside the Clean matte, on ", summary)

    def test_change_that_touches_the_sam_mask_joins_within_a_zone(self):
        args, clean = scene(slice(34, 44), slice(60, 70))
        after, _ = mathops.follow_matte(**args, erased=clean)
        self.assertGreater(int((after[0, 34:44, 70:76] > 0.5).sum()), 0)  # beside the tracker's mask
        self.assertEqual(int((after[:, CAR[0], 80:104] > 0.5).sum()), 0)  # further than a zone (8 px) from it

    def test_recording_keeps_the_clean_matte(self):
        args, clean = scene(slice(34, 42), slice(44, 54))
        with tempfile.TemporaryDirectory() as folder:
            os.environ["PAINTAPLATE_RECORD"] = folder
            try:
                mathops.follow_matte(**args, erased=clean)
            finally:
                del os.environ["PAINTAPLATE_RECORD"]
            again = mathops.replay(os.path.join(folder, os.listdir(folder)[0]))
        self.assertEqual(again["erased"].shape, clean.shape)
        _, summary = mathops.follow_matte(**again)
        self.assertIn("inside the Clean matte", summary)

    def test_summary_line(self):
        self.assertIn("Removed: areas the shot changed inside the Clean matte, on 1 frame (not touching the SAM mask).",
                      mathops.follow_summary(4, seen=4, cleaned=1))
        self.assertNotIn("Clean matte", mathops.follow_summary(4, seen=4))


if __name__ == "__main__":
    unittest.main()
