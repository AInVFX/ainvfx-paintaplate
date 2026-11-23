"""The plates that the GPU test makes (tests/gpu_matrix.py, MADE): a plate longer than its source goes back and forth
through the source's frames, so it holds no cut; it has the size, frame rate and length asked for; and each made plate
opens whole (logic.plateLength), so the cases on it measure the length they name."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import av
import numpy as np

from _env import ROOT, tool

sys.path.insert(0, os.path.join(ROOT, "tests"))
import gpu_matrix  # noqa: E402


def grey_movie(path, levels, fps=24, size=(64, 32)):
    """A lossless movie whose frame i is one flat grey, levels[i]."""
    with av.open(path, "w") as c:
        s = c.add_stream("libx264", rate=fps)
        s.width, s.height, s.pix_fmt, s.options = size[0], size[1], "yuv444p", {"qp": "0"}
        for v in levels:
            for packet in s.encode(av.VideoFrame.from_ndarray(np.full((size[1], size[0], 3), v, np.uint8), format="rgb24")):
                c.mux(packet)
        for packet in s.encode():
            c.mux(packet)


class MadePlates(unittest.TestCase):
    def test_frames_go_back_and_forth(self):
        self.assertEqual([gpu_matrix.back_and_forth(i, 4) for i in range(10)], [0, 1, 2, 3, 2, 1, 0, 1, 2, 3])
        self.assertEqual([gpu_matrix.back_and_forth(i, 1) for i in range(3)], [0, 0, 0])

    def test_a_longer_plate_has_its_size_rate_and_length_and_no_cut(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        source, target = os.path.join(tmp, "source.mp4"), os.path.join(tmp, "long.mp4")
        levels = [20 + 25 * i for i in range(9)]
        grey_movie(source, levels)
        gpu_matrix.make_plate(source, target, (128, 64), 25, 20)
        with av.open(target) as c:
            s = c.streams.video[0]
            self.assertEqual((s.width, s.height, float(s.average_rate)), (128, 64, 25.0))
            means = [float(f.to_ndarray(format="rgb24").mean()) for f in c.decode(video=0)]
        self.assertEqual(len(means), 20)
        asked = [levels[gpu_matrix.back_and_forth(i, len(levels))] for i in range(20)]
        self.assertGreater(np.corrcoef(means, asked)[0, 1], 0.999, f"frames {means} against the source's {asked}")

    def test_each_made_plate_opens_whole_and_a_case_uses_it(self):
        cases, rates = gpu_matrix.load_cases(), sorted({fps for _, fps, _ in gpu_matrix.MADE.values()})
        code = ("import { plateLength } from './web/logic.mjs';"
                f"console.log(JSON.stringify({rates}.map((f) => plateLength(f).frames)));")
        r = subprocess.run([tool("node", "install Node.js 20 or newer"), "--input-type=module", "-e", code],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        opens = dict(zip(rates, map(int, r.stdout.strip().strip("[]").split(","))))
        for name, ((width, height), fps, frames) in gpu_matrix.MADE.items():
            self.assertLessEqual(frames, opens[fps], f"{name}: the page opens {opens[fps]} frames at {fps} fps")
            users = [n for n, case in cases.items() if case.get("path") == f"plates/{name}"]
            self.assertTrue(users, f"{name}: no case of gpu_matrix.json opens it")
            for n in users:
                for f in cases[n].get("stage_frames", []):
                    self.assertTrue(1 <= f <= frames, f"{n}: stage frame {f} is outside its plate's {frames} frames")


if __name__ == "__main__":
    unittest.main()
