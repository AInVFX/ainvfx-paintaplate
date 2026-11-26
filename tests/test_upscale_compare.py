"""Where Upscale's chunks meet, as tests/upscale_compare.py bounds measures it: core's merge weights, and the steps between
one chunk's own frames and the next one's, for one window."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import upscale_compare  # noqa: E402
import upscale_plate  # noqa: E402


class Bounds(unittest.TestCase):
    def test_the_merge_weights_are_cores_hann_fade_over_the_middle_third(self):
        rounded = lambda o: [round(x, 3) for x in upscale_compare.merge_weights(o)]  # noqa: E731
        self.assertEqual(rounded(1), [1.0], "one shared latent frame: the earlier chunk alone, a cut")
        self.assertEqual(rounded(3), [1.0, 0.5, 0.0], "three: one latent frame half and half")
        self.assertEqual(rounded(4), [1.0, 1.0, 0.0, 0.0], "four: a cut again")
        self.assertEqual(rounded(6), [1.0, 1.0, 0.905, 0.095, 0.0, 0.0])

    def test_a_window_of_49_frames_in_chunks_of_21(self):
        self.assertEqual(upscale_compare.chunk_bounds(49, 21, 1), [(20, 20), (40, 40)], "one shared latent frame: a cut after frames 20 and 40")
        self.assertEqual(upscale_compare.chunk_bounds(49, 21, 3), [(12, 16), (24, 28), (36, 40)], "three: a blend over four steps each")
        self.assertEqual(upscale_compare.chunk_bounds(49, 0, 3), [], "one pass: no boundary")
        self.assertEqual(upscale_compare.chunk_bounds(21, 21, 1), [], "a window of one chunk")

    def test_a_window_of_121_frames_in_chunks_of_21_has_five_cuts(self):
        self.assertEqual(upscale_compare.chunk_bounds(121, 21, 1), [(20, 20), (40, 40), (60, 60), (80, 80), (100, 100)])


    def test_even_chunks_end_on_a_full_chunk_and_none_is_short(self):
        self.assertEqual(upscale_plate.even_chunk(49, 21, 3), 17, "49 frames: chunks of 5 latent frames, the last one full")
        self.assertEqual(upscale_plate.even_chunk(121, 21, 3), 17)
        self.assertEqual(upscale_plate.even_chunk(21, 21, 3), 21, "a window of one chunk: one pass")
        self.assertEqual(upscale_compare.chunk_bounds(49, 17, 3), [(8, 12), (16, 20), (24, 28), (32, 36)], "five chunks of 5 latent frames, two apart: the fifth ends full at the window's end")


if __name__ == "__main__":
    unittest.main()
