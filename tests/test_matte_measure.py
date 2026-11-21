"""tests/matte_replay.py on a small recording that PAINTAPLATE_RECORD writes: the replay prints the live run's
summary, measures the share of the changes that each code's matte keeps, tells two codes apart or says that they
agree pixel for pixel, records nothing itself, and draws its sheet."""
import contextlib
import glob
import io
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from _env import require
require("numpy", "scipy", "PIL")
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from scipy import ndimage  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import mathops  # noqa: E402
import matte_replay  # noqa: E402

N, H, W = 12, 72, 128
EMPTY = "import numpy as np\n\n\ndef follow_matte(masks, n, first, shot=None, **kw):\n    return np.zeros((n,) + shot.shape[1:3], np.float32), f\"tracked on 0 of {n} frames.\"\n"


def record(folder):
    """A textured plate, and an object 16 x 20 px that the shot paints and that moves right by 2 px a frame; the tracker
    returns it on every frame. Follow Matte runs once with PAINTAPLATE_RECORD set. Returns the recording and the summary."""
    rng = np.random.default_rng(3)
    plate = ndimage.gaussian_filter(0.3 + 0.4 * rng.random((H, W, 3)), (1, 1, 0)).astype(np.float32)
    base, shot, masks = np.repeat(plate[None], N, 0), np.repeat(plate[None], N, 0), np.zeros((N, H, W), np.float32)
    for t in range(N):
        masks[t, 28:44, 30 + 2 * t:50 + 2 * t] = 1
        shot[t, 28:44, 30 + 2 * t:50 + 2 * t] = (0.9, 0.2, 0.1)
    with mock.patch.dict(os.environ, {"PAINTAPLATE_RECORD": folder}):
        _, summary = mathops.follow_matte(masks, N, masks[0], shot=shot, base=base, element=masks[0], workers=1)
    return glob.glob(os.path.join(folder, "*.npz"))[0], summary


class MatteReplayMeasure(unittest.TestCase):
    def test_a_replay_measures_each_code_and_draws_its_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, summary = record(tmp)
            os.makedirs(os.path.join(tmp, "copy"))
            shutil.copy(mathops.__file__, os.path.join(tmp, "copy", "mathops.py"))
            with open(os.path.join(tmp, "empty.py"), "w") as f:
                f.write(EMPTY)
            text = io.StringIO()
            with contextlib.redirect_stdout(text), mock.patch.dict(os.environ, {"PAINTAPLATE_RECORD": tmp}):
                matte_replay.main([path, "--code", os.path.join(tmp, "copy", "mathops.py"), "--code", os.path.join(tmp, "empty.py"),
                                   "--sheet", os.path.join(tmp, "sheet.jpg"), "--frames", "1,6,12", "--workers", "1"])
            out = text.getvalue()
            self.assertIn(f"--- this checkout: a matte on {N} of {N} frames (1-{N})\n{summary}\n", out)  # the live run's summary
            self.assertIn(f"--- empty: a matte on 0 of {N} frames (none)", out)
            row = {line.split(" | ")[0][2:]: line for line in out.splitlines() if line.startswith("| ") and "---" not in line}
            kept = lambda name: float(re.search(r"\| ([\d.]+)% \(", row[name])[1])  # noqa: E731
            self.assertGreaterEqual(kept("this checkout"), 99.0, out)
            self.assertEqual(kept("copy"), kept("this checkout"))
            self.assertEqual(kept("empty"), 0.0)
            self.assertIn("copy: the same matte as this checkout on every frame, pixel for pixel.", out)
            self.assertIn(f"empty: differs from this checkout on {N} frames", out)
            self.assertEqual(len(glob.glob(os.path.join(tmp, "*.npz"))), 1, "a replay records nothing")
            with Image.open(os.path.join(tmp, "sheet.jpg")) as picture:
                self.assertEqual(picture.size, (6 * W // 2, 18 + 3 * H // 2))  # 3 + 3 codes, 3 frames, half size

    def test_frames_read_as_runs_of_the_plates_numbers(self):
        self.assertEqual(matte_replay.runs([0, 1, 2, 5, 7, 8], 1), "1-3, 6, 8-9")
        self.assertEqual(matte_replay.runs([], 1), "none")
        self.assertEqual(matte_replay.runs([3], 1001), "1004")


if __name__ == "__main__":
    unittest.main()
