"""Join Windows reads each window's own frames: a window job that runs again numbers its frames on in its folder, as
Save Image does, and the join keeps that window's newest frames once."""
import json
import os
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import plateio  # noqa: E402


def window(folder, levels, start=1):
    """One run of a window job: a frame per level, numbered from `start` as Save Frames numbers them after the files
    already in the folder."""
    os.makedirs(folder, exist_ok=True)
    plateio.write_pngs(lambda i: np.full((16, 32, 3), round(levels[i] * 65535), np.uint16),
                       [os.path.join(folder, f"f_{start + i:05}_.png") for i in range(len(levels))])


@unittest.skipUnless(plateio.av is not None, "PyAV missing")
class OwnFrames(unittest.TestCase):
    def test_a_window_saved_twice_counts_once_with_its_newest_frames(self):
        with tempfile.TemporaryDirectory() as tmp:  # a shot of 5 frames in windows of 2: 2, 2, then 1
            w = [os.path.join(tmp, f"w{k:03}") for k in range(3)]
            window(w[0], [0.1, 0.2])
            window(w[1], [0.3, 0.4]), window(w[1], [0.35, 0.45], start=3)
            window(w[2], [0.5]), window(w[2], [0.55], start=2)
            joined = plateio.join_windows(w, count=2, max_frames=5)
            np.testing.assert_allclose(joined[:, 0, 0, 0], [0.1, 0.2, 0.35, 0.45, 0.55], atol=1e-4)

    def test_a_folder_beyond_the_shot_reads_no_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = [os.path.join(tmp, f"w{k:03}") for k in range(3)]
            window(w[0], [0.1, 0.2]), window(w[1], [0.3, 0.4]), window(w[2], [0.9])
            np.testing.assert_allclose(plateio.join_windows(w, count=2, max_frames=4)[:, 0, 0, 0], [0.1, 0.2, 0.3, 0.4], atol=1e-4)

    def test_windows_that_share_frames_are_crossfaded_and_each_reads_its_newest_frames(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, "w000"), os.path.join(d, "w001")
            window(a, [0.9]), window(a, [0.1, 0.2, 0.3], start=2)  # w000 ran twice: its newest three frames count
            window(b, [0.4, 0.5])
            joined = plateio.join_windows([a, b], counts=[3, 2], share=1)
            np.testing.assert_allclose(joined[:, 0, 0, 0], [0.1, 0.2, (0.3 + 0.4) / 2, 0.5], atol=1e-4)  # one shared frame: half and half

    def test_a_window_short_of_its_frames_stops_the_join(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = [os.path.join(tmp, f"w{k:03}") for k in range(2)]
            window(w[0], [0.1, 0.2]), window(w[1], [0.3])
            with self.assertRaisesRegex(ValueError, r"^Join Windows: window w001 holds 1 of its 2 frames\.$"):
                plateio.join_windows(w, count=2, max_frames=4)

    def test_without_a_count_every_frame_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = os.path.join(tmp, "w000")
            window(w, [0.1, 0.2]), window(w, [0.3, 0.4], start=3)
            self.assertEqual(len(plateio.join_windows([w], count=0, max_frames=4)), 4)
            self.assertEqual(len(plateio.join_windows([w], count=2, max_frames=0)), 4)


class ExportWorkflow(unittest.TestCase):
    def test_the_export_gives_join_windows_each_windows_frames_and_the_frames_they_share(self):
        with open(os.path.join(ROOT, "web", "workflows", "upscale_export.json")) as f:
            nodes = json.load(f).values()
        join, = [n for n in nodes if n["class_type"] == "PaintAPlate_JoinWindows"]
        self.assertEqual(join["_meta"]["slots"], {"folder": "frames", "count": "count", "max_frames": "max_frames", "counts": "counts", "share": "share"})
        self.assertEqual((join["inputs"]["count"], join["inputs"]["max_frames"], join["inputs"]["counts"], join["inputs"]["share"]), (0, 121, "", 0))



class PageSendsTheWindowSize(unittest.TestCase):
    def test_each_upscale_export_job_of_the_page_sends_each_windows_frames_and_the_frames_they_share(self):
        with open(os.path.join(ROOT, "web", "app.mjs"), encoding="utf-8") as f:
            text = f.read()
        jobs = [text[i:i + 500] for i in range(len(text)) if text.startswith('["upscale_export", {', i)]
        self.assertTrue(jobs)
        for job in jobs:
            self.assertIn('counts: windows.map(([, count]) => count).join(",")', job)
            self.assertIn("share: UPSCALE.share", job)

if __name__ == "__main__":
    unittest.main()
