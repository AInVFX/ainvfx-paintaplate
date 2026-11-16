"""The seconds of each node of a job in the table of `tests/hdr_plate.py finish`: a node runs from its « executing »
message to the next one, whatever the messages between them, and the rows add up to the job's seconds."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
import hdr_plate  # noqa: E402

# A job posted at 0 s and ended at 550.5 s: a sampler (node 7) that sends progress, a decode (node 12), the end.
EVENTS = [(1.0, "execution_start", None), (1.5, "execution_cached", None), (2.0, "executing", "7"), (3.0, "progress", "7"),
          (60.0, "progress", "7"), (500.0, "progress", "7"), (509.0, "executing", "12"), (540.0, "executed", "12"),
          (550.0, "executing", None)]
PROMPT = {"7": {"class_type": "SamplerCustomAdvanced"}, "12": {"class_type": "VAEDecodeTiled"}}


class NodeSeconds(unittest.TestCase):
    def test_a_node_runs_from_its_start_to_the_next_start(self):
        spent = hdr_plate.node_seconds(EVENTS, 0.0, 550.5)
        self.assertAlmostEqual(spent["7"], 507.0)
        self.assertAlmostEqual(spent["12"], 41.0)
        self.assertAlmostEqual(spent[hdr_plate.BEFORE], 2.0)
        self.assertAlmostEqual(spent[hdr_plate.AFTER], 0.5)

    def test_the_rows_add_up_to_the_jobs_seconds(self):
        spent = hdr_plate.node_seconds(EVENTS, 0.0, 550.5)
        for top in (1, 8):
            rows = hdr_plate.node_rows(spent, PROMPT, top)
            self.assertAlmostEqual(sum(s for _, s in rows), 550.5)
        self.assertEqual([label for label, _ in hdr_plate.node_rows(spent, PROMPT, 1)],
                         ["SamplerCustomAdvanced", "1 other node", "Before the first node", "After the last node"])


if __name__ == "__main__":
    unittest.main()
