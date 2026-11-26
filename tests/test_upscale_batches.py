"""The export and the preview composite hold the composite once, as the review does: each writer takes its batch as it is
and saves the plate's own frames, leaving Load Plate's padding out by `frames`. No writer reads a clone of the shot."""
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(name):
    with open(os.path.join(ROOT, "web", "workflows", f"{name}.json")) as f:
        return json.load(f)


class NoClone(unittest.TestCase):
    def test_no_writer_of_the_export_or_the_preview_composite_reads_a_clone(self):
        for name in ("export", "comp"):
            graph = load(name)
            self.assertFalse([n for n in graph.values() if n["class_type"] == "ImageFromBatch"], name)

    def test_every_writer_saves_the_plates_own_frames(self):
        for name, writers in (("export", 2), ("comp", 2)):  # the matte's frames and movie; Save Plate leaves the padding out by the plate's own frame count
            graph = load(name)
            plate = next(k for k, n in graph.items() if n["class_type"] == "PaintAPlate_LoadPlate" and n["_meta"].get("title") == "Plate")
            saved = [n for n in graph.values() if n["class_type"] in ("PaintAPlate_SaveFrames", "PaintAPlate_SaveMovie")]
            self.assertEqual(len(saved), writers, name)
            for n in saved:
                self.assertEqual(n["inputs"].get("frames"), [plate, 4], f"{name}: {n['_meta']['title']}")


if __name__ == "__main__":
    unittest.main()
