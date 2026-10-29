"""Round-trip tests for the plate I/O helpers (numpy, PyAV, OpenEXR; no GPU, no ComfyUI)."""
import os, sys, unittest, tempfile
from fractions import Fraction
from _env import require
require("numpy", "PIL", "av", "OpenEXR")
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import plateio  # noqa: E402

import av, OpenEXR  # noqa: E402


def make_exr_sequence(folder, n=3, h=36, w=64):
    rng = np.random.default_rng(0)
    for i in range(n):
        rgb = (rng.random((h, w, 3)) * 4.0).astype(np.float16)  # values above 1.0 on purpose
        header = {"compression": OpenEXR.PIZ_COMPRESSION, "type": OpenEXR.scanlineimage,
                  "owner": "test plate", "chromaticities": (0.713, 0.293, 0.165, 0.830, 0.128, 0.044, 0.32168, 0.33767)}
        ch = {"R": rgb[..., 0].copy(), "G": rgb[..., 1].copy(), "B": rgb[..., 2].copy(),
              "A": np.ones((h, w), np.float16), "depth.Z": rng.random((h, w)).astype(np.float32),
              "diffuse.R": rgb[..., 0].copy(), "diffuse.G": rgb[..., 1].copy(), "diffuse.B": rgb[..., 2].copy()}
        OpenEXR.File(header, ch).write(os.path.join(folder, f"shot_v001.{1001 + i:04d}.exr"))


