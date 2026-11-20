"""A GPU case's Export (tests/ui_live.py): the tool ticks the review movie, and with --graph the ComfyUI graph, only
when the Export dialog offers the box. The dialog hides the review movie for a relit result in HDR, and both boxes for a
fluid shot alone and for a plate alone; a hidden box cannot be ticked, so a case that tried would end there."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui_live  # noqa: E402


class Page:
    """What the tool reads of the Export dialog: the boxes on show. Ticking a hidden box fails, as in the browser."""
    def __init__(self, shown):
        self.shown, self.ticked = set(shown), []

    def is_visible(self, box):
        return box in self.shown

    def check(self, box):
        if box not in self.shown:
            raise TimeoutError(f"{box} is hidden")
        self.ticked.append(box)


class Export(unittest.TestCase):
    def test_edits_get_the_review_movie_and_the_graph_when_asked(self):
        page = Page(["#x-review", "#x-graph"])
        self.assertEqual(ui_live.tick_offered(page), ["#x-review"])
        self.assertEqual(ui_live.tick_offered(Page(["#x-review", "#x-graph"]), graph=True), ["#x-review", "#x-graph"])
        self.assertEqual(page.ticked, ["#x-review"])

    def test_a_relit_result_in_hdr_has_no_review_movie(self):
        self.assertEqual(ui_live.tick_offered(Page(["#x-graph"])), [])
        self.assertEqual(ui_live.tick_offered(Page(["#x-graph"]), graph=True), ["#x-graph"])

    def test_a_fluid_shot_alone_and_a_plate_alone_offer_neither(self):
        self.assertEqual(ui_live.tick_offered(Page([]), graph=True), [])


if __name__ == "__main__":
    unittest.main()
