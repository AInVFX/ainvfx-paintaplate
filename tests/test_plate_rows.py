"""PL8: plateio.decode_video sizes its array by what the file holds, not by max_frames, and keeps core's pictures when
the file's header says another count."""
import os
import sys
import tempfile
import tracemalloc
import unittest
from unittest import mock

from _env import ROOT, require

require("numpy", "av")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import decode_parity  # noqa: E402
import plateio  # noqa: E402


class Rows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.paths = {os.path.basename(p): p for p in decode_parity.movies(cls.tmp.name)}  # 30 frames each

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_a_short_clip_with_1024_max_frames_holds_its_own_rows(self):
        frame = 144 * 256 * 3 * 4
        tracemalloc.start()
        try:
            rgb, alpha, n = plateio.decode_video(self.paths["h264_256.mp4"], 1024, 24.0, pad_8n1=True)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual((n, rgb.shape[0]), (30, 33))  # 30 frames and their padding to 8k+1
        self.assertTrue(rgb.flags.owndata)
        self.assertLess(peak, 40 * frame)  # 1,024 rows reserved 1,033 frames' worth

    def test_a_header_that_says_another_count_keeps_core_pictures(self):
        for name in ("mjpeg_yuvj.mov", "prores4444_alpha.mov"):
            path = self.paths[name]
            right = plateio.decode_video(path, 121, 24.0, pad_8n1=True)
            self.assertEqual(plateio._frames_said(path), 30)
            for said in (0, 5, 29, 31, 500):
                with mock.patch.object(plateio, "_frames_said", return_value=said):
                    rgb, alpha, n = plateio.decode_video(path, 121, 24.0, pad_8n1=True)
                self.assertEqual((n, rgb.shape[0]), (30, 33), (name, said))
                self.assertEqual(rgb.tobytes(), right[0].tobytes(), (name, said))
                self.assertEqual(alpha is None, right[1] is None)
                self.assertTrue(alpha is None or alpha.tobytes() == right[1].tobytes())
                self.assertTrue(rgb.flags.owndata)

    def test_a_trim_still_stops_at_max_frames(self):
        rgb, _, n = plateio.decode_video(self.paths["h264_256.mp4"], 17, 24.0, pad_8n1=True)
        self.assertEqual((n, rgb.shape[0]), (17, 17))


if __name__ == "__main__":
    unittest.main()
