"""tests/upscale_prompts.py: Upscale's jobs, from a /history answer as ComfyUI gives it, written one file each in the order
they ran, exactly as ComfyUI ran them; the jobs of other workflows left out."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import upscale_prompts  # noqa: E402

UP = {"1": {"class_type": "SeedVR2TemporalChunk", "inputs": {"chunking_mode.frames_per_chunk": 21}}, "2": {"class_type": "KSampler", "inputs": {"seed": 42}}}
JOIN = {"1": {"class_type": "PaintAPlate_JoinWindows", "inputs": {"counts": "21,21", "share": 4}}}
OTHER = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {}}}


def entry(number, pid, prompt, status="success"):
    return {"prompt": [number, pid, prompt, {}, []], "outputs": {}, "status": {"status_str": status}}


class Prompts(unittest.TestCase):
    def test_upscale_jobs_in_the_order_they_ran_each_as_ran(self):
        history = {"b" * 36: entry(3, "b" * 36, JOIN), "a" * 36: entry(1, "a" * 36, UP), "c" * 36: entry(2, "c" * 36, OTHER),
                   "d" * 36: entry(4, "d" * 36, UP, "error")}
        with tempfile.TemporaryDirectory() as out:
            rows = upscale_prompts.save(history, out)
            self.assertEqual(rows, [("001_upscale_aaaaaaaa.json", "upscale", "success"), ("002_upscale_export_bbbbbbbb.json", "upscale_export", "success"),
                                    ("003_upscale_dddddddd.json", "upscale", "error")])
            with open(os.path.join(out, rows[0][0]), encoding="utf-8") as f:
                self.assertEqual(json.load(f), UP)


if __name__ == "__main__":
    unittest.main()
