"""SDR to HDR on a plate with no edit: the plate is its own SDR shot, brought into the model space at the working size,
and its HDR frames come back at the plate's size and frame count. A shot from the shot pass goes through as before."""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path[:0] = [REPO, os.path.join(REPO, "tools")]
import build_workflows  # noqa: E402


def titled(prompt, title):
    found = [nid for nid, n in prompt.items() if n.get("_meta", {}).get("title", n.get("title")) == title]
    assert len(found) == 1, (title, found)
    return found[0]


def filled(values):
    wf = build_workflows.fill("hdr", values)
    return wf[0] if isinstance(wf, tuple) else wf


class HdrOnAPlate(unittest.TestCase):
    def setUp(self):
        self.prompt = build_workflows.load("hdr")[0]

    def test_a_shot_passes_through(self):
        """At their defaults the new slots pass a shot on as it is: Color Space (OCIO) from @model to @model returns its
        input, and core's Upscale Image returns its input at 0 x 0."""
        p = self.prompt
        conv = p[titled(p, "SDR shot in the model space")]["inputs"]
        self.assertEqual((conv["source"], conv["destination"]), ("@model", "@model"))
        for title in ("SDR shot at the working size", "HDR frames at the plate's size"):
            n = p[titled(p, title)]
            self.assertEqual((n["class_type"], n["inputs"]["width"], n["inputs"]["height"]), ("ImageScale", 0, 0))

    def test_a_plate_fills_the_slots(self):
        wf = filled({"path": "plates/desk.mp4", "color_space": "sRGB - Display", "width": 1920, "height": 1088,
                     "plate_width": 1920, "plate_height": 1080})
        self.assertEqual(wf[titled(wf, "SDR shot in the model space")]["inputs"]["source"], "sRGB - Display")
        work = wf[titled(wf, "SDR shot at the working size")]["inputs"]
        back = wf[titled(wf, "HDR frames at the plate's size")]["inputs"]
        self.assertEqual((work["width"], work["height"], back["width"], back["height"]), (1920, 1088, 1920, 1080))
        self.assertEqual(back["upscale_method"], "bilinear")  # no overshoot above a highlight, no value below 0

    def test_the_guide_and_keep_black_read_the_sdr_shot(self):
        p = self.prompt
        work = titled(p, "SDR shot at the working size")
        guide = p[titled(p, "Guide: the shot from sRGB to ACEScct")]["inputs"]["image"]
        black = [n for n in p.values() if n["class_type"] == "PaintAPlate_KeepBlack"][0]["inputs"]["sdr"]
        self.assertEqual((guide[0], black[0]), (work, work))

    def test_the_result_keeps_the_plates_frame_count(self):
        p = self.prompt
        load = titled(p, "Shot (SDR)")
        savers = [n for n in p.values() if n["class_type"] in ("PaintAPlate_SaveFrames", "PaintAPlate_SaveMovie")]
        self.assertEqual(len(savers), 2)
        for n in savers:  # Load Plate's 'frames': the plate's own count, without the 8n+1 padding
            self.assertEqual(n["inputs"]["frames"], [load, 4])


if __name__ == "__main__":
    unittest.main()
