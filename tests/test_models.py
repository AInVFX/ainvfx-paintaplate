"""The models registry (web/models.json): every file get_models.py downloads has one entry with its licence, source and
revision, and every model file a workflow loads is in it."""
import glob
import json
import os
import sys
import unittest

from _env import ROOT
sys.path.insert(0, ROOT)
import get_models  # noqa: E402

REGISTRY = json.load(open(os.path.join(ROOT, "web", "models.json"), encoding="utf-8"))


class Models(unittest.TestCase):
    def test_every_download_has_an_entry_and_a_licence(self):
        by_file = {m["file"]: m for m in REGISTRY["models"]}
        self.assertEqual(len(by_file), len(REGISTRY["models"]), "one entry per file")
        for repo, path, _ in get_models.MODELS:
            name = os.path.basename(path)
            self.assertIn(name, by_file, f"{name} has no entry in web/models.json")
            m = by_file[name]
            self.assertEqual((m["repo"], m["revision"]), (repo, get_models.REVISIONS[repo]), name)
            for key in ("name", "use", "licence", "licence_url", "source"):
                self.assertTrue(m.get(key), f"{name}: no {key}")
        self.assertEqual(set(by_file), {os.path.basename(p) for _, p, _ in get_models.MODELS}, "no entry without its download")

    def test_every_file_a_workflow_loads_is_registered(self):
        files = {m["file"] for m in REGISTRY["models"]}
        for path in glob.glob(os.path.join(ROOT, "web", "workflows", "*.json")):
            with open(path, encoding="utf-8") as f:
                nodes = json.load(f).values()
            for node in nodes:
                for v in (node.get("inputs") or {}).values():
                    if isinstance(v, str) and v.endswith(".safetensors"):
                        self.assertIn(os.path.basename(v), files, f"{os.path.basename(path)} loads {v}")


if __name__ == "__main__":
    unittest.main()
