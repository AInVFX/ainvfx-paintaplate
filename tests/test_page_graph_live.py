"""The page workstream's rules of tests/graph_live.py, with no ComfyUI and no browser: links, values, nodes over each
other, red nodes, image files, the layout, and the offline check of a saved graph."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

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


    def test_the_layout_counts_the_canvas_and_the_links_longer_than_1500_px(self):
        boxes = [("1", "a", 0, 0, 100, 100), ("2", "b", 1700, 0, 100, 100), ("3", "c", 150, 200, 100, 100)]
        links = [[1, 1, 0, 2, 0, "IMAGE"], [2, 1, 1, 3, 0, "MASK"], [3, 9, 0, 2, 1, "INT"]]  # the third leaves from no node
        self.assertEqual(graph_live.spread(boxes, links), {"canvas": [1800, 300], "links": 2, "long": 1, "longest": 1600})

    def test_an_image_file_in_a_subfolder_or_not_named_by_the_note_is_named(self):
        graph = {"nodes": [{"type": "MarkdownNote", "widgets_values": ["These files must be in ComfyUI's input folder: plates/a.mp4, and m_1.png."]},
                           {"type": "LoadImageMask", "widgets_values": ["m_1.png", "alpha"]}, {"type": "LoadImage", "widgets_values": ["paintaplate/s_1.png", "image"]},
                           {"type": "LoadImage", "widgets_values": ["p_1.png", "image"]}]}
        self.assertEqual(graph_live.loaders(graph), (["paintaplate/s_1.png"], ["paintaplate/s_1.png", "p_1.png"]))

    def test_offline_checks_a_saved_graph_with_no_comfyui_and_no_browser(self):
        graph = {"nodes": [{"id": 1, "type": "MarkdownNote", "title": "README", "pos": [0, 0], "size": [400, 300], "widgets_values": ["Files: m_1.png."]},
                           {"id": 2, "type": "LoadImageMask", "pos": [500, 0], "size": [300, 300], "widgets_values": ["m_1.png", "alpha"]},
                           {"id": 3, "type": "NoSuchNode", "pos": [900, 0], "size": [200, 100], "widgets_values": []}],
                 "links": [[1, 2, 0, 3, 0, "MASK"]], "extra": {"paintaplate": {"prompt": {"2": {"class_type": "LoadImageMask", "inputs": {"image": "m_1.png"}}}}}}
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "g.json"), "w") as f:
                json.dump(graph, f)
            with mock.patch.object(sys, "argv", ["graph_live.py", "--offline", "--graph", os.path.join(d, "g.json"), "--out", d]), contextlib.redirect_stdout(io.StringIO()) as said:
                code = graph_live.main()
            with open(os.path.join(d, "graph_live.json")) as f:
                found = json.load(f)
        self.assertEqual((code, found["red"], found["over"], found["deep"], found["unnamed"]), (1, ["NoSuchNode"], [], [], []))
        self.assertEqual(found["spread"], {"canvas": [1100, 330], "links": 1, "long": 0, "longest": 100})
        self.assertIn("Check 3, the values against the page's API graph, needs ComfyUI's editor", said.getvalue())


if __name__ == "__main__":
    unittest.main()
