"""A GPU case's Export (tests/ui_live.py): the tool ticks the Preview stage, and with --graph the ComfyUI graph, only when
the Export dialog offers the tick. A render with no preview has no Preview tick, and a plate alone has no graph; a hidden
tick cannot be ticked, so a case that tried would end there."""
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
    def test_the_preview_and_the_graph_when_asked(self):
        page = Page(["#x-preview", "#x-graph"])
        self.assertEqual(ui_live.tick_offered(page), ["#x-preview"])
        self.assertEqual(ui_live.tick_offered(Page(["#x-preview", "#x-graph"]), graph=True), ["#x-preview", "#x-graph"])
        self.assertEqual(page.ticked, ["#x-preview"])

    def test_a_render_with_no_preview_has_no_preview_tick(self):
        self.assertEqual(ui_live.tick_offered(Page(["#x-graph"])), [])
        self.assertEqual(ui_live.tick_offered(Page(["#x-graph"]), graph=True), ["#x-graph"])

    def test_a_plate_alone_with_no_preview_offers_neither(self):
        self.assertEqual(ui_live.tick_offered(Page([]), graph=True), [])


if __name__ == "__main__":
    unittest.main()
