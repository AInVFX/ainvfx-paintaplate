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


if __name__ == "__main__":
    unittest.main()
