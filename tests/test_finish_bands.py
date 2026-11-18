"""tests/hdr_plate.py bands: the bands where a tiled decode blends two tiles, found by the difference from a whole decode,
in stops on scene-linear frames and in 8-bit steps on display frames."""
import os
import sys
import tempfile
import unittest

from _env import ROOT, require

require("numpy", "scipy", "av", "OpenEXR", "PIL")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
import hdr_plate  # noqa: E402
import plateio  # noqa: E402

W, H, TILE, OVERLAP = 400, 240, 64, 16  # a tile every 48 px: 7 bands across, from 48 px, and 4 down


def blended(size: int, offsets) -> np.ndarray:
    """Along one side, the level that tiles each off by its own amount leave once core's tiled_scale_multidim blends
    them: each tile weighted by a ramp of OVERLAP px from both its edges, then the weights divided out."""
    total, weight = np.zeros(size), np.zeros(size)
    for k, x in enumerate(range(0, size - OVERLAP, TILE - OVERLAP)):
        n = min(TILE, size - x)
        m = np.ones(n)
        if OVERLAP < n:
            for t in range(OVERLAP):
                m[t] *= (t + 1) / OVERLAP
                m[n - 1 - t] *= (t + 1) / OVERLAP
        total[x:x + n] += m * offsets[k % len(offsets)]
        weight[x:x + n] += m
    return total / weight


def picture(rng) -> np.ndarray:
    """A scene-linear frame from 0.05 to 2, with stripes and grain that the difference from the reference removes."""
    y, x = np.mgrid[0:H, 0:W]
    level = (0.05 + 1.95 * x / W) * (0.6 + 0.4 * np.sin(y / 9.0)) * np.exp(rng.normal(0, 0.2, (H, W)))
    return (level[..., None] * np.array([1.0, 0.9, 0.8])).astype(np.float32)


def exrs(folder, frames):
    os.makedirs(folder)
    plateio.write_exrs(lambda i: frames[i], [os.path.join(folder, f"f_{i:05d}.exr") for i in range(len(frames))], workers=2)
    return folder


