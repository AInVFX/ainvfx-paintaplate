"""The fluid workflow at the size the page asks for, and the first frame it writes (web/workflows/fluid.json)."""
import os
import sys
import unittest

from _env import ROOT

WORKFLOWS = os.path.join(ROOT, "web", "workflows")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_workflows  # noqa: E402


def slot_inputs(prompt):
    """Each slot's node and input: {slot: (node id, input name)}."""
    return {slot: (nid, key) for nid, node in prompt.items() for key, slot in node.get("_meta", {}).get("slots", {}).items()}


def of_class(prompt, cls):
    return [nid for nid, node in prompt.items() if node["class_type"] == cls]


class FluidSize(unittest.TestCase):
    def test_width_and_height_scale_the_blank_plate_and_every_size_follows(self):
        """`width` and `height` scale the blank plate, and 0 by 0 keeps its own size. The control video, the empty latent
        and the live previews read the scaled size, so a pass at the shot preview's size runs whole at that size."""
        prompt, _, _ = build_workflows.load("fluid", WORKFLOWS)
        slots = slot_inputs(prompt)
        (w, w_key), (h, h_key) = slots["width"], slots["height"]
        self.assertEqual(w, h, "one node takes both")
        scale = prompt[w]
        self.assertEqual((scale["class_type"], scale["inputs"][w_key], scale["inputs"][h_key]), ("ImageScale", 0, 0))
        frames = prompt[scale["inputs"]["image"][0]]  # the blank plate's frames in the model space
        self.assertEqual((frames["class_type"], frames["inputs"]["image"][0]), ("PaintAPlate_ColorSpace", of_class(prompt, "PaintAPlate_LoadPlate")[0]))
        sizes = of_class(prompt, "GetImageSize")
        self.assertEqual(len(sizes), 1)
        self.assertEqual(prompt[sizes[0]]["inputs"]["image"][0], w, "the one size every node reads is the scaled plate's")
        for cls, keys in (("PaintAPlate_KeyframeVideo", ("width", "height", "frames")), ("EmptyLTXVLatentVideo", ("width", "height", "length"))):
            node = prompt[of_class(prompt, cls)[0]]
            self.assertEqual([node["inputs"][k][0] for k in keys], sizes * 3, cls)


class FluidFirstFrame(unittest.TestCase):
    def test_the_first_frame_is_frame_0_of_the_decoded_shot(self):
        """`first`: frame 0 of the decoded shot as a PNG, under `first_prefix`, as `ingest` writes a plate's first frame.
        The preview movie and the shot as ProRes 4444 XQ come from the same decoded frames."""
        prompt, _, outs = build_workflows.load("fluid", WORKFLOWS)
        save = prompt[outs["first"]]
        self.assertEqual((save["class_type"], save["_meta"]["title"]), ("SaveImage", "First frame"))
        self.assertEqual(slot_inputs(prompt)["first_prefix"], (outs["first"], "filename_prefix"))
        pick = prompt[save["inputs"]["images"][0]]
        self.assertEqual((pick["class_type"], pick["inputs"]["batch_index"], pick["inputs"]["length"]), ("ImageFromBatch", 0, 1))
        decoded = pick["inputs"]["image"][0]
        self.assertEqual(prompt[decoded]["class_type"], "VAEDecodeTiled")
        self.assertEqual(prompt[outs["plate"]]["inputs"]["images"][0], decoded)



class FluidControlMovie(unittest.TestCase):
    def test_the_control_movie_says_what_it_shows(self):
        """`control`: the keyframes on black as LTX reads them, a movie that the GPU cases compare with the shot."""
        prompt, _, outs = build_workflows.load("fluid", WORKFLOWS)
        movie = prompt[outs["control"]]
        self.assertEqual((movie["class_type"], movie["_meta"]["title"]), ("PaintAPlate_SaveMovie", "Control video as a movie: the keyframes on black"))
        self.assertEqual(prompt[movie["inputs"]["images"][0]]["class_type"], "PaintAPlate_KeyframeVideo")

if __name__ == "__main__":
    unittest.main()
