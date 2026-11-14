"""The page workstream's rules of tests/object_info_fixture.py, with no ComfyUI: what a class keeps of /object_info."""
import json
import unittest

import object_info_fixture as fixture


class ObjectInfoFixture(unittest.TestCase):
    def test_a_class_keeps_its_inputs_in_order_with_the_options_editor_graph_reads_and_its_outputs(self):
        info = {"input": {"required": {"model": ["MODEL"], "sampler_name": [["euler", "dpmpp_2m"], {"tooltip": "x"}],
                                       "seed": ["INT", {"default": 0, "min": 0, "control_after_generate": True}]},
                          "optional": {"mask": ["MASK", {"forceInput": True}]}, "hidden": {"unique_id": "UNIQUE_ID"}},
                "input_order": {"required": ["seed", "model", "sampler_name"], "optional": ["mask"]},
                "output": ["LATENT"], "output_name": ["LATENT"], "category": "sampling"}
        self.assertEqual(fixture.entry(info), {"input": {"required": {"seed": ["INT", {"default": 0, "control_after_generate": True}],
                                                                      "model": ["MODEL", {}], "sampler_name": ["COMBO", {}]},
                                                         "optional": {"mask": ["MASK", {"forceInput": True}]}},
                                               "output": ["LATENT"], "output_name": ["LATENT"]})

    def test_the_new_combo_form_drops_its_choices_and_keeps_its_upload(self):
        self.assertEqual(fixture.typed(["COMBO", {"options": ["a.png", "b.png"], "image_upload": True}]), ["COMBO", {"image_upload": True}])

    def test_a_text_keeps_dynamic_prompts_which_tells_the_editor_graph_to_hold_it(self):
        self.assertEqual(fixture.typed(["STRING", {"multiline": True, "dynamicPrompts": True, "tooltip": "x"}]), ["STRING", {"multiline": True, "dynamicPrompts": True}])

    def test_the_classes_of_both_formats(self):
        self.assertEqual(fixture.classes({"nodes": [{"type": "A"}, {"type": "B"}]}), {"A", "B"})
        self.assertEqual(fixture.classes({"1": {"class_type": "A", "inputs": {}}, "2": {"class_type": "C", "inputs": {}}}), {"A", "C"})

    def test_the_file_of_today_has_the_shape_the_script_writes(self):
        with open(fixture.FILE) as f:
            nodes = json.load(f)["nodes"]
        self.assertEqual({k: fixture.entry(v) for k, v in nodes.items()}, nodes)


if __name__ == "__main__":
    unittest.main()
