"""The page workstream's rules of tests/graph_live.py, with no ComfyUI and no browser: links, values, nodes over each
other, red nodes."""
import unittest

import graph_live


class GraphLive(unittest.TestCase):
    def test_a_link_matches_whatever_the_type_of_its_id(self):
        api = {"5": {"class_type": "VAEDecode", "inputs": {"samples": ["4", 0], "vae": [3, 2]}}}
        made = {5: {"class_type": "VAEDecode", "inputs": {"samples": [4, 0], "vae": ["3", 2]}}}
        self.assertEqual(graph_live.differences(api, made), ([], []))

    def test_a_value_and_a_node_that_differ_are_named_and_an_added_input_apart(self):
        api = {"1": {"class_type": "KSampler", "inputs": {"seed": 103, "cfg": 1.0, "denoise": 0.35}}, "2": {"class_type": "VAELoader", "inputs": {}}}
        made = {"1": {"class_type": "KSampler", "inputs": {"seed": 103, "cfg": 1.0000000001, "denoise": 0.5, "steps": 8}},
                "3": {"class_type": "VAELoader", "inputs": {}}}
        wrong, added = graph_live.differences(api, made)
        self.assertEqual(wrong, ["1 KSampler.denoise: 0.35 became 0.5", "2 VAELoader: only in the page's graph", "3 VAELoader: only in the editor's graph"])
        self.assertEqual(added, ["1 KSampler.steps = 8"])

    def test_nodes_that_touch_are_apart_and_nodes_that_cross_are_named(self):
        boxes = [("1", "a", 0, 0, 100, 100), ("2", "b", 100, 0, 100, 100), ("3", "c", 50, 50, 100, 100)]
        self.assertEqual(graph_live.overlaps(boxes), ["1 « a » and 3 « c »", "2 « b » and 3 « c »"])

    def test_a_class_unknown_to_comfyui_is_red_and_a_note_is_not(self):
        self.assertEqual(graph_live.red(["KSampler", "MarkdownNote", "Missing", "Missing"], {"KSampler"}), ["Missing"])


if __name__ == "__main__":
    unittest.main()
