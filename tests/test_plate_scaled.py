"""Frames of another size than the plate, written in the plate's own format: a movie in its codec, a 16-bit PNG sequence
under the plate's frame names, and an EXR frame with its pixel type and its header attributes, its other channels left
out. Save Plate writes the export of Upscale to 4K this way."""
import os
import sys
import tempfile
import unittest
from fractions import Fraction

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import plateio  # noqa: E402

av, OpenEXR = plateio.av, plateio.OpenEXR


def ramp(h, w):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    return np.stack([x / (w - 1), y / (h - 1), (x + y) / (w + h - 2)], -1)


@unittest.skipUnless(av is not None, "PyAV missing")
class ScaledMovie(unittest.TestCase):
    def test_a_movie_keeps_its_codec_pixel_format_and_frame_count_at_twice_its_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = os.path.join(tmp, "plate.mov"), os.path.join(tmp, "out", "plate.mov")
            with av.open(src, "w") as c:
                s = c.add_stream("prores_ks", rate=Fraction(24, 1))
                s.width, s.height, s.pix_fmt = 32, 18, "yuv422p10le"
                for _ in range(3):
                    for p in s.encode(av.VideoFrame.from_ndarray((ramp(18, 32) * 255).astype(np.uint8), format="rgb24")):
                        c.mux(p)
                for p in s.encode():
                    c.mux(p)
            spec = plateio.probe_plate(src)
            spec["frames"] = 3
            scaled = plateio.at_size(spec, 64, 36)
            self.assertEqual((scaled["scaled_from"], spec.get("scaled_from")), ((32, 18), None))
            self.assertIs(plateio.at_size(spec, 32, 18), spec)
            os.makedirs(os.path.dirname(out))
            w = plateio.VideoWriter(scaled, out)
            for _ in range(3):
                w.write(ramp(36, 64))
            w.close()
            with av.open(w.path) as c:
                v = c.streams.video[0]
                self.assertEqual((v.codec_context.name, v.codec_context.pix_fmt, v.width, v.height), ("prores", "yuv422p10le", 64, 36))
                self.assertEqual(sum(1 for _ in c.decode(video=0)), 3)


@unittest.skipUnless(av is not None, "PyAV missing")
class ScaledSequence(unittest.TestCase):
    def test_a_16_bit_png_sequence_keeps_its_depth_and_its_frame_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, out = os.path.join(tmp, "plate"), os.path.join(tmp, "out")
            os.makedirs(folder), os.makedirs(out)
            paths = [os.path.join(folder, f"shot.{n}.png") for n in (1001, 1002)]
            plateio.write_pngs(lambda i: np.round(ramp(6, 8) * 65535).astype(np.uint16), paths)
            spec = plateio.probe_plate(folder)
            spec["frames"] = 2
            scaled = plateio.at_size(spec, 16, 12)
            written = [plateio.write_still(scaled, i, ramp(12, 16), None, None, out) for i in range(2)]
            self.assertEqual([os.path.basename(p) for p in written], ["shot.1001.png", "shot.1002.png"])
            with av.open(written[1]) as c:
                f = next(c.decode(video=0))
                self.assertEqual((f.width, f.height, f.format.name), (16, 12, spec["pix_fmt"]))


@unittest.skipUnless(OpenEXR is not None, "OpenEXR missing")
class ScaledExr(unittest.TestCase):
    def test_an_exr_frame_keeps_its_pixel_type_and_header_and_leaves_its_other_channels_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, out = os.path.join(tmp, "plate"), os.path.join(tmp, "out")
            os.makedirs(folder), os.makedirs(out)
            rgb = ramp(6, 8).astype(np.float16) * 4
            chans = {"R": rgb[..., 0], "G": rgb[..., 1], "B": rgb[..., 2], "Z": np.ones((6, 8), np.float16)}
            OpenEXR.File({"compression": OpenEXR.PIZ_COMPRESSION, "owner": "a test plate"}, chans).write(os.path.join(folder, "shot.0001.exr"))
            spec = plateio.probe_plate(folder)
            spec["frames"] = 1
            path = plateio.write_still(plateio.at_size(spec, 16, 12), 0, ramp(12, 16) * 4, None, None, out)
            with OpenEXR.File(path, separate_channels=True) as f:
                part = f.parts[0]
                self.assertEqual(sorted(part.channels), ["B", "G", "R"])
                self.assertEqual(part.channels["R"].pixels.shape, (12, 16))
                self.assertEqual(part.channels["R"].pixels.dtype, np.float16)
                self.assertEqual((part.header["owner"], part.header["compression"]), ("a test plate", OpenEXR.PIZ_COMPRESSION))
                self.assertAlmostEqual(float(part.channels["R"].pixels.max()), 4.0, places=2)


if __name__ == "__main__":
    unittest.main()
