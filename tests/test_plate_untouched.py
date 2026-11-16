"""Where the export's matte shows 0, the export holds the plate's own samples. The scene has a soft edge, as Fit to Plate
makes it with the export's grow, feather and steady, and its first 8-bit step holds pixels that the composite changed.
The frames are read back as the export's measures read them, with read_float, which reads each level of a still at
its own depth."""
import os
import sys
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
import mathops  # noqa: E402
import plateio  # noqa: E402

H, W, N = 72, 96, 3


class StillLevels(unittest.TestCase):
    def check(self, levels, scale):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "levels.png")
            frame = np.repeat(levels.reshape(16, -1)[..., None], 3, -1)
            plateio.write_pngs(lambda i: frame, [path], workers=1)
            np.testing.assert_array_equal(plateio.read_float(path), frame.astype(np.float32) / np.float32(scale))

    def test_an_8_bit_level_k_reads_k_over_255(self):
        self.check(np.arange(256, dtype=np.uint8), 255)

    def test_a_16_bit_level_k_reads_k_over_65535(self):
        self.check(np.array([0, 1, 255, 256, 257, 4096, 32767, 32768, 65280, 65534, 65535, 2, 3, 510, 511, 512] * 2,
                            np.uint16), 65535)


class UntouchedOnASoftMatte(unittest.TestCase):
    def export(self, ext, write, element):
        rng = np.random.default_rng(7)
        with tempfile.TemporaryDirectory() as d:
            src, out = os.path.join(d, "plate"), os.path.join(d, "export")
            os.makedirs(src), os.makedirs(out)
            paths = [os.path.join(src, f"plate.{1001 + i}{ext}") for i in range(N)]
            frames = [(rng.random((H, W, 3)) * 0.6 + 0.2).astype(np.float32) for _ in range(N)]
            write(frames, paths)
            spec = plateio.probe_plate(src)
            plate = [plateio.read_float(p) for p in paths]
            boxes = np.zeros((N, H, W), np.float32)
            for i in range(N):  # a box that moves one pixel a frame
                boxes[i, 24:48, 30 + i:60 + i] = 1.0
            gen = np.full((H, W, 3), element, np.float32)
            images, masks = mathops.fit_to_plate(N, H, W, lambda i: plate[i], lambda i: gen, boxes, align=False,
                                                 match_color=False, grain=0.0, grow=8, feather=12, steady=2, workers=1)
            mattes = [os.path.join(d, f"matte_{i + 1:05}_.png") for i in range(N)]
            for i in range(N):  # Save Plate's copy, and the matte as Save Frames writes it
                final = mathops.composite(plate[i], images[i], masks[i])
                plateio.write_still(spec, i, final, None, plateio.untouched(masks[i]), out)
            plateio.write_pngs(lambda i: plateio.core_uint8(np.repeat(masks[i][..., None], 3, -1)), mattes, workers=1)
            first_step = []
            for i, name in enumerate(sorted(os.listdir(out))):
                result, stored = plateio.read_float(os.path.join(out, name)), plateio.core_uint8(masks[i])
                shows_0 = plateio.untouched(plateio.read_float(mattes[i])[..., 0])
                np.testing.assert_array_equal(shows_0, stored == 0)
                np.testing.assert_array_equal(result[shows_0], plate[i][shows_0])
                first_step.append(np.abs(result - plate[i])[stored == 1].max(initial=0.0))
            self.assertGreater(max(first_step), 0.0)  # the composite changed pixels of the matte's first step

    def test_half_float_exr(self):
        self.export(".exr", lambda f, p: plateio.write_exrs(lambda i: f[i] * 6.0, p, workers=1, fps=24.0), 9.0)

    def test_8_bit_png(self):
        self.export(".png", lambda f, p: plateio.write_pngs(lambda i: plateio.core_uint8(f[i]), p, workers=1), 1.0)

    def test_16_bit_png(self):
        self.export(".png", lambda f, p: plateio.write_pngs(lambda i: np.round(f[i] * 65535).astype(np.uint16), p,
                                                             workers=1), 1.0)


if __name__ == "__main__":
    unittest.main()
