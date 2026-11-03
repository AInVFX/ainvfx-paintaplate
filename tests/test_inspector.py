"""The colour inspector's pixel route and a video plate's frames at full precision (routes.pixel, routes.video_frames)."""
import os
import unittest

import numpy as np

from _env import require
require("aiohttp")
require("OpenEXR")
import test_routes  # noqa: E402  its ComfyUI folders stand-in, so both files share one `routes` module
import av  # noqa: E402
import OpenEXR  # noqa: E402
import routes  # noqa: E402

INPUT = test_routes.INPUT


def exr(path, rgb):
    with OpenEXR.File({"compression": OpenEXR.PIZ_COMPRESSION, "type": OpenEXR.scanlineimage},
                      {c: rgb[..., i].astype(np.float16) for i, c in enumerate("RGB")}) as f:
        f.write(path)


class Pixel(unittest.TestCase):
    def test_exr_values_as_stored_at_native_size(self):
        os.makedirs(os.path.join(INPUT, "seq"), exist_ok=True)
        for n in range(3):
            rgb = np.zeros((2160, 3840, 3), np.float32)
            rgb[10, 20] = [4.0, 0.5, -0.1]
            rgb[2000, 3800] = [0.25, 0.75 + n, 16.0]
            exr(os.path.join(INPUT, "seq", f"p.{1001 + n:04d}.exr"), rgb)
        got = routes.pixel("seq/p.####.exr", 0, 20, 10)
        self.assertEqual((got["width"], got["height"]), (3840, 2160))
        self.assertEqual(got["value"], [4.0, 0.5, float(np.float16(-0.1))])
        self.assertEqual(routes.pixel("seq/p.####.exr", 2, 3800, 2000)["value"], [0.25, 2.75, 16.0])
        self.assertAlmostEqual(routes.pixel("seq/p.####.exr", 2, 3800, 2000, 3)["mean"][2], 16.0 / 9, places=6)
        with self.assertRaises(ValueError):
            routes.pixel("seq/p.####.exr", 0, 3840, 0)

    def test_video_with_its_own_matrix(self):
        """Lossless BT.709 limited-range YUV codes: the pixel reads them through that matrix and range, exactly."""
        path = os.path.join(INPUT, "clip.mp4")
        codes = [(73, 115, 202), (128, 90, 60), (50, 230, 120), (235, 128, 128)] * 3  # Y, Cb, Cr
        with av.open(path, "w") as c:
            s = c.add_stream("libx264", rate=24, options={"qp": "0"})
            s.width, s.height, s.pix_fmt = 64, 48, "yuv444p"
            s.codec_context.colorspace, s.codec_context.color_range = 1, 1  # BT.709, limited
            for code in codes:
                f = av.VideoFrame(64, 48, "yuv444p")
                for p, v in zip(f.planes, code):
                    p.update(bytes([v]) * (p.line_size * 48))
                f.colorspace, f.color_range = 1, 1
                for pk in s.encode(f):
                    c.mux(pk)
            for pk in s.encode():
                c.mux(pk)

        def bt709(y, cb, cr):
            y, cb, cr = (y - 16) / 219, (cb - 128) / 224, (cr - 128) / 224
            r, b = y + 1.5748 * cr, y + 1.8556 * cb
            return [r, (y - 0.2126 * r - 0.0722 * b) / 0.7152, b]
        for i in (0, 5, 10, 11):
            np.testing.assert_allclose(routes.pixel("clip.mp4", i, 30, 20)["value"], bt709(*codes[i]), atol=1e-5, err_msg=f"frame {i}")
        self.assertEqual(routes.pixel("clip.mp4", 0, 30, 20)["movie"], {"codec": "h264", "pix_fmt": "yuv444p", "bits": 8})
        self.assertNotIn("movie", routes.pixel("seq/p.####.exr", 0, 20, 10))
        frames = routes.video_frames(path, 6, 8)  # past the end, the last frame holds
        self.assertEqual(len(frames), 8)
        np.testing.assert_allclose(frames[-1][0, 0], bt709(*codes[-1]), atol=1e-5)
        body, w, h = routes.deep_frames("clip.mp4", 1, 2, 960)
        self.assertEqual((w, h, len(body)), (64, 48, 2 * 64 * 48 * 3 * 2))

if __name__ == "__main__":
    unittest.main()
