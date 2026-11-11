"""The page in a headless browser against the mock ComfyUI: one test per flow of tests/ui_mock.py.

The first test runs every flow once, side by side (one per CPU), each with its own time limit. Every test then reports its
own flow: a failure names its flow and shows its last lines, and the other flows still run. It needs playwright with a
browser. In CI the page job runs it, one part of the flows per machine (PAGE_SHARD, as "2/4"); the unit job leaves it
to the page job.

One flow alone, its lines as they come: python tests/ui_mock.py --only keys
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

import ui_mock
from _env import CI, ROOT, missing

SHARD = os.environ.get("PAGE_SHARD", "")


def setUpModule():
    if CI and not SHARD:
        raise unittest.SkipTest("in CI the page job runs the page tests, in shards (PAGE_SHARD)")
    if importlib.util.find_spec("playwright") is None:
        missing("pip install playwright && python -m playwright install chromium")


class Page(unittest.TestCase):
    results = None  # every flow's result, from one run of tests/ui_mock.py

    @classmethod
    def result(cls, name):
        if cls.results is None:
            with tempfile.TemporaryDirectory() as folder:
                out = os.path.join(folder, "results.json")
                run = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "ui_mock.py"), "--json", out, *(["--shard", SHARD] if SHARD else [])],
                                     capture_output=True, text=True)  # no limit here: ui_mock.py stops a flow past its own
                if not os.path.exists(out):
                    raise RuntimeError("tests/ui_mock.py ended with no results:\n" + (run.stdout + run.stderr)[-3000:])
                with open(out) as f:
                    cls.results = {r["flow"]: r for r in json.load(f)}
        return cls.results[name]


def flow_test(name):
    def test(self):
        r = self.result(name)
        if r["failure"]:
            self.fail(f"{r['failure']}\n" + "\n".join(r["lines"][-40:]))
    test.__doc__ = f"python tests/ui_mock.py --only {name}"
    return test


for flow in ui_mock.flow_names(SHARD):
    setattr(Page, f"test_{flow}", flow_test(flow))

if __name__ == "__main__":
    unittest.main(verbosity=2)
