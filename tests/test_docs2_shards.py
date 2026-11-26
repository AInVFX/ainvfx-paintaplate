"""The page tests' shards, cut by time. The page job prints one line of flow times (tests/test_ui_mock.py): its tag, then one
JSON object with the shard, the CPUs that ran its flows side by side, its wall time and each flow's seconds. Those lines
refresh tests/page_seconds.json, and the cut reads that file: every flow in one shard, the shards close in time, the
longest flows first. With DOCS_COMPLETE=1, the closing check before main, the file and the flows also name each other."""
import json
import os
import re
import statistics
import unittest

import ui_mock

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "..", ".github", "workflows", "tests.yml"), encoding="utf-8") as fh:
    PARTS = len(re.search(r"shard: \[([\d, ]+)\]", fh.read()).group(1).split(","))  # the page job's matrix


class SecondsLine(unittest.TestCase):
    def test_the_line_holds_each_flow_s_seconds(self):
        rows = [{"flow": "keys", "checks": 3, "seconds": 12.3, "failure": None, "lines": ["  ok   a"]},
                {"flow": "pipeline", "checks": 9, "seconds": 140.0, "failure": "a check failed", "lines": []}]
        tag, _, body = ui_mock.seconds_line(rows, "2/6", 301.04).partition(" ")
        self.assertEqual(tag, "PAGE_SECONDS")
        line = json.loads(body)
        self.assertEqual(line["flows"], {"keys": 12.3, "pipeline": 140.0}, "a failed flow keeps its time")
        self.assertEqual((line["shard"], line["wall"]), ("2/6", 301.0))
        self.assertGreaterEqual(line["cpus"], 1)


    def test_a_refresh_reads_every_job_s_line(self):
        log = "\n".join(["job 1\tstep\t2026-01-01T00:00:00Z " + ui_mock.seconds_line([{"flow": "keys", "seconds": 12.3}], "1/2", 20),
                         ui_mock.seconds_line([{"flow": "pipeline", "seconds": 140.0}], "2/2", 150), "another line"])
        self.assertEqual(ui_mock.read_seconds(log), {"keys": 12.3, "pipeline": 140.0})


class Cut(unittest.TestCase):
    def setUp(self):
        self.flows = ui_mock.flow_names()
        self.seconds = ui_mock.flow_seconds(self.flows)

    def test_every_flow_is_in_one_shard(self):
        for parts in (4, PARTS):
            cut = [ui_mock.flow_names(f"{k}/{parts}") for k in range(1, parts + 1)]
            self.assertEqual(sorted(sum(cut, [])), sorted(self.flows), f"{parts} parts")

    def test_the_shards_end_close_together(self):
        sums = [sum(self.seconds[f] for f in ui_mock.flow_names(f"{k}/{PARTS}")) for k in range(1, PARTS + 1)]
        self.assertLessEqual(max(sums) - min(sums), statistics.median(self.seconds.values()),
                             f"the shards' seconds: {[round(t) for t in sums]}")

    def test_the_longest_flows_start_first(self):
        for names in (self.flows, ui_mock.flow_names(f"2/{PARTS}")):
            self.assertEqual(names, sorted(names, key=lambda f: (-self.seconds[f], f)))

    def test_a_flow_with_no_time_takes_the_median(self):
        known = ui_mock.flow_seconds(["no_such_flow"])
        self.assertEqual(known["no_such_flow"], statistics.median(json.load(open(ui_mock.SECONDS)).values()))

    @unittest.skipUnless(os.environ.get("DOCS_COMPLETE") == "1", "the closing check before main: DOCS_COMPLETE=1")
    def test_every_flow_has_a_time(self):
        with open(ui_mock.SECONDS, encoding="utf-8") as fh:
            known = set(json.load(fh))
        self.assertEqual(sorted(set(self.flows) - known), [], "these flows have no time: refresh tests/page_seconds.json (TESTING.md, CI)")
        self.assertEqual(sorted(known - set(self.flows)), [], "tests/page_seconds.json names flows that do not exist")


if __name__ == "__main__":
    unittest.main()
