"""cache.py: the unused cache under output/paintaplate, what stays (the folders a saved scene names, the folders the page
keeps, an export, the scenes), and the job index records that go with their files."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import cache  # noqa: E402

FILES = {
    "paintaplate/aaa/proxy_00001_.mp4": 10,
    "paintaplate/aaa/v1/full/shot/f_00001_.png": 100,
    "paintaplate/aaa/v1/export/horse.mp4": 50,
    "paintaplate/aaa/v1/horse_paintaplate_v1__export-matte.zip": 40,
    "paintaplate/aaa/v2/full/shot/f_00001_.png": 200,
    "paintaplate/aaa/edits/e1_00001_.png": 30,
    "paintaplate/bbb/proxy_00001_.mp4": 20,
    "paintaplate/bbb/v1/full/shot/f_00001_.png": 300,
    "paintaplate/edits/edit_00001_.png": 5,  # outside any plate's folder
}


def record(sub):
    return json.dumps({"workflow": "shot", "outputs": {"9": {"images": [{"filename": "f_00001_.png", "subfolder": sub, "type": "output"}]}}})


class Cache(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="cache_")
        self.addCleanup(shutil.rmtree, self.out, True)
        texts = {rel: "x" * size for rel, size in FILES.items()}
        texts["paintaplate/scenes/horse.paintaplate.json"] = json.dumps({"folders": ["paintaplate/aaa", "paintaplate/aaa/v2", "paintaplate/aaa/edits"]})
        texts["paintaplate/jobs/k1.json"] = record("paintaplate/aaa/v2/full/shot")
        texts["paintaplate/jobs/k2.json"] = record("paintaplate/bbb/v1/full/shot")
        for rel, text in texts.items():
            os.makedirs(os.path.dirname(os.path.join(self.out, rel)), exist_ok=True)
            with open(os.path.join(self.out, rel), "w") as fh:
                fh.write(text)

    def rel(self, paths):
        return sorted(os.path.relpath(p, self.out).replace(os.sep, "/") for p in paths)

    def test_the_unused_cache_is_what_no_scene_and_no_plate_on_screen_names_and_never_an_export(self):
        self.assertEqual(self.rel(p for p, _ in cache.unused(self.out)),
                         ["paintaplate/aaa/v1/full/shot/f_00001_.png", "paintaplate/bbb/proxy_00001_.mp4", "paintaplate/bbb/v1/full/shot/f_00001_.png"])
        self.assertEqual(self.rel(p for p, _ in cache.unused(self.out, keep=["paintaplate/bbb", "paintaplate/bbb/v1"])),
                         ["paintaplate/aaa/v1/full/shot/f_00001_.png"])

    def test_clear_removes_it_with_its_empty_folders_and_the_job_records_whose_files_went(self):
        self.assertEqual(cache.clear(self.out), (3, 420))
        self.assertEqual(self.rel(os.path.join(t, n) for t, _, names in os.walk(self.out) for n in names),
                         ["paintaplate/aaa/edits/e1_00001_.png", "paintaplate/aaa/proxy_00001_.mp4", "paintaplate/aaa/v1/export/horse.mp4",
                          "paintaplate/aaa/v1/horse_paintaplate_v1__export-matte.zip", "paintaplate/aaa/v2/full/shot/f_00001_.png",
                          "paintaplate/edits/edit_00001_.png", "paintaplate/jobs/k1.json", "paintaplate/scenes/horse.paintaplate.json"])
        self.assertFalse(os.path.exists(os.path.join(self.out, "paintaplate", "bbb")))
        self.assertEqual(cache.clear(self.out), (0, 0))


if __name__ == "__main__":
    unittest.main()
