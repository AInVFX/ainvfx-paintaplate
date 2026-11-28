"""The GPU report reads the page's lines in the words the page writes them."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gpu_matrix  # noqa: E402


class Seeds(unittest.TestCase):
    def test_the_fluid_shot_s_seed_is_read_from_its_detail_line(self):
        log = ("Seed 104 asked for in the address (?seed=): every new edit and every new fluid shot starts from it.\n"
               "Fluid shot v1: started.\n  2 keyframes, at frames 1, 121.\n  1280 x 704, 121 frames at 24 fps.\n"
               '  Seed 104, prompt "a wild fire, flames rising".\n')
        self.assertEqual(gpu_matrix.read_log(log)["seeds"], ["104"])

    def test_the_seed_asked_for_in_the_address_is_not_a_seed_the_page_used(self):
        log = "Seed 7 asked for in the address (?seed=): every new edit and every new fluid shot starts from it.\n"
        self.assertEqual(gpu_matrix.read_log(log)["seeds"], [])

    def test_an_edit_s_and_a_render_s_seeds_are_read_in_their_sentences(self):
        log = ('Edit 1: Clean "", seed 1991206597, whole object on, 1 stroke, over 0 edits.\n'
               "Render v1: 1 edit (Clean 1), seed 1991206597, shot preview at 640 x 352.\n")
        self.assertEqual(gpu_matrix.read_log(log)["seeds"], ["1991206597"])


if __name__ == "__main__":
    unittest.main()
