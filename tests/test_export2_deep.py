"""A movie deeper than 10 bits exports as 16-bit PNG frames, which keep its samples (plateio.movie_writer): FFmpeg's ProRes
encoder takes 10 bits, so ProRes 4444 XQ would move a 12-bit plate's untouched pixels by up to 14 of 4095. A movie's bits are
its pixel format's, except a ProRes that FFmpeg wrote, which holds 10 though its decoder reports 12 (plateio.movie_bits)."""
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

from _env import ROOT

sys.path.insert(0, ROOT)
import plateio  # noqa: E402

av = plateio.av
H, W, N = 48, 64, 3


def movie(path, codec, pix, opts=None):  # a ramp with grain, in BT.709, limited range
    rng = np.random.default_rng(5)
    with av.open(path, "w") as out:
        st = out.add_stream(codec, rate=24)
        st.width, st.height, st.pix_fmt = W, H, pix
        cc = st.codec_context
        cc.color_primaries = cc.color_trc = cc.colorspace = 1
        cc.color_range = 1
        cc.options = opts or {}
        for i in range(N):
            rgb = np.clip(np.linspace(0.1, 0.9, W)[None, :, None] + rng.normal(0, 0.5 / 4095, (H, W, 3)) + 0.01 * i, 0, 1)
            f = av.VideoFrame.from_ndarray(np.round(rgb * 65535).astype(np.uint16), format="rgb48le")
            f = f.reformat(format=pix, dst_colorspace=1, src_color_range=2, dst_color_range=1)
            f.pts = i
            for p in st.encode(f):
                out.mux(p)
        for p in st.encode(None):
            out.mux(p)
    return path


@unittest.skipIf(av is None or not {"ffv1", "prores_ks", "libx264"} <= set(av.codecs_available), "PyAV with ffv1, prores_ks and libx264 is needed")
class DeepMovies(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_a_movies_bits_are_its_samples(self):
        h264 = movie(os.path.join(self.dir, "a.mp4"), "libx264", "yuv420p")
        ffv1 = movie(os.path.join(self.dir, "b.mkv"), "ffv1", "yuv444p12le")
        xq = os.path.join(self.dir, "c.mov")
        w = plateio.VideoWriter(plateio.probe_plate(ffv1), xq)
        for _ in range(N):
            w.write(np.full((H, W, 3), 0.5, np.float32))
        w.close()
        bits = {name: plateio.probe_plate(p)["bits"] for name, p in (("h264", h264), ("ffv1 12-bit", ffv1), ("prores from ffmpeg", w.path))}
        self.assertEqual(bits, {"h264": 8, "ffv1 12-bit": 12, "prores from ffmpeg": 10})
        self.assertEqual(plateio.probe_plate(w.path)["pix_fmt"], "yuv444p12le", "its decoder reports 12 bits")

    def test_a_deep_movie_exports_as_16_bit_frames_that_keep_its_samples(self):
        plate = movie(os.path.join(self.dir, "deep.mkv"), "ffv1", "yuv444p12le")
        spec = plateio.probe_plate(plate)
        writer = plateio.movie_writer(spec, os.path.join(self.dir, "out", "deep.mkv"))
        os.makedirs(os.path.join(self.dir, "out"))
        self.assertIsInstance(writer, plateio.FramesWriter)
        keep = np.ones((H, W), bool)
        keep[16:32, 16:48] = False
        source = plateio.SourceFrames(plate, writer.pix_fmt)
        for _ in range(N):
            writer.write(np.full((H, W, 3), 0.25, np.float32), keep=keep, source=source.next())
        source.close()
        writer.close()
        self.assertEqual([os.path.basename(p) for p in writer.paths], [f"deep_{i + 1:05}_.png" for i in range(N)])
        with av.open(plate) as c:
            want = [f.reformat(format="rgb48le").to_ndarray() for f in c.decode(video=0)]
        for path, src in zip(writer.paths, want):
            got = np.round(plateio.read_float(path)[..., :3] * 65535).astype(np.int64)
            self.assertEqual(int(np.abs(got - src)[keep].max()), 0, "untouched pixels: the source's own samples at 16 bits")
            self.assertEqual(int(np.abs(got[~keep] - round(0.25 * 65535)).max()), 0, "the edit: what the composite holds")
            self.assertTrue(((got[keep] >> 4) % 4 != 0).any(), "kept: samples between the steps of a 10-bit grid, which XQ would round")


if __name__ == "__main__":
    unittest.main()
