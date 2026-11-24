"""The models' licences in web/models.json: one name per licence and one licence per name, each linked to its own text.
Lightricks' LTX-2 repository holds two community licences: LICENSE-2_x, the LTX-2.x Community License Agreement, for LTX
2.5 and the models built on it, and LICENSE-2, the LTX-2 Community License Agreement, for LTX 2.3 and the models built on
it. Each takes the short name of Lightricks' own cards. Its LICENSE file is the Apache 2.0 licence of its code."""
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LTX = "https://github.com/Lightricks/LTX-2/blob/main/"
NAMES = {LTX + "LICENSE-2_x": "LTX-2.x Community License", LTX + "LICENSE-2": "LTX-2 Community License"}


class Licences(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "web", "models.json"), encoding="utf-8") as fh:
            cls.models = json.load(fh)["models"]

    def test_one_link_per_licence_and_one_licence_per_link(self):
        links, names = {}, {}
        for m in self.models:
            links.setdefault(m["licence"], set()).add(m["licence_url"])
            names.setdefault(m["licence_url"], set()).add(m["licence"])
        self.assertEqual({k: sorted(v) for k, v in links.items() if len(v) > 1}, {}, "a licence named with two links")
        self.assertEqual({k: sorted(v) for k, v in names.items() if len(v) > 1}, {}, "a link given two names")

    def test_each_ltx_licence_has_one_name_and_its_own_text(self):
        wrong = {m["id"]: (m["licence"], m["licence_url"]) for m in self.models
                 if m["licence_url"].startswith(LTX) and NAMES.get(m["licence_url"]) != m["licence"]}
        self.assertEqual(wrong, {}, "an LTX model whose licence name is not the one of the text it links")


if __name__ == "__main__":
    unittest.main()
