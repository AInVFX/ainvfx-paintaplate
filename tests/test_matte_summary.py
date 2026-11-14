"""Follow Matte's summary (matte workstream, wave 5: P3)."""
import os, sys, unittest
from _env import require
require("numpy", "scipy")
import numpy as np  # noqa: E402
from scipy import ndimage  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mathops as m  # noqa: E402


def scene(front_cols, walks=False, n=121, h=182, w=320):
    """The cow scenes of test_mathops.py: a camera that pans 2 px per frame, a painted object that stands still in the
    scene (or, with `walks`, walks with what stands in front from frame 28), and a front object still in the frame."""
    rng = np.random.default_rng(12 if walks else 11)
    land = ndimage.gaussian_filter(rng.random((h, w + 2 * n, 3)).astype(np.float32), (2, 2, 0))
    land = np.clip(0.5 + 3 * (land - land.mean()), 0, 1)
    base = np.stack([land[:, 2 * t:2 * t + w] for t in range(n)])
    front = (slice(30, 170), front_cols)
    base[(slice(None),) + front] = (0.55, 0.25, 0.10)
    shot, sam, shown = base.copy(), np.zeros((n, h, w), np.float32), np.zeros((n, h, w), bool)
    for t in range(n):
        x = 213 - 2 * (min(t, 28) if walks else t)
        shown[t, 96:116, max(x, 0):max(x + 86, 0)] = True
        if not walks:
            shown[(t,) + front] = False  # behind what stands in front
        shot[t][shown[t]] = (0.9, 0.85, 0.8)
        if t < 11:
            sam[t, 63:149, 207 - 2 * t:305 - 2 * t] = 1  # the paint zone it was given
        elif walks or t < 50:
            sam[t] = shown[t]
    return sam, shown, shot, base, front


class Summary(unittest.TestCase):
    """The ratio to the SAM mask is read only on frames where SAM 3.1 returned a mask; the others are counted apart."""

    def test_frames_with_no_mask_from_sam_are_counted_apart(self):
        sam, shown, shot, base, front = scene(slice(60, 184))  # SAM loses the object on frame 50; the shot's changes bring it back
        _, summary = m.follow_matte(sam, len(sam), sam[0], shot=shot, base=base, zone=1 / 16, threshold=0.1, element=shown[0].astype(np.float32))
        found = __import__("re").search(r"\n  Added: areas the shot changed next to the object, on \d+ frames? \(up to (\d+\.\d)x the SAM mask; (\d+) frames? with no SAM mask\)\.", summary)
        self.assertIsNotNone(found, summary)  # at the commit before: « up to 1301.0 times SAM's mask », a count of pixels
        self.assertLess(float(found.group(1)), 5.0)
        self.assertGreater(int(found.group(2)), 0)


class Form(unittest.TestCase):
    """A headline, the warnings next, then one detail per line, only those."""

    def test_example_word_for_word(self):
        text = "Paint matte (640x352): " + m.follow_summary(121, 106, strays=2, added=112, most=30.4, alone=15, moved=1,
                                                          largest=(33.1, 65), above=(25, 90))
        self.assertEqual(text, "\n".join([
            "Paint matte (640x352): tracked on 106 of 121 frames.",
            "  Warning: matte above 3x the object from frame 25 to 90 (up to 33.1x at frame 65). Check the composite there.",
            "  Removed: SAM detections too far from the object, on 2 frames.",
            "  Added: areas the shot changed next to the object, on 112 frames (up to 30.4x the SAM mask; 15 frames with no SAM mask).",
            "  Object moves from frame 1: occlusion by the plate not tested."]))

    def test_only_what_happened(self):
        self.assertEqual(m.follow_summary(121, 121, largest=(1.2, 31)), "tracked on 121 of 121 frames.")  # no warning, no line
        self.assertEqual(m.follow_summary(6, largest=(60.0, 0)).split("\n"), [
            "tracked on 0 of 6 frames.", "  Warning: matte 60.0x the object at frame 0. Check the composite there.",
            "  Held: first-frame mask, on every frame."])
        one = m.follow_summary(12, 11, held=1, added=1, most=1.5, largest=(1.5, 3))
        self.assertIn("\n  Held: last matte, on 1 frame with no SAM mask.", one)  # one frame, not « 1 frames »
        self.assertIn("\n  Added: areas the shot changed next to the object, on 1 frame (up to 1.5x the SAM mask).", one)

    def test_every_line_is_one_technical_line(self):
        text = m.follow_summary(121, 100, zones=9, placed=23, strays=2, held=4, added=10, most=2.0, alone=1, guarded=2,
                                smoothed=3, moved=5, fronts=30, gone=5, largest=(3.5, 40), above=(30, 44), cleaned=3,
                                left=(50, 56), flicker=(5, 0.59, 53))
        lines = text.split("\n")
        self.assertEqual(len(lines), 16)
        for line in lines[1:]:
            self.assertRegex(line, r"^  [A-Z][^\n]*\.$")
            self.assertNotRegex(line, r"\b(so|what it found|is asked|times|frame\(s\))\b")


class Choices(unittest.TestCase):
    """The approved forms: a warning names its range, the flicker is a detail line, the tooltips end with a full stop."""

    def test_warning_names_its_range(self):
        self.assertIn("\n  Warning: matte 4.2x the object at frame 65. Check the composite there.",
                      m.follow_summary(121, 100, largest=(4.2, 65), above=(65, 65)))  # one frame above 3x
        self.assertNotIn("Warning", m.follow_summary(121, 100, largest=(2.9, 65), above=None))

    def test_flicker_is_the_last_detail_line(self):
        self.assertTrue(m.follow_summary(10, 10, flicker=(5, 0.59, 53)).endswith(
            "\n  Flicker: pieces of the matte for 3 frames or fewer, on 5 frames (up to 59% of the matte at frame 53)."))
        self.assertTrue(m.follow_summary(10, 10, gone=2, flicker=(1, 0.042, 7)).endswith(
            "\n  Flicker: pieces of the matte for 3 frames or fewer, on 1 frame (up to 4.2% of the matte at frame 7)."))

    def test_follow_matte_reads_the_flicker(self):
        sam, shown, shot, base, front = scene(slice(60, 184))
        matte, summary = m.follow_matte(sam, len(sam), sam[0], shot=shot, base=base, zone=1 / 16, threshold=0.1, element=shown[0].astype(np.float32))
        self.assertEqual("\n  Flicker: " in summary, bool(m.matte_flicker(matte).any()))

    def test_follow_matte_tooltips(self):
        import os
        import re
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nodes.py")).read()
        tips = re.findall(r'tooltip="([^"]*)"', src[src.index("class FollowMatte"):src.index("class KeyframeVideo")])
        self.assertEqual(len(tips), 9)
        for tip in tips:
            self.assertTrue(tip.endswith("."), tip)
            self.assertNotIn("SAM's", tip)

