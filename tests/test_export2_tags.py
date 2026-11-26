"""A movie that Save Plate writes with the plate's own samples kept (plateio.keep_samples) carries the plate's colour
matrix and range on every frame: ProRes writes them into each frame's header, and a reader decodes the frame by them."""
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
W, H, N = 64, 48, 3


def write_plate(path):  # a 10-bit ProRes 422 HQ plate in BT.709, limited range: a ramp with some texture
    rng = np.random.default_rng(3)
    with av.open(path, "w") as out:
        st = out.add_stream("prores_ks", rate=24)
        st.width, st.height, st.pix_fmt = W, H, "yuv422p10le"
        st.codec_context.options = {"profile": "3"}
        for i in range(N):
            rgb = np.clip(np.linspace(0.1, 0.9, W)[None, :, None] + rng.normal(0, 0.02, (H, W, 3)), 0, 1)
            f = av.VideoFrame.from_ndarray(np.round(rgb * 65535).astype(np.uint16), format="rgb48le")
            f = f.reformat(format="yuv422p10le", dst_colorspace=1, src_color_range=2, dst_color_range=1)
            f.pts = i
            for p in st.encode(f):
                out.mux(p)
        for p in st.encode(None):
            out.mux(p)


@unittest.skipIf(av is None or "prores_ks" not in av.codecs_available, "PyAV with prores_ks is needed")
class KeptSamplesKeepTheirTags(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.plate = os.path.join(self.dir, "plate.mov")
        write_plate(self.plate)

    def export(self, codec_spec):
        spec = dict(plateio.probe_plate(self.plate), **codec_spec)
        out = os.path.join(self.dir, f"export_{codec_spec.get('profile', 'own')}.mov".replace(" ", ""))
        frames = plateio.decode_video(self.plate, N, 24)[0]
        keep = np.ones((H, W), bool)
        keep[16:32, 16:48] = False  # the edit: new pixels there, the plate's own samples everywhere else
        writer = plateio.VideoWriter(spec, out)
        source = plateio.SourceFrames(self.plate, writer.pix_fmt)
        for i in range(N):
            frame = np.array(frames[i])
            frame[16:32, 16:48] = (0.8, 0.3, 0.2)
            writer.write(frame, keep=keep, source=source.next())
        source.close()
        writer.close()
        return out, keep

    def check(self, out, keep):
        with av.open(out) as c:
            spaces = {(int(f.colorspace), int(f.color_range)) for f in c.decode(video=0)}
        self.assertEqual(spaces, {(1, 1)}, "every frame names BT.709 and limited range, as the plate does")
        plate = np.asarray(plateio.decode_video(self.plate, N, 24)[0], np.float64)
        back = np.asarray(plateio.decode_video(out, N, 24)[0], np.float64)
        self.assertLess(np.abs(back - plate)[:, keep].mean() * 1023, 4.0, "untouched pixels read back as the plate's, within 4 of 1023")

    def test_the_plates_own_profile(self):
        self.check(*self.export({}))

    def test_prores_4444_xq(self):
        self.check(*self.export({"codec": "prores", "profile": "4444 XQ", "pix_fmt": "yuv444p10le"}))


if __name__ == "__main__":
    unittest.main()
