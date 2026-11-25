"""The page job's line of flow times: its tag, then one JSON object with the shard, the CPUs that ran its flows side by
side, its wall time and each flow's seconds. The page job prints it (tests/test_ui_mock.py), so a job's log gives the
times that the flows are cut into shards by."""
import json
import unittest

import ui_mock


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


if __name__ == "__main__":
    unittest.main()
