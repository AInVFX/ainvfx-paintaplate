"""routes.clear_live: a finished prompt's live previews leave ComfyUI's temp folder; other prompts' files stay."""
import os
import shutil
import tempfile
import unittest

import importlib

importlib.import_module("test_routes")  # its ComfyUI folders stand-in, so both files share one `routes` module
import routes  # noqa: E402


class LiveClear(unittest.TestCase):
    def test_a_finished_prompt_s_live_previews_leave_the_temp_folder(self):
        temp = tempfile.mkdtemp(prefix="live_")
        self.addCleanup(shutil.rmtree, temp, True)
        folder = os.path.join(temp, routes.LIVE_FOLDER)
        os.makedirs(folder)
        for name in ("p1_001.webp", "p1_002.webp", "p2_001.webp", "p1_notes.txt"):
            open(os.path.join(folder, name), "w").close()
        self.assertEqual(routes.clear_live("p1", temp), 2)
        self.assertEqual(sorted(os.listdir(folder)), ["p1_notes.txt", "p2_001.webp"])
        self.assertEqual(routes.clear_live("../p2", temp), 0)  # not a prompt id: nothing leaves
        self.assertEqual(routes.clear_live("p3", os.path.join(temp, "none")), 0)  # no live preview yet


if __name__ == "__main__":
    unittest.main()
