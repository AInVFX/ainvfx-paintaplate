"""The stand-ins of tests/ui_live.py. Its flow runs on a ComfyUI whose model files are empty, so each workflow that loads a
model and that the flow posts needs a stand-in built from core nodes. A second stage is posted whenever the preview is
smaller than the working size: the full-size clean plate pass posts `cleanup` after `clean`."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import ui_live  # noqa: E402


def nodes(path):
    with open(path, encoding="utf-8") as fh:
        return [n for n in json.load(fh).values() if isinstance(n, dict) and "class_type" in n]


class StandIns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as out:
            ui_live.stand_ins(out)
            cls.made = {name[:-5]: nodes(os.path.join(out, name)) for name in os.listdir(out)}

    def test_a_second_stage_has_the_stand_in_of_its_first_stage(self):
        for first, second in (("clean", "cleanup"),):
            self.assertIn(second, sorted(self.made), f"`{second}` would run its real graph on empty model files")
            self.assertEqual(self.made[second], self.made[first])

    def test_a_stand_in_replaces_a_workflow_that_loads_a_model_and_loads_none(self):
        for name, graph in self.made.items():
            real = nodes(os.path.join(ROOT, "web", "workflows", f"{name}.json"))
            self.assertTrue(any("Loader" in n["class_type"] for n in real), f"`{name}` loads no model: the flow can run it as it is")
            self.assertFalse([n["class_type"] for n in graph if "Loader" in n["class_type"]], f"the stand-in of `{name}` loads a model")


if __name__ == "__main__":
    unittest.main()
