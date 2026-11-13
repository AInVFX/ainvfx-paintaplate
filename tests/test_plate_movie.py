"""PL4: Save Movie's memory. plateio.core_uint8 makes core's 8-bit bytes with a strip as its temporary, and
plateio.write_movie converts at most twice its workers ahead of x264, the frames in their order."""
import os
import sys
import tempfile
import threading
import time
import unittest

from _env import ROOT, require

require("numpy", "av")
sys.path.insert(0, ROOT)
import av  # noqa: E402
import numpy as np  # noqa: E402
import plateio  # noqa: E402


class CoreBytes(unittest.TestCase):
    def test_the_bytes_of_core_conversion(self):
        rng = np.random.default_rng(0)
        for shape in ((1, 1, 3), (63, 5, 3), (130, 77, 3), (200, 64, 4), (0, 8, 3)):
            f = rng.uniform(-0.5, 1.5, shape).astype(np.float32)
            f.flat[:min(6, f.size)] = [0.0, 1.0, 1 / 255, 254.999 / 255, -0.0, 0.5][:min(6, f.size)]
            want = np.clip(255.0 * f, 0, 255).astype(np.uint8)
            self.assertEqual(plateio.core_uint8(f).tobytes(), want.tobytes(), shape)
            self.assertEqual(plateio.core_uint8(f, rows=7).tobytes(), want.tobytes(), shape)


class Movie(unittest.TestCase):
    @staticmethod
    def frames(n):
        return [np.full((16, 16, 3), (i * 20) % 256, np.uint8) for i in range(n)]

    def test_a_few_frames_ahead_of_the_encoder(self):
        """Frame 1 is slow to convert: while it is, no frame further than twice the workers is asked for."""
        frames, asked, during, lock = self.frames(40), [0], [], threading.Lock()

        def at(i):
            with lock:
                asked[0] = max(asked[0], i)
            if i == 1:  # holds the window open
                time.sleep(0.3)
                during.append(asked[0])
            return frames[i]
        with tempfile.TemporaryDirectory() as tmp:
            plateio.write_movie(at, 40, os.path.join(tmp, "m.mp4"), 24.0, workers=2)
        self.assertLessEqual(during[0], 4)

    def test_every_frame_in_its_order(self):
        frames = self.frames(12)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.mp4")
            plateio.write_movie(lambda i: frames[i], 12, path, 24.0, workers=4)
            with av.open(path) as c:
                got = [f.to_ndarray(format="rgb24") for f in c.decode(video=0)]
        self.assertEqual(len(got), 12)
        for want, f in zip(frames, got):
            self.assertLess(abs(float(f.mean()) - float(want.mean())), 3.0)


if __name__ == "__main__":
    unittest.main()
