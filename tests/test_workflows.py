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
                  "matte": {"follow", "frames", "movie"}, "comp": {"video"}, "review": {"review", "frames", "view"},
                  "export": {"export", "exr", "matte", "matte_movie"}, "warm": {"frame"},
                  "fluid": {"plate", "video", "control"}, "hdr": {"hdr", "movie"}}
        for name, keys in wanted.items():
            self.assertEqual(set(build_workflows.load(name, WORKFLOWS)[2]), keys, name)

    def test_every_movie_takes_the_native_size(self):
        """Every movie the page plays has the movie_width and movie_height slots: the page sends the plate's native size."""
        for name in build_workflows.NAMES:
            prompt, slots, _ = build_workflows.load(name, WORKFLOWS)
            movies = [k for k, n in prompt.items() if n["class_type"] == "PaintAPlate_SaveMovie"]
            for k in movies:
                self.assertIn([k, "width"], [list(t) for t in slots["movie_width"]], name)
                self.assertIn([k, "height"], [list(t) for t in slots["movie_height"]], name)

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


class ViewerMovies(unittest.TestCase):
    """An image sequence plays 8-bit movies in log values (ACEScct): its review's viewer movie and its SDR-to-HDR movie."""

    def test_review_viewer_movie_goes_with_the_nodes_that_fed_it(self):
        _, _, outputs = build_workflows.load("review")
        seq = build_workflows.fill("review", {"view_prefix": "p/v1/review/view", "view_space": "ACEScct", "frames_prefix": "p/v1/review/frames"})
        video = build_workflows.fill("review", {"view_prefix": "", "frames_prefix": ""})
        self.assertIn(outputs["view"], seq)
        self.assertNotIn(outputs["view"], video)
        used = {str(v[0]) for n in video.values() for v in n["inputs"].values() if isinstance(v, list)}
        idle = [n["class_type"] for nid, n in video.items() if nid not in used and "output" not in n.get("_meta", {})]
        self.assertEqual(idle, [], "a dropped link leaves no node that feeds nothing")
        conv = seq[str(seq[outputs["view"]]["inputs"]["images"][0])]  # Save Movie scales it to the size the page sends
        self.assertEqual(conv["inputs"]["destination"], "ACEScct")

    def test_hdr_writes_a_log_movie_beside_its_frames(self):
        _, _, outputs = build_workflows.load("hdr")
        wf = build_workflows.fill("hdr", {"view_space": "ACEScct", "video_prefix": "p/fluid_v1/hdr_movie", "movie_fps": 25.0})
        movie = wf[outputs["movie"]]
        self.assertEqual((movie["class_type"], movie["inputs"]["fps"]), ("PaintAPlate_SaveMovie", 25.0))
        conv = wf[str(movie["inputs"]["images"][0])]
        self.assertEqual((conv["inputs"]["source"], conv["inputs"]["destination"]), ("ACEScg", "ACEScct"))

    def test_hdr_decodes_in_128_frame_temporal_tiles(self):
        """64-frame temporal tiles with 8 of overlap made a 0.32-stop jump at frame 56 of a 121-frame HDR shot (2 Nov)."""
        prompt, _, _ = build_workflows.load("hdr")
        tiled = [n["inputs"] for n in prompt.values() if n["class_type"] == "VAEDecodeTiled"]
        self.assertEqual([(t["temporal_size"], t["temporal_overlap"]) for t in tiled], [(128, 32)])


class MemorySlots(unittest.TestCase):
    def test_the_memory_profile_slots_default_to_the_large_cards_values(self):
        """`tile` and `guide_tiled` (logic.memoryProfile on the page): unfilled, a workflow runs as on a large card."""
        import json
        folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web", "workflows")
        for name, tiles, guides in (("clean", 0, 1), ("cleanup", 2, 0), ("shot", 1, 1), ("fluid", 1, 1), ("hdr", 1, 1)):
            with open(os.path.join(folder, f"{name}.json")) as f:
                prompt = json.load(f)
            slots = {slot: (node["class_type"], node["inputs"][key]) for node in prompt.values() for key, slot in node.get("_meta", {}).get("slots", {}).items()}
            tile = [n for n in prompt.values() if n.get("_meta", {}).get("slots", {}).get("tile_size") == "tile"]
            guide = [n for n in prompt.values() if n.get("_meta", {}).get("slots", {}).get("use_tiled_encode") == "guide_tiled"]
            self.assertEqual((len(tile), len(guide)), (tiles, guides), name)
            self.assertTrue(all(n["inputs"]["tile_size"] == 512 for n in tile), name)
            self.assertTrue(all(n["inputs"]["use_tiled_encode"] is False for n in guide), name)
            self.assertEqual("tile" in slots, bool(tiles), name)