def make_prores(path, n=9, w=160, h=96):
    out = av.open(path, "w")
    vs = out.add_stream("prores_ks", rate=Fraction(24000, 1001))
    vs.metadata["timecode"] = "01:00:00:00"  # the mov muxer writes a tmcd track from this
    vs.width, vs.height, vs.pix_fmt = w, h, "yuv422p10le"
    vs.codec_context.options = {"profile": "3"}
    vs.codec_context.color_primaries = 1; vs.codec_context.color_trc = 1; vs.codec_context.colorspace = 1
    as_ = out.add_stream("pcm_s16le", rate=48000)
    yy, xx = np.mgrid[0:h, 0:w]
    for i in range(n):
        rgb = np.stack([(xx / w), (yy / h), np.full_like(xx, (i % 8) / 8.0, dtype=float)], -1)
        arr = (rgb * 65535).astype(np.uint16)
        fr = av.VideoFrame.from_ndarray(arr, format="rgb48le").reformat(format="yuv422p10le", dst_colorspace=1, src_color_range=2, dst_color_range=1)
        fr.pts = i
        for p in vs.encode(fr): out.mux(p)
    for p in vs.encode(None): out.mux(p)
    samples = (np.sin(np.arange(48000 // 2) / 10.0) * 3000).astype(np.int16)[None]
    af = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono"); af.sample_rate = 48000; af.pts = 0
    for p in as_.encode(af): out.mux(p)
    for p in as_.encode(None): out.mux(p)
    out.close()


def decode_float(path):
    frames = []
    with av.open(path) as c:
        for f in c.decode(video=0):
            frames.append(f.to_ndarray(format="gbrpf32le"))  # what core uses: (H, W, 3), RGB order
    return frames


class PlateIO(unittest.TestCase):
    """Reading and writing plates: formats, layers, headers, frame names, padding."""

    def test_exr_layers_survive(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "plate"); os.makedirs(src); make_exr_sequence(src)
            spec = plateio.probe_plate(src)
            assert spec["kind"] == "sequence" and spec["frames"] == 3 and spec["first_frame"] == 1001
            assert spec["exr"]["extra_channels"] == ["depth.Z", "diffuse.B", "diffuse.G", "diffuse.R"] or \
                set(spec["exr"]["extra_channels"]) == {"depth.Z", "diffuse.R", "diffuse.G", "diffuse.B"}
            assert plateio.guess_color_space(spec) == "linear ACEScg"
            out = os.path.join(d, "out"); os.makedirs(out)
            new_rgb = np.full((36, 64, 3), 0.25, np.float32)
            path = plateio.output_frame_name(spec, 1, out)
            assert os.path.basename(path) == "shot_v001.1002.exr"
            plateio.write_exr_like(spec["files"][1], new_rgb, None, path)
            with OpenEXR.File(spec["files"][1], separate_channels=True) as a, OpenEXR.File(path, separate_channels=True) as b:
                ca, cb = a.channels(), b.channels()
                assert set(ca) == set(cb)
                for name in ca:
                    if name in ("R", "G", "B"):
                        assert cb[name].pixels.dtype == ca[name].pixels.dtype == np.float16
                        assert np.allclose(cb[name].pixels, 0.25)
                    else:
                        assert np.array_equal(ca[name].pixels, cb[name].pixels), name  # bit-identical
                ha, hb = a.header(), b.header()
                assert hb["owner"] == "test plate"
                assert str(hb["compression"]) == str(ha["compression"])
                assert np.allclose(np.array(hb["chromaticities"], float), np.array(ha["chromaticities"], float))
        print("exr layers: ok")

    def test_video_spec_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "plate.mov"); make_prores(src)
            spec = plateio.probe_plate(src)
            assert spec["kind"] == "video" and spec["codec"] == "prores" and spec["pix_fmt"] == "yuv422p10le", spec
            assert spec["timecode"] == "01:00:00:00" and spec["audio_streams"] == 1 and abs(spec["fps"] - 23.976) < 0.01
            frames = decode_float(src)
            assert frames[0].shape == (96, 160, 3)
            out = os.path.join(d, "out.mov")
            w = plateio.VideoWriter(spec, out, audio_source=src)
            for f in frames:
                w.write(f)
            w.close()
            spec2 = plateio.probe_plate(out)
            for k in ("codec", "pix_fmt", "width", "height", "fps_num", "fps_den", "color_primaries", "color_trc", "colorspace", "timecode", "audio_streams"):
                assert spec2[k] == spec[k], (k, spec2[k], spec[k])
            again = decode_float(out)
            err = max(float(np.abs(a - b).mean()) for a, b in zip(frames, again))
            assert err < 1.0 / 255.0, err  # untouched pixels survive one ProRes generation
            print(f"video round trip: ok (mean abs error {err * 255:.3f} / 255, notes={w.notes})")

    def test_stills(self):
        rgb = np.random.default_rng(1).random((20, 30, 3)).astype(np.float32)
        for ext, fmt in ((".png", "rgb48be"), (".tif", "rgb48le"), (".dpx", "gbrp10le"), (".exr", "gbrpf16le")):
            codec, pix, opts = plateio.still_target({"ext": ext, "pix_fmt": fmt}, False)
            data = plateio.encode_still(rgb, None, codec, pix, opts)
            assert len(data) > 100, ext
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as t:
                t.write(data); p = t.name
            back = decode_float(p)[0]
            tol = {".png": 5e-4, ".tif": 5e-4, ".dpx": 2e-3, ".exr": 2e-3}[ext]  # swscale float path
            assert np.abs(back - rgb).max() < tol, (ext, np.abs(back - rgb).max())
            os.unlink(p)
        print("stills png/tiff/dpx/exr: ok")

    def test_core_save_names(self):
        with tempfile.TemporaryDirectory() as d:
            for i in (1, 2, 10):
                open(os.path.join(d, f"f_{i:05d}_.png"), "wb").close()
            open(os.path.join(d, "notes.txt"), "w").close()
            seq = [os.path.basename(p) for p in plateio.find_sequence(d)]
            assert seq == ["f_00001_.png", "f_00002_.png", "f_00010_.png"], seq
        print("core Save Image names group into one sequence: ok")

    def test_pad(self):
        assert [plateio.pad_count_8n1(n) for n in (1, 2, 9, 10, 97, 100, 121)] == [1, 9, 9, 17, 97, 105, 121]
        print("8n+1 padding: ok")


class Sequences(unittest.TestCase):
    def test_missing_frames_keep_their_numbers(self):
        """As in OpenRV: a missing frame holds the one before, later frames keep their numbers, frames on twos stay on twos."""
        with tempfile.TemporaryDirectory() as d:
            for n in (1001, 1002, 1004, 1005):  # 1003 is missing
                Image.fromarray(np.full((4, 4, 3), n % 256, np.uint8)).save(os.path.join(d, f"shot.{n}.png"))
            files, step, missing = plateio.sequence_frames(d)
            self.assertEqual((len(files), step, missing), (5, 1, [1003]))
            self.assertTrue(files[2].endswith("shot.1002.png"))
            spec = plateio.probe_plate(d)
            self.assertEqual((spec["frames"], spec["missing"]), (5, [1003]))
            self.assertTrue(plateio.output_frame_name(spec, 4, "/out", ".png").endswith("shot.1005.png"))
        with tempfile.TemporaryDirectory() as d:
            for n in (1, 3, 5, 7):  # on twos
                Image.fromarray(np.zeros((4, 4, 3), np.uint8)).save(os.path.join(d, f"t_{n:04d}.png"))
            spec = plateio.probe_plate(d)
            self.assertEqual((spec["frames"], spec["step"], spec["missing"]), (4, 2, []))
            self.assertTrue(plateio.output_frame_name(spec, 3, "/out", ".png").endswith("t_0007.png"))
        print("sequences: missing frames hold, numbers kept, frames on twos")



class BlankCanvas(unittest.TestCase):
    def test_blank_plate_is_black_prores_4444(self):
        """The canvas of a fluid shot: ProRes 4444 at its frame rate and length, every frame black."""
        path = plateio.write_blank(os.path.join(tempfile.mkdtemp(), "blank.mov"), 192, 128, 24, 25)
        spec = plateio.probe_plate(path)
        self.assertEqual((spec["codec"], spec["width"], spec["height"], spec["fps"], spec["frames"]), ("prores", 192, 128, 24.0, 25))
        self.assertIn("4444", spec["profile"])
        with av.open(path) as c:
            frames = [f.to_ndarray(format="rgb24") for f in c.decode(video=0)]
        self.assertEqual(len(frames), 25)
        self.assertLessEqual(max(int(f.max()) for f in frames), 1)
        print("blank canvas: ProRes 4444, 25 black frames: ok")

    def test_prores_4444_plate_exports(self):
        """A ProRes 4444 plate decodes as 12-bit 4:4:4; the export writes it again with prores_ks, which takes 10-bit."""
        spec = plateio.probe_plate(plateio.write_blank(os.path.join(tempfile.mkdtemp(), "p4444.mov"), 128, 64, 25, 9))
        self.assertEqual(spec["pix_fmt"], "yuv444p12le")
        self.assertEqual(plateio.encoder_pix_fmt("prores_ks", "yuv444p12le"), "yuv444p10le")
        self.assertEqual(plateio.encoder_pix_fmt("prores_ks", "yuv422p10le"), "yuv422p10le")
        writer = plateio.VideoWriter(spec, os.path.join(tempfile.mkdtemp(), "out.mov"))
        for _ in range(9):
            writer.write(np.full((64, 128, 3), 0.5, np.float32))
        writer.close()
        back = plateio.probe_plate(writer.path)
        self.assertEqual((back["codec"], back["frames"]), ("prores", 9))
        self.assertIn("4444", back["profile"])
        print("ProRes 4444 plate export: ok", writer.notes)


class WritePngsTest(unittest.TestCase):
    def test_frames_written_in_parallel_exactly(self):
        rng = np.random.default_rng(5)
        frames = [rng.integers(0, 256, (24, 40, 3), np.uint8) for _ in range(5)] + [rng.integers(0, 256, (24, 40, 4), np.uint8)]
        ticks = []
        with tempfile.TemporaryDirectory() as d:
            paths = [os.path.join(d, f"f_{i + 1:05}_.png") for i in range(len(frames))]
            plateio.write_pngs(lambda i: frames[i], paths, workers=3, tick=lambda: ticks.append(1))
            back = [np.asarray(Image.open(p)) for p in paths]
        self.assertEqual(len(ticks), len(frames))
        self.assertTrue(all(np.array_equal(a, b) for a, b in zip(frames, back)))
        print("PNG frames: ok (RGB and RGBA, written in parallel, every pixel exact)")


class MovieAndSamplesTest(unittest.TestCase):
    def test_movie_as_core_tags_it(self):
        colours = [(128, 128, 128), (200, 40, 40), (30, 160, 90), (240, 220, 30), (20, 30, 200)]
        frames = [np.full((48, 64, 3), c, np.uint8) for c in colours]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "raw_00001_.mp4")
            plateio.write_movie(lambda i: frames[i], len(frames), path, 24.0, workers=3)
            with av.open(path) as c:
                cc = c.streams.video[0].codec_context
                tags = (cc.name, cc.pix_fmt, int(cc.colorspace), int(cc.color_range), int(cc.color_primaries), int(cc.color_trc))
                got = [f.reformat(format="rgb24", src_colorspace=1, src_color_range=1, dst_color_range=2).to_ndarray()
                       for f in c.decode(video=0)]
        self.assertEqual(tags, ("h264", "yuv420p", 1, 1, 1, 13))  # as core: BT.709 matrix and primaries, sRGB transfer, limited
        worst = max(np.abs(g[8:-8, 8:-8].astype(int) - f[8:-8, 8:-8]).max() for g, f in zip(got, frames))
        self.assertLessEqual(worst, 4)  # the BT.709 matrix both ways: a wrong matrix shifts saturated colours far more
        print(f"movie: ok (H.264 yuv420p, BT.709 and sRGB tags, flat colours back within {worst}/255)")

    def test_untouched_samples_are_the_source(self):
        rng = np.random.default_rng(10)
        for fmt in ("yuv420p", "yuv422p10le"):
            src = av.VideoFrame.from_ndarray(rng.integers(0, 256, (16, 24, 3), np.uint8), format="rgb24").reformat(format=fmt)
            new = av.VideoFrame.from_ndarray(rng.integers(0, 256, (16, 24, 3), np.uint8), format="rgb24").reformat(format=fmt)
            keep = np.zeros((16, 24), bool)
            keep[:, 13:] = True  # an odd edge: the chroma column shared with column 12 changed, so it keeps the new sample
            out = plateio.keep_samples(new, src, keep)
            size = 2 if "10" in fmt else 1
            y = [plateio.plane_array(f.planes[0], size) for f in (out, src, new)]
            u = [plateio.plane_array(f.planes[1], size) for f in (out, src, new)]
            self.assertTrue(np.array_equal(y[0][:, 13:], y[1][:, 13:]) and np.array_equal(y[0][:, :13], y[2][:, :13]))
            self.assertTrue(np.array_equal(u[0][:, 7:], u[1][:, 7:]) and np.array_equal(u[0][:, :7], u[2][:, :7]))
        print("untouched YUV samples: ok (4:2:0 and 4:2:2 10-bit, a shared chroma sample kept only when all its pixels are)")


class FloatReadTest(unittest.TestCase):
    def test_read_float_keeps_exr_values(self):
        import OpenEXR
        rgb = np.zeros((4, 6, 3), np.float32)
        rgb[..., 0], rgb[..., 1], rgb[..., 2] = 2.5, 0.25, -0.125
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "f.0001.exr")
            for kind in (np.float16, np.float32):  # half EXR decodes to gbrpf16le, float EXR to gbrpf32le
                OpenEXR.File({"compression": OpenEXR.ZIP_COMPRESSION, "type": OpenEXR.scanlineimage}, {"RGB": rgb.astype(kind)}).write(path)
                np.testing.assert_allclose(plateio.read_float(path), rgb, atol=1e-3)
        print("float read: ok (2.5, 0.25 and -0.125 kept, in RGB order, from half and float EXR)")

if __name__ == "__main__":
    unittest.main(verbosity=2)
