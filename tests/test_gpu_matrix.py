"""tests/gpu_matrix.py: what it reads from a case's page log and from ComfyUI's history. tools/runpod_start.sh: what a
start keeps. No GPU and no browser."""
import argparse
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


class Seeds(unittest.TestCase):
    """A case runs from its own seed with its strokes as written, so a wrong picture comes back at the next run."""

    def test_every_case_holds_a_seed(self):
        """The laptop's erase of 12 Nov (1.11.10) left its object in the picture. The page had drawn its seed, 1017942128,
        and the GPU test had moved the strokes: the next run would have made another picture."""
        cases = gpu_matrix.load_cases()
        for name in gpu_matrix.ALL:
            self.assertIsInstance(cases[name].get("seed"), int, name)
            self.assertTrue(0 <= cases[name]["seed"] < 2 ** 31, name)
        self.assertEqual(cases["horse_erase"]["seed"], 1017942128)
        self.assertEqual((cases["uhd_erase"]["seed"], cases["uhd25_erase"]["seed"]), (1017942128, 1017942128), "« like » takes the other case's seed")
        self.assertEqual(cases["uhd_erase"]["strokes"][0][3], 2 * cases["horse_erase"]["strokes"][0][3], "and its strokes, the brush scaled")

    def test_a_case_hands_its_strokes_as_written_and_its_seed_to_the_page(self):
        a = argparse.Namespace(url="http://127.0.0.1:8188", comfy="/comfy", channel="chrome", timeout=900, memory="")
        cases = gpu_matrix.load_cases()
        erase = gpu_matrix.command(a, cases["horse_erase"], "/out/horse_erase")
        self.assertEqual(erase[erase.index("--seed") + 1], "1017942128")
        self.assertEqual(json.loads(erase[erase.index("--strokes") + 1]), cases["horse_erase"]["strokes"])
        self.assertEqual(gpu_matrix.command(a, cases["horse_erase"], "/out/horse_erase"), erase, "a second run asks for the same")
        fluid = gpu_matrix.command(a, cases["fluid_720"], "/out/fluid_720")
        self.assertEqual(json.loads(fluid[fluid.index("--fluid") + 1]), cases["fluid_720"]["fluid"])
        self.assertEqual(fluid[fluid.index("--seed") + 1], str(cases["fluid_720"]["seed"]))
        self.assertNotIn("--strokes", fluid)
        self.assertNotIn("--seed", gpu_matrix.command(a, {"path": "plates/horse.mp4"}, "/out/x"), "a case without a seed: the page draws one")

    def test_the_report_names_the_seed_asked_for_and_the_seeds_of_the_page_s_log(self):
        log = ('04:35:35 PMEdit 1: Erase "", seed 1017942128, whole object on, 1 stroke, over 0 edits\n'
               "04:36:10 PMRender v1: 1 edit(s) (1 Erase), preview at 640x352, seed 1017942128, steps: erase > clean > comp\n")
        named = gpu_matrix.read_log(log)["seeds"]
        self.assertEqual(named, ["1017942128"])
        self.assertEqual(gpu_matrix.seed_note(1017942128, named), "Seed asked for: 1017942128. In the page's log: 1017942128.")
        self.assertIn("The page did not start from the seed asked for", gpu_matrix.seed_note(7, named))
        self.assertEqual(gpu_matrix.seed_note(None, named), "Seed asked for: none, the page draws one. In the page's log: 1017942128.")
        self.assertEqual(gpu_matrix.read_log(LOG)["seeds"], [])

    def test_seeds_takes_the_whole_numbers_the_page_accepts(self):
        self.assertEqual(gpu_matrix.seeds_asked(""), [None])
        self.assertEqual(gpu_matrix.seeds_asked("7,8, 2147483647"), [7, 8, 2147483647])
        for text in ("7,x", "-1", "2147483648", "7,,8"):
            with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
                gpu_matrix.seeds_asked(text)


