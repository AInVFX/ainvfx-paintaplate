"""Core's tone mapping undone on the way back from the model space (the colour review's proposal A): ocio.undo_tone,
ocio.convert out of @model with the plate's peak, and ocio.out_of_model, with which Relight Transfer measures the light.
Runs without torch or ComfyUI."""
import sys
import unittest

from _env import ROOT, require

require("PyOpenColorIO", "numpy", "scipy")
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
import mathops  # noqa: E402
import ocio  # noqa: E402

LIN709, PEAK = "Linear Rec.709 (sRGB)", 7.4


def lum(frames):
    return np.concatenate([f[..., :3] @ ocio.REC709_LUMA for f in frames]).ravel()


def stops(after, before):
    return np.log2(np.maximum(lum(after), 1e-9) / lum(before))


def hdr_frames(peak=PEAK, n=5, size=96):
    """Frames in scene-linear Rec.709 as a camera gives them: luminance from 0.01 to `peak`, each channel within 25 % of
    it, and one grey pixel at the peak."""
    rng, out = np.random.default_rng(0), []
    for _ in range(n):
        level = np.exp(rng.uniform(np.log(0.01), np.log(peak), (size, size, 1)))
        tint = 1.0 + rng.uniform(-0.25, 0.25, (size, size, 3))
        f = (level * tint / (tint @ ocio.REC709_LUMA)[..., None]).astype(np.float32)
        f[0, 0] = peak
        out.append(f)
    return out


class OutOfTheModelSpace(unittest.TestCase):
    def setUp(self):
        self.plate = hdr_frames()
        self.peak = ocio.batch_peak(self.plate, ocio.BUILTIN, LIN709)
        self.model = ocio.convert(self.plate, ocio.BUILTIN, LIN709, ocio.MODEL, self.peak)

    def test_decoded_as_it_is_new_content_comes_back_low(self):
        """The review's numbers at a peak of 7.4: a grey of 0.18 comes back 0.23 stops low, a white of 1.0 0.97 stops low."""
        self.assertAlmostEqual(self.peak, PEAK, places=5)
        today, level = stops(ocio.convert(self.model, ocio.BUILTIN, ocio.MODEL, LIN709), self.plate), lum(self.plate)
        for at, low in ((0.18, -0.23), (1.0, -0.97)):
            self.assertAlmostEqual(float(np.median(today[np.abs(np.log2(level / at)) < 0.05])), low, delta=0.02)

    def test_exact_below_one_and_within_005_stops_up_to_the_peak(self):
        back = ocio.convert(self.model, ocio.BUILTIN, ocio.MODEL, LIN709, self.peak)
        error, level = np.abs(stops(back, self.plate)), lum(self.plate)
        self.assertLess(error[level < 1.0].max(), 1e-3)
        self.assertLess(error.max(), 0.05)
        channels = np.abs(np.log2(np.maximum(np.concatenate(back), 1e-9) / np.concatenate(self.plate))).reshape(-1, 3)
        self.assertLess(channels[level < 1.0].max(), 1e-3)  # below 1.0 each channel comes back too, so the colour does

    def test_any_destination_goes_through_linear_light(self):
        lin = ocio.convert(self.model, ocio.BUILTIN, ocio.MODEL, LIN709, self.peak)
        same = ocio.convert(self.model, ocio.BUILTIN, ocio.MODEL, ocio.LINEAR, self.peak)
        self.assertTrue(all(a.tobytes() == b.tobytes() for a, b in zip(lin, same)))
        for dst in ("ACEScg", "ACEScct"):
            want = np.stack(ocio.convert(lin, ocio.BUILTIN, LIN709, dst))
            got = np.stack(ocio.convert(self.model, ocio.BUILTIN, ocio.MODEL, dst, self.peak))
            np.testing.assert_allclose(got, want, rtol=1e-5, atol=1e-6)

    def test_a_plate_at_or_under_one_gives_the_same_bytes(self):
        rng = np.random.default_rng(1)
        model = [rng.uniform(0, 1, (32, 48, 3)).astype(np.float32) for _ in range(3)]
        self.assertEqual(ocio.batch_peak([f * 0.9 for f in model], ocio.BUILTIN, LIN709), 1.0)
        for dst in (LIN709, ocio.LINEAR, "ACEScg", "ACEScct"):
            today = ocio.convert(model, ocio.BUILTIN, ocio.MODEL, dst)
            for peak in (None, 1.0, ocio.TONE_ABOVE):
                got = ocio.convert(model, ocio.BUILTIN, ocio.MODEL, dst, peak)
                self.assertTrue(all(a.tobytes() == b.tobytes() for a, b in zip(got, today)), (dst, peak))
        self.assertEqual(ocio.out_of_model(model[0], 1.0).tobytes(), ocio.decode(model[0]).tobytes())

    def test_alpha_stays(self):
        f = np.concatenate([self.model[0], np.full(self.model[0].shape[:2] + (1,), 0.25, np.float32)], -1)
        back = ocio.convert([f], ocio.BUILTIN, ocio.MODEL, LIN709, self.peak)[0]
        self.assertEqual(back.shape[-1], 4)
        self.assertTrue((back[..., 3] == 0.25).all())
        self.assertTrue((ocio.out_of_model(f, self.peak)[..., 3] == 0.25).all())

    def test_relight_transfer_way_is_the_same_return(self):
        """Core's sRGB decode where convert takes the config's: the same levels, to 0.001 stops."""
        mine = [ocio.out_of_model(f, self.peak) for f in self.model]
        ref = ocio.convert(self.model, ocio.BUILTIN, ocio.MODEL, LIN709, self.peak)
        self.assertLess(np.abs(stops(mine, ref)).max(), 1e-3)


class RelightAtThePlateLevels(unittest.TestCase):
    def test_half_the_light_comes_back_as_half_the_light(self):
        """A plate of a grey of 0.18 and a highlight of 4.0, at a peak of 7.4; the model makes it again at half the light.
        Measured at the plate's levels, the relit plate is half the plate. Decoded as it is, the highlight loses about
        a third of a stop where it should lose one."""
        h, w = 48, 160
        plate = np.full((h, w, 3), 0.18, np.float32)
        plate[:, w // 2:] = 4.0
        source, relit = (ocio.convert([p], ocio.BUILTIN, LIN709, ocio.MODEL, PEAK)[0] for p in (plate, plate * 0.5))
        new = mathops.relight_frame(plate, ocio.out_of_model(source, PEAK), ocio.out_of_model(relit, PEAK), 1, 1.0,
                                    (0.0, 0.0), "linear", "linear")
        old = mathops.relight_frame(plate, source, relit, 1, 1.0, (0.0, 0.0), "linear", "sRGB")
        away = np.r_[0:w // 2 - 24, w // 2 + 24:w]
        error = np.log2(new[:, away] @ ocio.REC709_LUMA / (plate[:, away] @ ocio.REC709_LUMA * 0.5))
        self.assertLess(np.abs(error).max(), 0.02)
        highlight = np.log2(old[:, w // 2 + 24:] @ ocio.REC709_LUMA / 4.0)
        self.assertGreater(float(np.median(highlight)), -0.5)  # today: about -0.3 stops


if __name__ == "__main__":
    unittest.main()
