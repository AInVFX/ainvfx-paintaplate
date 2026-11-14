"""The page's messages that another tool reads: each reader takes the words the page writes."""
import unittest

import gpu_matrix


class Messages(unittest.TestCase):
    def test_the_working_sizes_line_gives_the_edit_preview_size_in_its_words_and_in_the_older_ones(self):
        new = "Working sizes: edits at 1920 x 1088, edit preview at 768 x 432, shot preview at 640 x 352, tracking at 960 x 544."
        old = "Working sizes: edits at 1920 x 1088, quick passes at 768 x 432, preview at 640 x 352, tracking at 960 x 544"
        self.assertEqual(gpu_matrix.quick_size(new), (768, 432))
        self.assertEqual(gpu_matrix.quick_size(old), (768, 432))
        self.assertIsNone(gpu_matrix.quick_size("Plate desk.mp4: opened in 1.2 s."))

    def test_the_timed_steps_read_the_same_in_the_log_s_new_words_and_in_the_older_ones(self):
        new = ("Render v1: Track the paint, full size: about 40 s.\nRender v1: Track the paint, full size: done in 42.0 s (estimate 40 s).\n"
               "Fluid shot v1: started.\nfluid 1a2b3c4d: done in 30.0 s (12 nodes)\nFluid shot v1: SDR to HDR done in 12.5 s.\n  Half-float EXR frames in x.\n"
               "Fluid shot v1: done in 44.0 s.\n  summary")
        old = ("Render v1: Track the paint, full size (about 40 s)\nRender v1: Track the paint, full size took 42.0 s\n"
               "Fluid v1: 1 keyframe(s)\nfluid 1a2b3c4d: done in 30.0 s (12 nodes)\nFluid v1: SDR to HDR took 12.5 s: half-float EXR frames in x\n"
               "Fluid v1: done in 44.0 s: summary")
        self.assertTrue(gpu_matrix.log_steps(new))
        self.assertEqual(gpu_matrix.log_steps(new), gpu_matrix.log_steps(old))


if __name__ == "__main__":
    unittest.main()
