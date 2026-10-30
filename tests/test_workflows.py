"""The workflows the page runs: generated from tools/build_workflows.py, openable in ComfyUI, valid against its source."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from _env import COMFY, LTX, ROOT

WORKFLOWS = os.path.join(ROOT, "web", "workflows")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_workflows  # noqa: E402


class Workflows(unittest.TestCase):
    def test_generated_files_are_current(self):
        """web/workflows matches what tools/build_workflows.py writes: no hand edits, no stale files."""
        with tempfile.TemporaryDirectory() as out:
            subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_workflows.py")], check=True,
                           env={**os.environ, "PAINTAPLATE_WORKFLOWS_OUT": out}, capture_output=True)
            self.assertEqual(sorted(os.listdir(out)), sorted(os.listdir(WORKFLOWS)))
            for name in os.listdir(out):
                with open(os.path.join(out, name)) as a, open(os.path.join(WORKFLOWS, name)) as b:
                    self.assertEqual(json.load(a), json.load(b), f"{name} is stale: run tools/build_workflows.py")

    def test_mattes_are_combined_at_one_size(self):
        """Combine Masks crops its source to its destination and never scales it (comfy_extras/nodes_mask.py), and the
        erase matte is tracked smaller than the paint matte: each composite scales the erase matte to the paint matte's
        size first. Without it, the paint matte of a plate with an erase kept its top-left corner, stretched."""
        for name in ("comp", "review", "export"):
            with open(os.path.join(WORKFLOWS, f"{name}.json")) as f:
                wf = json.load(f)
            [combine] = [n for n in wf.values() if n["class_type"] == "MaskComposite"]
            scaled = wf[wf[combine["inputs"]["destination"][0]]["inputs"]["image"][0]]
            self.assertEqual(scaled["class_type"], "ImageScale", name)
            size = wf[scaled["inputs"]["width"][0]]
            self.assertEqual((size["class_type"], scaled["inputs"]["height"][0]), ("GetImageSize", scaled["inputs"]["width"][0]), name)
            source = wf[combine["inputs"]["source"][0]]
            self.assertEqual(size["inputs"]["image"], source["inputs"]["image"], f"{name}: the erase matte takes the paint matte's size")

    def test_files_open_in_comfyui_as_api_workflows(self):
        """ComfyUI's frontend loads a JSON file as an API workflow when every top-level value has a class_type
        and an inputs object (src/scripts/metadata/json.ts and app.ts, ComfyUI_frontend 1.57.1)."""
        for name in os.listdir(WORKFLOWS):
            with open(os.path.join(WORKFLOWS, name)) as f:
                data = json.load(f)
            for nid, node in data.items():
                self.assertIsInstance(node.get("class_type"), str, f"{name} #{nid}")
                self.assertIsInstance(node.get("inputs"), dict, f"{name} #{nid}")

    def test_every_slot_points_at_a_real_input(self):
        """Each named slot the page fills names a node and an input that exist in the prompt."""
        for name in build_workflows.NAMES:
            prompt, slots, outputs = build_workflows.load(name, WORKFLOWS)
            self.assertTrue(slots, name)
            for slot, targets in slots.items():
                for node, field in targets:
                    self.assertIn(node, prompt, f"{name}: slot {slot}")
                    self.assertIn(field, prompt[node]["inputs"], f"{name}: slot {slot}")
            for out, node in outputs.items():
                self.assertIn(node, prompt, f"{name}: output {out}")

    def test_outputs_the_page_reads(self):
        """The page picks results by output name, not by position."""
        wanted = {"ingest": {"hero", "proxy", "spec"}, "prompt": {"text"}, "edit": {"patch", "relit", "result"},
                  "snap": {"named"} | {f"point_{k}" for k in range(5)}, "clean": {"frames", "video"}, "cleanup": {"frames", "video"}, "shot": {"frames", "video"},
                  "matte": {"follow", "frames"}, "comp": {"video"}, "review": {"review", "frames"}, "export": {"export", "matte"},
                  "warm": {"frame"},
                  "fluid": {"plate", "video"}, "hdr": {"hdr"}}
        for name, keys in wanted.items():
            self.assertEqual(set(build_workflows.load(name, WORKFLOWS)[2]), keys, name)

    def test_setup_downloads_every_model_file(self):
        """get_models.py downloads every model file a workflow loads, at a pinned revision, and the pod setup runs it."""
        import glob, json
        sys.path.insert(0, ROOT)
        import get_models
        fetched = {os.path.basename(path) for _, path, _ in get_models.MODELS}
        self.assertTrue(all(repo in get_models.REVISIONS and len(get_models.REVISIONS[repo]) == 40 for repo, _, _ in get_models.MODELS))
        def nodes(path):
            with open(path, encoding="utf-8") as fh:
                return json.load(fh).values()
        loaded = {v for f in glob.glob(os.path.join(WORKFLOWS, "*.json")) for n in nodes(f)
                  for v in n["inputs"].values() if isinstance(v, str) and v.endswith(".safetensors")}
        self.assertTrue(loaded)
        self.assertEqual(loaded - fetched, set())
        with open(os.path.join(ROOT, "tools", "pod_setup.sh"), encoding="utf-8") as fh:
            self.assertIn('"$PACK/get_models.py" "$M"', fh.read())

    @unittest.skipUnless(COMFY and os.path.isdir(LTX), "set COMFYUI_DIR (and LTXVIDEO_DIR) to check against source")
    def test_classes_and_inputs_exist_in_source(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_workflows.py"), COMFY, LTX],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
