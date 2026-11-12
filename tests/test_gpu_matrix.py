"""tests/gpu_matrix.py: what it reads from a case's page log and from ComfyUI's history. tools/runpod_start.sh: what a
start keeps. No GPU and no browser."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gpu_matrix  # noqa: E402

LOG = """15:02:31ingest ef88a8f3: done in 2.0 s (10 nodes, 3 from ComfyUI's cache)
15:02:40edit 0a1b2c3d: done in 8.5 s (24 nodes, 16 previews)
15:02:41Render v1: Shot, preview took 41.2 s
15:03:30shot 99aa00bb: stopped after 12.0 s in SamplerCustomAdvanced (31 nodes, 3 previews)
15:03:31Memory profile large: 96 GB of VRAM, 188 GB of RAM. Every model loads now and stays loaded
"""


class Report(unittest.TestCase):
    def test_a_retry_is_counted_by_its_own_line(self):
        """The laptop's erase of 12 Nov showed one out-of-memory retry where none happened: ComfyUI had stopped, and the
        page's message for a stop also says « ran out of memory »."""
        stopped = ("09:14:58Erase pass, full size failed: ComfyUI stopped answering. Its terminal says why: most often the machine "
                   "ran out of memory. Start ComfyUI again. Generate tries again.\n")
        self.assertEqual(gpu_matrix.read_log(stopped)["oom"], 0)
        self.assertEqual(gpu_matrix.read_log(stopped + "09:15:00" + gpu_matrix.RETRY + ".\n")["oom"], 1)
        with open(os.path.join(gpu_matrix.REPO, "web", "comfy.mjs"), encoding="utf-8") as f:
            self.assertIn(gpu_matrix.RETRY, f.read(), "the page's own words for a retry")

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


class Run(unittest.TestCase):
    """gpu_matrix.main with stand-ins for the browser, ComfyUI and the cases."""

    def matrix(self, cases, alive, *more):
        """main() on `cases`: what was called, in order, the exit code and the report. `alive` holds ComfyUI's answer after
        each case."""
        calls, alive = [], iter(alive)

        def case(a, name, case, folder):
            calls.append(name)
            return {"name": name, "seconds": 255.0, "vram": 0, "ram": 0, "own": 0, "container": 0, "folder": folder, "log": "", "marks": [],
                    **gpu_matrix.read_log(""), "passed": True, "why": "", "matte": None, "live_files": 0}

        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "input", "plates"))
            open(os.path.join(tmp, "input", "plates", "horse.mp4"), "w").close()
            argv = ["gpu_matrix.py", "--comfy", tmp, "--out", os.path.join(tmp, "out"), "--cases", cases, *more]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(gpu_matrix, "browser_ready", lambda channel: None), \
                    mock.patch.object(gpu_matrix, "get", lambda url: {}), mock.patch.object(gpu_matrix, "Memory", lambda url: mock.Mock(pid=None)), \
                    mock.patch.object(gpu_matrix, "run_case", case), mock.patch.object(gpu_matrix, "answers", lambda url: next(alive)), \
                    mock.patch.object(gpu_matrix, "free", lambda url: calls.append("free")), contextlib.redirect_stdout(io.StringIO()):
                code = gpu_matrix.main()
            with open(os.path.join(tmp, "out", "report.md"), encoding="utf-8") as f:
                return calls, code, f.read()

    def test_a_run_stops_when_comfyui_has_stopped(self):
        """On the laptop (12 Nov) ComfyUI stopped in horse_erase, and the two cases left each failed in 31 s with a traceback."""
        calls, code, report = self.matrix("horse_cow,horse_erase,horse_light,fluid_720", [True, False])
        self.assertEqual((calls, code), (["horse_cow", "horse_erase"], 1))
        for name in ("horse_light", "fluid_720"):
            self.assertIn(f"| {name} | not run: ComfyUI had stopped |", report)
            self.assertNotIn(f"## {name}", report)
        self.assertIn("## horse_erase · passed in 255 s", report)

    def test_a_run_goes_to_its_end_while_comfyui_answers(self):
        calls, code, report = self.matrix("horse_cow,horse_erase", [True])
        self.assertEqual((calls, code), (["horse_cow", "horse_erase"], 0))
        self.assertNotIn("not run", report)

    def test_fresh_frees_comfyui_before_each_case(self):
        """On the pod of 11 Nov a case's first job read the 138 GB that the case before it had left."""
        calls, _, report = self.matrix("horse_cow,horse_erase", [True], "--fresh")
        self.assertEqual(calls, ["free", "horse_cow", "free", "horse_erase"])
        self.assertIn("| Before each case | ComfyUI is freed (--fresh) |", report)
        calls, _, report = self.matrix("horse_cow,horse_erase", [True])
        self.assertEqual(calls, ["horse_cow", "horse_erase"])
        self.assertIn("| Before each case | ComfyUI stays as the case before left it |", report)

    def test_free_posts_what_the_page_posts(self):
        sent = []

        def urlopen(request, timeout=None):
            sent.append((request.full_url, request.get_method(), json.loads(request.data)))
            return io.BytesIO()

        with mock.patch.object(gpu_matrix.urllib.request, "urlopen", urlopen), mock.patch.object(gpu_matrix.time, "sleep", lambda seconds: None):
            gpu_matrix.free("http://127.0.0.1:8188")
        self.assertEqual(sent, [("http://127.0.0.1:8188/free", "POST", {"unload_models": True, "free_memory": True})])


@unittest.skipUnless(importlib.util.find_spec("playwright"), "tests/ui_live.py imports Playwright")
class Live(unittest.TestCase):
    """tests/ui_live.py: the two rules that read the page's History and its render note."""

    def test_a_fluid_shot_has_its_own_history_row(self):
        """fluid_1080_edit waited 600 s for one row after its first edit, and History held two (pod, 11 Nov)."""
        import ui_live
        self.assertEqual([ui_live.rows(0, None), ui_live.rows(1, None)], [1, 2])
        self.assertEqual(ui_live.rows(0, {"size": [1920, 1088]}), 2)

    def test_a_stage_is_marked_once(self):
        """The laptop's horse_cow of 12 Nov wrote 61 marks for two stages: the estimate in the note changes every second."""
        import ui_live
        notes = ["preview about 14 s left", "preview about 3 s left", "preview almost ready", "full size about 8 min 20 s left",
                 "full size about 2 min 50 s left", "full size ready"]
        self.assertEqual([ui_live.stage(note) for note in notes], ["preview"] * 3 + ["full size"] * 2 + ["full size ready"])


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
