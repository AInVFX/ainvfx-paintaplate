"""The memory of core's composite, as the docstrings of tools/build_workflows.cleanup and mathops.composite state it
(render workstream, wave 5): four copies of the shot and two of its mask, in float32."""
import os
import unittest

from _env import ROOT

FRAMES, WIDTH, HEIGHT = 121, 1920, 1088


class CompositeMemory(unittest.TestCase):
    def test_four_copies_of_the_shot_and_two_of_its_mask(self):
        gb = FRAMES * WIDTH * HEIGHT * (4 * 3 + 2 * 1) * 4 / 2 ** 30  # the shot has 3 channels, its mask 1, 4 bytes each
        self.assertEqual(f"{gb:.1f} GB", "13.2 GB")
        for rel, name in (("tools/build_workflows.py", "def cleanup("), ("mathops.py", "def composite(")):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                src = f.read()
            start = src.index('"""', src.index(name)) + 3
            doc = src[start:src.index('"""', start)]
            self.assertIn("four copies of the shot and two of its mask", doc, rel)
            self.assertIn("13.2 GB", doc, rel)
            self.assertNotIn("16.9", doc, rel)


if __name__ == "__main__":
    unittest.main()
