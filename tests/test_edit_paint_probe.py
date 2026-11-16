"""Tests of tests/paint_probe.py's own rules: which stroke shows at each pixel, each over the ones before; the pixels that
each colour shows, as the page counts them; and the strokes' box on 0..1000."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paint_probe  # noqa: E402


class Strokes(unittest.TestCase):
    def test_a_later_stroke_covers_an_earlier_one(self):
        strokes = [("#d32f2f", [(0.2, 0.5), (0.8, 0.5)], 192), ("#000000", [(0.45, 0.5), (0.55, 0.5)], 96)]
        top = paint_probe.layers(strokes, (192, 108))
        shares = paint_probe.shares_of(strokes, top)
        self.assertGreater(shares["#000000"], 0)
        self.assertGreater(shares["#d32f2f"], shares["#000000"])
        self.assertEqual(int(top[54, 96]), 1, "the black stroke shows where it covers the red one")
        self.assertEqual(int(top[54, 50]), 0)

    def test_two_strokes_of_one_colour_add_up(self):
        strokes = [("#1976d2", [(0.1, 0.2), (0.2, 0.2)], 96), ("#1976d2", [(0.7, 0.8), (0.8, 0.8)], 96)]
        top = paint_probe.layers(strokes, (192, 108))
        self.assertEqual(paint_probe.shares_of(strokes, top)["#1976d2"], int((top >= 0).sum()))

    def test_the_box_holds_every_stroke(self):
        top = paint_probe.layers([("#fbc02d", [(0.25, 0.25), (0.75, 0.75)], 20)], (200, 100))
        y0, x0, y1, x1 = paint_probe.bbox_of(top)
        self.assertTrue(y0 < 250 < 750 < y1 and x0 < 250 < 750 < x1, (y0, x0, y1, x1))


if __name__ == "__main__":
    unittest.main()