class Run(unittest.TestCase):
    """gpu_matrix.main with stand-ins for the browser, ComfyUI and the cases."""

    def matrix(self, cases, alive, *more, jobs=()):
        """main() on `cases`: what was called, in order, the exit code and the report. `alive` holds ComfyUI's answer after
        each case, and `jobs` the jobs each case ran."""
        calls, alive = [], iter(alive)

        def case(a, name, case, folder):
            calls.append(name)
            return {"name": name, "seconds": 255.0, "vram": 0, "ram": 0, "own": 0, "container": 0, "folder": folder, "log": "", "marks": [],
                    **gpu_matrix.read_log(""), "jobs": list(jobs), "passed": True, "why": "", "matte": None, "live_files": 0, "seed": case.get("seed")}

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

    def test_the_report_is_written_when_a_job_ran(self):
        """A job's row gives its seconds in ComfyUI. The report kept them under the name of its list of cases: it stopped
        after the first case whose last job had run, and the cases left were not started (the laptop, 12 Nov, 1.11.10)."""
        GB = gpu_matrix.GB
        ran = {"name": "cleanup", "id": "5b938984", "seconds": 88.3, "run": 88.0, "vram": 15 * GB, "ram": 38 * GB, "own": 38 * GB,
               "cached": 13, "nodes": 36, "previews": 1}
        indexed = {**ran, "name": "ingest", "id": "05306f52", "seconds": 0.1, "run": None}  # taken from the job index: not timed
        calls, code, report = self.matrix("horse_erase,horse_cow", [True], jobs=[indexed, ran])
        self.assertEqual((calls, code), (["horse_erase", "horse_cow"], 0))
        self.assertIn("| cleanup 5b938984 | 88.3 | 88.0 |", report)
        self.assertIn("| ingest 05306f52 | 0.1 |", report)
        self.assertNotIn("The log of each failure", report)

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

    def test_seeds_runs_each_case_once_per_seed(self):
        """The pod's first turn runs the erase on 5 seeds: one row of the report and one folder per seed."""
        calls, code, report = self.matrix("horse_erase,horse_light", [True, True, True], "--seeds", "7,8")
        self.assertEqual((calls, code), (["horse_erase_s7", "horse_erase_s8", "horse_light_s7", "horse_light_s8"], 0))
        self.assertIn("| Seeds | 7, 8 (--seeds): each case runs once per seed |", report)
        self.assertIn("## horse_erase_s8 · passed in 255 s", report)
        self.assertIn("- Seed asked for: 8.", report)
        calls, _, report = self.matrix("horse_erase", [])
        self.assertEqual(calls, ["horse_erase"])
        self.assertIn("| Seeds | each case runs from its own (gpu_matrix.json) |", report)
        self.assertIn("- Seed asked for: 1017942128.", report)
        self.assertIn("| Job index | left alone: the page is opened with `?index=0`, so every job runs |", report)

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


    def test_the_page_is_asked_for_the_seed_and_for_no_job_index(self):
        """With one seed and the same strokes, a case's jobs are the same at every run: taken from the job index, none would
        run, and no time or peak of memory would be measured."""
        import ui_live
        self.assertEqual(ui_live.address("http://127.0.0.1:8188"), "http://127.0.0.1:8188/extensions/ainvfx-paintaplate/paintaplate.html?blank=0&index=0")
        self.assertEqual(ui_live.address("http://x", "small", 1017942128).split("?")[1], "blank=0&index=0&memory=small&seed=1017942128")
        self.assertEqual(ui_live.address("http://x", seed=0).split("?")[1], "blank=0&index=0&seed=0", "0 is a seed")
        with open(os.path.join(gpu_matrix.REPO, "web", "app.mjs"), encoding="utf-8") as f:
            page = f.read()
        for option in ('Q.get("blank")', 'Q.get("index")', 'Q.get("memory")', 'Q.get("seed")'):
            self.assertIn(option, page, "the page's own name for this option")


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