class Bands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rng = np.random.default_rng(3)
        self.ref = [picture(self.rng) for _ in range(3)]

    def tearDown(self):
        self.tmp.cleanup()

    def measure(self, frames, **kw):
        ref = exrs(os.path.join(self.tmp.name, "whole"), self.ref)
        test = exrs(os.path.join(self.tmp.name, "tiled"), frames)
        return hdr_plate.bands(ref, test, TILE, OVERLAP, every=1, **kw)

    def test_a_band_put_in_is_found_where_core_blends_two_tiles_and_its_swing_is_read(self):
        level = blended(W, (0.04, -0.04))  # each tile column 0.04 stops over or under the whole decode, in turn
        r = self.measure([f * np.exp2(level)[None, :, None].astype(np.float32) for f in self.ref])
        places = hdr_plate.band_places(W, TILE, OVERLAP)
        self.assertEqual(places, [(x, x + OVERLAP) for x in range(48, 337, 48)])
        expect = [level[a:b].max() - level[a:b].min() for a, b in places]
        self.assertGreater(min(expect), 0.06)
        got = [row for row in r["rows"] if row[0] == "Columns"]
        self.assertEqual([(a, b) for _, a, b, _, _ in got], places)
        for (_, _, _, med, _), e in zip(got, expect):
            self.assertAlmostEqual(med, e, delta=0.003)
        self.assertEqual([row[:3] for row in r["shows"]], [("Columns", a, b) for a, b in places])
        self.assertLess(max(row[3] for row in r["rows"] if row[0] == "Rows"), 0.005)
        self.assertLess(r["controls"]["Columns"], 0.005)
        self.assertIn("Bands over 0.01 stops: 7 of 7 column bands and 0 of 4 row bands.", r["text"])

    def test_the_sheet_shows_both_frames_3_stops_down_and_their_difference_with_a_gold_mark_over_each_band(self):
        level = blended(W, (0.04, -0.04))
        sheet = os.path.join(self.tmp.name, "sky.png")
        r = self.measure([f * np.exp2(level)[None, :, None].astype(np.float32) for f in self.ref], sheet=sheet, rows=(0, 200))
        a = np.asarray(Image.open(sheet).convert("RGB"))
        self.assertEqual(a.shape, (3 * 200 + 8, W, 3))
        for top in (0, 204, 408):
            self.assertEqual(tuple(a[top + 2, 50]), hdr_plate.GOLD)  # the first column band, 48 to 64
            self.assertEqual(tuple(a[top + 50, 2]), hdr_plate.GOLD)  # the first row band, 48 to 64
        x = np.clip(self.ref[0][100, 200] * 2.0 ** -3, 0, 1)
        self.assertTrue(np.allclose(a[204 + 100, 200], (1.055 * x ** (1 / 2.4) - 0.055) * 255, atol=1.5))
        grey = a[408 + 100, 20:30, 0].astype(float)  # inside the first tile, 0.04 stops over: 0.5 + 0.04 / 0.2
        self.assertTrue(np.allclose(grey, 0.7 * 255, atol=2))
        self.assertIn("Sheet `sky.png`: frame 1, rows 0 to 200.", r["text"])

    def test_with_no_reference_the_frames_own_level_shows_its_bands_and_a_frame_with_none_reads_none(self):
        y, x = np.mgrid[0:H, 0:W]
        smooth = ((0.2 + 0.8 * x / W) * np.exp(self.rng.normal(0, 0.01, (H, W))))[..., None].repeat(3, -1).astype(np.float32)
        banded = smooth * np.exp2(blended(W, (0.04, -0.04)))[None, :, None].astype(np.float32)
        for frames, found in (([banded], 7), ([smooth], 0)):
            folder = exrs(os.path.join(self.tmp.name, f"self{found}"), frames)
            r = hdr_plate.bands("", folder, TILE, OVERLAP, every=1, rows=(0, H), sheet=os.path.join(self.tmp.name, f"s{found}.png"))
            self.assertEqual(len([row for row in r["shows"] if row[0] == "Columns"]), found)
            self.assertEqual([row for row in r["shows"] if row[0] == "Rows"], [])
        self.assertIn("against its own level over rows 0 to 240", r["text"])
        self.assertEqual(np.asarray(Image.open(os.path.join(self.tmp.name, "s0.png"))).shape[0], 2 * H + 4)

    def test_a_frame_with_no_band_reads_none_whatever_its_grain_and_its_gain(self):
        frames = [f * np.exp2(0.1 + self.rng.normal(0, 0.01, (H, W, 1))).astype(np.float32) for f in self.ref]
        r = self.measure(frames, out=os.path.join(self.tmp.name, "report", "bands.md"))
        self.assertEqual(r["shows"], [])
        self.assertLess(r["largest"], 0.01)
        self.assertIn("No band over 0.01 stops", r["text"])
        with open(os.path.join(self.tmp.name, "report", "bands.md")) as f:
            self.assertEqual(f.read(), r["text"])

    def test_display_frames_read_in_8_bit_steps_and_the_bands_follow_a_frame_brought_to_another_size(self):
        y, x = np.mgrid[0:H, 0:W]
        ref = (40 + 160 * x / W + 20 * np.sin(y / 7.0)).round()
        work = blended(256, (2.0, -2.0))  # the decode was 256 px high, brought to 240 as the plate's size
        level = np.interp((np.arange(H) + 0.5) * 256 / H - 0.5, np.arange(256), work)
        test = (ref + level[:, None]).round()
        paths = []
        for name, a in (("ref.png", ref), ("test.png", test)):
            paths.append(os.path.join(self.tmp.name, name))
            Image.fromarray(np.repeat(a[..., None], 3, -1).astype(np.uint8)).save(paths[-1])
        r = hdr_plate.bands(*paths, TILE, OVERLAP, work=f"{W}x256", steps=True, every=1)
        places = hdr_plate.band_places(H, TILE, OVERLAP, 256)
        self.assertEqual(places, [(45, 60), (90, 105), (135, 150), (180, 195)])
        self.assertEqual([row[:3] for row in r["shows"]], [("Rows", a, b) for a, b in places])
        self.assertTrue(all(row[3] >= 3.0 for row in r["shows"]))
        self.assertLess(max(row[3] for row in r["rows"] if row[0] == "Columns"), 0.001)
        self.assertIn("in steps (8-bit levels)", r["text"])

    def test_the_bands_are_where_core_starts_its_tiles_on_the_video_vae(self):
        # core's tiled_scale_multidim on a latent n long: tiles start at range(0, n - overlap, tile - overlap), in latent
        # units; the LTX video VAE makes 32 px of each, so 256 px tiles with 64 px of overlap are 8 and 2 units
        for px, n in ((1920, 60), (1088, 34)):
            starts = list(range(0, n - 2, 6))[1:]
            self.assertEqual(hdr_plate.band_places(px, 256, 64), [(32 * s, 32 * s + 64) for s in starts])
        self.assertEqual(len(hdr_plate.band_places(1920, 256, 64)), 9)
        self.assertEqual(hdr_plate.band_places(1080, 256, 64, 1088)[0], (191, 254))


if __name__ == "__main__":
    unittest.main()
