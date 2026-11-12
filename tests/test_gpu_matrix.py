"""tests/gpu_matrix.py: what it reads from a case's page log and from ComfyUI's history. tools/runpod_start.sh: what a
start keeps. No GPU and no browser."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gpu_matrix  # noqa: E402

LOG = """15:02:31ingest ef88a8f3: done in 2.0 s (10 nodes, 3 from ComfyUI's cache)
15:02:40edit 0a1b2c3d: done in 8.5 s (24 nodes, 16 previews)
15:02:41Render v1: Shot, preview took 41.2 s
15:03:30shot 99aa00bb: stopped after 12.0 s in SamplerCustomAdvanced (31 nodes, 3 previews)
15:03:31Memory profile large: 96 GB of VRAM, 188 GB of RAM. Every model loads now and stays loaded
"""


class Report(unittest.TestCase):
    def test_a_job_is_read_from_its_one_line(self):
        r = gpu_matrix.read_log(LOG)
        self.assertEqual([(j["name"], j["id"], j["seconds"], j["nodes"], j["cached"], j["previews"]) for j in r["jobs"]],
                         [("ingest", "ef88a8f3", 2.0, 10, 3, 0), ("edit", "0a1b2c3d", 8.5, 24, 0, 16)])
        self.assertEqual(r["previews"], 16)
        self.assertEqual(r["ended"], ["shot 99aa00bb: stopped after 12.0 s in SamplerCustomAdvanced (31 nodes, 3 previews)"])
        self.assertEqual(r["steps"], [("v1 Shot, preview", 41.2)])
        self.assertTrue(r["profile"].startswith("large (96 GB of VRAM"))

    def test_a_job_s_peak_is_read_between_its_start_and_its_end_in_the_history(self):
        history = {"ef88a8f3-1111": {"status": {"messages": [["execution_start", {"timestamp": 10000}], ["execution_cached", {"nodes": [], "timestamp": 10001}],
                                                             ["execution_success", {"timestamp": 13000}]]}},
                   "0a1b2c3d-2222": {"status": {"messages": [["execution_start", {"timestamp": 20000}], ["execution_error", {"timestamp": 20400}]]}},
                   "ffff0000-3333": {"status": {"messages": []}}}
        spans = gpu_matrix.job_spans(history)
        self.assertEqual(spans, {"ef88a8f3": (10.0, 13.0), "0a1b2c3d": (20.0, 20.4)})
        memory = gpu_matrix.Memory("http://127.0.0.1:9")  # no ComfyUI there: only the readings below are used
        memory.samples = [(9.0, 50, 5, 1), (10.5, 70, 8, 2), (12.0, 60, 9, 3), (14.0, 99, 99, 99), (21.0, 40, 4, 4)]
        self.assertEqual(memory.peak(*spans["ef88a8f3"]), [70, 9, 3])
        self.assertEqual(memory.peak(*spans["0a1b2c3d"]), [40, 4, 4], "a job shorter than a second: the reading nearest to its end")
        self.assertEqual(memory.peak(), [99, 99, 99], "a whole case")


@unittest.skipUnless(shutil.which("bash"), "tools/runpod_start.sh is a bash script")
class PodStart(unittest.TestCase):
    """tools/runpod_start.sh with stand-ins for the setup, ComfyUI, curl and nvidia-smi."""

    def test_a_start_keeps_the_log_of_the_comfyui_that_ran_before(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with tempfile.TemporaryDirectory() as tmp:
            tools, work, bins, venv = (os.path.join(tmp, *parts) for parts in (("pack", "tools"), ("work",), ("bin",), ("venv", "bin")))
            for folder in (tools, os.path.join(work, "ComfyUI"), bins, venv):
                os.makedirs(folder)
            shutil.copy(os.path.join(root, "tools", "runpod_start.sh"), tools)
            for file, text in ((os.path.join(tools, "pod_setup.sh"), 'echo "models done" > "$WORKDIR/models.log"'),
                               (os.path.join(bins, "curl"), '[ -e "$WORKDIR/up" ]'),  # ComfyUI answers once its stand-in has run
                               (os.path.join(bins, "nvidia-smi"), "echo 16000"),
                               (os.path.join(venv, "python"), 'echo "ComfyUI, run $RUN"; touch "$WORKDIR/up"')):
                with open(file, "w", encoding="utf-8") as f:
                    f.write("#!/bin/sh\n" + text + "\n")
                os.chmod(file, 0o755)
            env = {**os.environ, "WORKDIR": work, "VENV": os.path.dirname(venv), "PATH": bins + os.pathsep + os.environ["PATH"], "HF_TOKEN": "x"}

            def start(run):
                return subprocess.run(["bash", os.path.join(tools, "runpod_start.sh")], env={**env, "RUN": run}, stdin=subprocess.DEVNULL,
                                      capture_output=True, text=True, timeout=120).stdout

            def logs():
                return {name: open(os.path.join(work, name), encoding="utf-8").read().strip() for name in os.listdir(work) if name.startswith("comfyui.")}

            start("one")
            self.assertEqual(logs(), {"comfyui.log": "ComfyUI, run one"})
            os.remove(os.path.join(work, "up"))  # ComfyUI stopped
            said = start("two")
            kept = logs()
            self.assertEqual(kept.pop("comfyui.log"), "ComfyUI, run two")
            self.assertEqual(list(kept.values()), ["ComfyUI, run one"], "the log of the ComfyUI that stopped, under its own name")
            self.assertIn("is kept: " + os.path.join(work, next(iter(kept))), said)


if __name__ == "__main__":
    unittest.main()
