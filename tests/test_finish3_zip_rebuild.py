"""tests/zip_rebuild.py on a small zip written as Export writes SDR to HDR's set: half-float EXR frames for the plate, the
layer and the composite, 16-bit PNG frames for the matte. A set whose composite is its plate around its matte and its layer
inside it rebuilds within half-float precision; a matte with one frame too many shows as unequal counts; a stage that lacks
a row names it."""
import os
import sys
import tempfile
import unittest
import zipfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import plateio  # noqa: E402
import zip_rebuild  # noqa: E402

N, H, W = 3, 16, 24


def frames(seed, peak):  # N frames of values from 0 to `peak`
    return [np.random.default_rng(seed + i).uniform(0, peak, (H, W, 3)).astype(np.float32) for i in range(N)]


class ZipRebuild(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.plate, self.layer = frames(1, 1.4), frames(10, 2.0)
        self.matte = [np.clip(np.random.default_rng(20 + i).uniform(-0.3, 1.3, (H, W)), 0, 1).astype(np.float32) for i in range(N)]

    def zip(self, mattes, rows=("plate_hdr", "layer_hdr", "composite_hdr", "matte")):
        root, path = os.path.join(self.dir.name, "rows"), os.path.join(self.dir.name, "set.zip")
        written = [np.round(m * 65535) / 65535 for m in mattes]  # as Save Frames' png16 writes it
        comp = [p * (1 - m[..., None]) + l * m[..., None] for p, l, m in zip(self.plate, self.layer, written)]
        for row, data in (("plate_hdr", self.plate), ("layer_hdr", self.layer), ("composite_hdr", comp)):
            if row in rows:
                os.makedirs(os.path.join(root, row), exist_ok=True)
                plateio.write_exrs(lambda i, d=data: d[i], [os.path.join(root, row, f"desk_{row}_{i + 1:05}.exr") for i in range(N)])
        if "matte" in rows:
            os.makedirs(os.path.join(root, "matte"), exist_ok=True)
            plateio.write_pngs(lambda i: np.repeat(np.round(mattes[i] * 65535).astype(np.uint16)[..., None], 3, 2),
                               [os.path.join(root, "matte", f"desk_matte_{i + 1:05}.png") for i in range(len(mattes))])
        with zipfile.ZipFile(path, "w") as z:
            for folder, _, names in os.walk(root):
                for name in names:
                    z.write(os.path.join(folder, name), os.path.relpath(os.path.join(folder, name), root))
        return path

    def found(self, path):
        with zipfile.ZipFile(path) as z:
            return zip_rebuild.rebuilt(z, os.path.join(self.dir.name, "out"))

    def test_a_set_rebuilds_within_half_float_precision(self):
        v = self.found(self.zip(self.matte))["HDR"]
        self.assertEqual(v[:4], (N, N, N, N))
        self.assertLess(v[6], 1e-3)  # half floats keep 11 bits: a relative step of 1 / 2048

    def test_a_matte_with_a_frame_too_many_shows_as_unequal_counts(self):
        v = self.found(self.zip(self.matte + self.matte[-1:]))["HDR"]
        self.assertEqual(v[:4], (N, N, N + 1, N))
        self.assertTrue(np.isnan(v[4]))

    def test_a_stage_that_lacks_a_row_names_it(self):
        self.assertEqual(self.found(self.zip(self.matte, rows=("plate_hdr", "composite_hdr", "matte")))["HDR"], "lacks layer_hdr")


if __name__ == "__main__":
    unittest.main()
