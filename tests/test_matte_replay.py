"""Follow Matte reads its inputs in half floats, as a recording keeps them: a recording replays its live run exactly."""
import os, sys, tempfile, unittest
from _env import require
require("numpy", "scipy")
import numpy as np  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mathops as m  # noqa: E402


class RecordingReplays(unittest.TestCase):
    def test_a_recording_replays_its_live_run_exactly(self):
        """SAM's mask has a rim at 0.5002 over pixels the shot leaves as they were: a half float reads it as 0.5, which
        is not above the mask's threshold, so the rim is in the matte only if the live run reads more digits."""
        rng = np.random.default_rng(17)
        n, h, w = 12, 48, 64
        masks = np.zeros((n, h, w), np.float32)
        masks[:, 14:34, 18:46] = 0.5002  # the rim
        masks[:, 18:30, 22:42] = 1.0  # the body
        base = (0.4 + 0.2 * rng.random((n, h, w, 3))).astype(np.float32)
        shot = base.copy()
        shot[:, 18:30, 22:42] += 0.3  # the paint, on the body only
        first = (masks[0] > 0.9).astype(np.float32)
        live, said = m.follow_matte(masks, n, first, shot=shot, base=base)
        with tempfile.TemporaryDirectory() as folder:
            again, says = m.follow_matte(**m.replay(m.record(folder, masks, n, first, shot, base, 1 / 16, 0.1, None)))
        self.assertEqual(said, says)
        self.assertEqual(int((live != again).sum()), 0)


if __name__ == "__main__":
    unittest.main()
