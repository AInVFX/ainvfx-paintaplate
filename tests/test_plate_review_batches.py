"""The review job holds the full-size composite once: its writers (the review movie, the EXR frames, the viewer's movie)
take it as it is, each saving the plate's own frames and converting each frame as it saves it."""
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRITERS = {"PaintAPlate_SaveMovie", "PaintAPlate_SaveFrames"}


class ReviewBatches(unittest.TestCase):
    def test_the_composite_goes_straight_to_its_writers(self):
        with open(os.path.join(ROOT, "web", "workflows", "review.json")) as f:
            graph = json.load(f)
        composite = [k for k, n in graph.items() if n.get("class_type") == "PaintAPlate_CompositeFrames"]
        self.assertEqual(len(composite), 1)
        load = next(k for k, n in graph.items() if n.get("class_type") == "PaintAPlate_LoadPlate" and n.get("_meta", {}).get("title") == "Plate")
        readers = [n for n in graph.values() if any(v == [composite[0], 0] for v in n.get("inputs", {}).values())]
        self.assertEqual(sorted(n["class_type"] for n in readers), ["PaintAPlate_SaveFrames", "PaintAPlate_SaveMovie", "PaintAPlate_SaveMovie"])
        for n in readers:
            self.assertEqual(n["inputs"].get("frames"), [load, 4], n["_meta"]["title"])
        movies = [n for n in readers if n["class_type"] == "PaintAPlate_SaveMovie"]
        self.assertTrue(all("source" in n["inputs"] and "destination" in n["inputs"] for n in movies))


if __name__ == "__main__":
    unittest.main()
