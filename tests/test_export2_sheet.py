"""The GPU sheet reads a zip's result by its row (tests/zip_rows.py, gpu_matrix.sheet): a Light edit in HDR, whose zip holds
its result as composite_hdr/ EXR frames and no full-size composite, gives a sheet."""
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

import numpy as np

from _env import ROOT

sys.path.insert(0, ROOT)
import gpu_matrix  # noqa: E402
import plateio  # noqa: E402


class LightInHdr(unittest.TestCase):
    def test_a_relit_result_in_hdr_gives_a_sheet(self):
        import av
        tmp, (w, h, n) = tempfile.mkdtemp(prefix="paintaplate_sheet_"), (320, 192, 4)
        self.addCleanup(shutil.rmtree, tmp, True)
        plate = os.path.join(tmp, "plate.mp4")
        with av.open(plate, "w") as c:
            s = c.add_stream("mpeg4", rate=24)
            s.width, s.height, s.pix_fmt = w, h, "yuv420p"
            for _ in range(n):
                for p in s.encode(av.VideoFrame.from_ndarray(np.full((h, w, 3), 128, np.uint8), format="rgb24")):
                    c.mux(p)
            for p in s.encode():
                c.mux(p)
        frames = [os.path.join(tmp, f"f_{i + 1:05}_.exr") for i in range(n)]
        plateio.write_exrs(lambda i: np.full((h, w, 3), 2.5, np.float32), frames, workers=1, fps=24.0)  # above 1.0: SDR to HDR's values
        folder = os.path.join(tmp, "case")
        os.makedirs(folder)
        with zipfile.ZipFile(os.path.join(folder, "export.zip"), "w") as z:  # as Export zips a Light edit in HDR, which the dialog opens on
            for i, f in enumerate(frames):
                z.write(f, f"composite_hdr/plate_composite_hdr_{i + 1:05}_.exr")
        case = {"path": "plates/plate.mp4", "strokes": [["light", "a warm light", [[0.4, 0.5], [0.6, 0.5]], 30, {}]]}
        got = gpu_matrix.sheet(case, folder, plate)
        self.assertTrue(got and os.path.exists(got["path"]), f"a sheet for the relit result in HDR: {got}")


if __name__ == "__main__":
    unittest.main()
