"""phase_shift with `fine` on soft and sharp textures: two frames, the second moved by a known shift, read to a fortieth
of a pixel or better. The result is the shift that moves the second frame back onto the first."""
import os
import sys
import unittest

import numpy as np
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
import mathops  # noqa: E402


def pan(sigma, seed, w=128, h=72):
    """Two luma frames of a random texture blurred at `sigma`, the second panned by 1 px."""
    tex = ndimage.gaussian_filter(np.random.default_rng(seed).random((h, w + 40)).astype(np.float32), sigma)
    return tex[:, 20:20 + w], tex[:, 21:21 + w]


def moved(a, dy, dx):
    """`a` moved by (dy, dx) px, exactly: a phase ramp in Fourier space."""
    fy, fx = np.fft.fftfreq(a.shape[0])[:, None], np.fft.fftfreq(a.shape[1])[None, :]
    return np.fft.ifft2(np.fft.fft2(a) * np.exp(-2j * np.pi * (fy * dy + fx * dx))).real.astype(np.float32)


class Shift(unittest.TestCase):
    def test_a_pan_of_one_pixel_on_a_soft_texture_reads_one_pixel(self):
        for sigma in (2.0, 1.5, 0.7):
            for seed in (0, 1, 2):
                dy, dx = mathops.phase_shift(*pan(sigma, seed), 8.0, fine=True)
                self.assertAlmostEqual(dx, 1.0, delta=0.03, msg=(sigma, seed))
                self.assertAlmostEqual(dy, 0.0, delta=0.03, msg=(sigma, seed))

    def test_a_sub_pixel_shift_reads_within_a_fortieth_of_a_pixel(self):
        tex = ndimage.gaussian_filter(np.random.default_rng(3).standard_normal((160, 192)), 3.0).astype(np.float32)
        for s in (0.1, 0.2, 0.4, 0.5, 0.7, 1.0, 1.3):
            dy, dx = mathops.phase_shift(tex, moved(tex, 0.3 * s, s), 8.0, fine=True)
            self.assertAlmostEqual(dx, -s, delta=0.025, msg=s)
            self.assertAlmostEqual(dy, -0.3 * s, delta=0.025, msg=s)

    def test_a_whole_pixel_shift_on_a_sharp_texture_is_exact(self):
        tex = np.random.default_rng(3).random((64, 96)).astype(np.float32)
        dy, dx = mathops.phase_shift(tex[:, 10:74], tex[:, 13:77], 8.0, fine=True)
        self.assertAlmostEqual(dx, 3.0, delta=0.01)
        self.assertAlmostEqual(dy, 0.0, delta=0.01)

    def test_a_shift_above_the_limit_and_an_empty_frame_read_no_shift(self):
        tex = np.random.default_rng(4).random((64, 96)).astype(np.float32)
        self.assertEqual(mathops.phase_shift(tex[:, 10:74], tex[:, 13:77], 2.0, fine=True), (0.0, 0.0))
        flat = np.zeros((40, 50), np.float32)
        self.assertEqual(mathops.phase_shift(flat, flat, 8.0, fine=True), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
