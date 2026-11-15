"""PAINTAPLATE_RECORD keeps what Follow Matte read at its own size, in half floats (float16), so a replay counts as the
live run does: the same mattes, at the same size, and the same summary. A recording in 8 bits still replays."""
import glob, os, sys, tempfile, unittest
from _env import require
require("numpy", "scipy")
import numpy as np  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mathops as m  # noqa: E402


def panning(n=12, h=90, w=400):
    """A camera that pans 1 px per frame over a textured plate, and a painted square that stands still in the scene. The
    tracker returns the whole paint zone on the first 3 frames, then the square."""
    rng = np.random.default_rng(5)
    texture = np.repeat(rng.random((h, w + n)), 1, 0)
    base = np.stack([np.repeat(texture[:, n - t:n - t + w, None], 3, 2) for t in range(n)]).astype(np.float32)
    shot, masks = base.copy(), np.zeros((n, h, w), np.float32)
    first, element = np.zeros((h, w), np.float32), np.zeros((h, w), np.float32)
    first[20:70, 40:120] = 1
    element[35:55, 60:80] = 1
    for t in range(n):
        shot[t, 35:55, 60 + t:80 + t] = (0.25, 0.5, 0.75)
        masks[t] = first if t < 3 else 0
        masks[t, 35:55, 60 + t:80 + t] = 1
    return dict(masks=masks, n=n, first=first, shot=shot, base=base, element=element)


def exact(a):  # values that float16 holds exactly: a recording then changes nothing
    return None if a is None else np.round(np.asarray(a, np.float32) * 1024) / 1024


def recorded(args):
    """follow_matte on `args` with PAINTAPLATE_RECORD set: (the live run's mattes and summary, the recording's path)."""
    folder = tempfile.mkdtemp(prefix="record_")
    os.environ["PAINTAPLATE_RECORD"] = folder
    try:
        live = m.follow_matte(**args)
    finally:
        del os.environ["PAINTAPLATE_RECORD"]
    path, = glob.glob(os.path.join(folder, "*.npz"))
    return live, path


class Record(unittest.TestCase):
    def test_a_replay_counts_as_the_live_run(self):
        args = {k: exact(v) if isinstance(v, np.ndarray) else v for k, v in panning().items()}
        (matte, summary), path = recorded(args)
        with np.load(path) as d:
            self.assertEqual({d[k].dtype for k in ("masks", "shot", "base") if d[k].size}, {np.dtype(np.float16)})
        again, said = m.follow_matte(**m.replay(path))
        self.assertEqual(said, summary)
        self.assertTrue(np.array_equal(again, matte))

    def test_a_recording_in_8_bits_still_replays(self):
        _, path = recorded({k: exact(v) if isinstance(v, np.ndarray) else v for k, v in panning().items()})
        with np.load(path) as d:
            old = {k: (np.clip(d[k].astype(np.float32), 0, 1) * 255 + 0.5).astype(np.uint8) if d[k].dtype == np.float16 else d[k] for k in d.files}
        np.savez_compressed(path, **old)
        args = m.replay(path)
        self.assertEqual(args["shot"].dtype, np.float32)
        self.assertLessEqual(float(args["shot"].max()), 1.0)
        self.assertIn("tracked on", m.follow_matte(**args)[1])


if __name__ == "__main__":
    unittest.main()
