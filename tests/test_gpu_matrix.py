"""tests/gpu_matrix.py: what it reads from a case's page log and from ComfyUI's history. tools/runpod_start.sh: what a
start keeps. No GPU and no browser."""
import argparse
import contextlib
import glob
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
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

    def test_the_erase_with_its_object_named_is_the_erase_with_two_words(self):
        """With no words, Klein's prompt writer named the horse and the barn stayed (the laptop, 12 Nov, at 1.11.9 and at
        1.11.10). The same stroke from the same seed with « the barn » says whether a name is enough."""
        cases = gpu_matrix.load_cases()
        plain, named = cases["horse_erase"], cases["horse_erase_barn"]
        self.assertEqual((plain["strokes"][0][1], named["strokes"][0][1]), ("", "the barn"))
        self.assertEqual((named["path"], named["seed"], named["strokes"][0][2:]), (plain["path"], plain["seed"], plain["strokes"][0][2:]))
        self.assertNotIn("horse_erase_barn", gpu_matrix.ALL)

    def test_a_case_ends_when_the_page_says_that_an_erase_left_its_object(self):
        """The page renders no shot then (logic.eraseCheck), and ui_live.py waited 8 times --timeout for one: two hours. It
        reads the mark the page puts on History's row, which holds no words."""
        with open(os.path.join(gpu_matrix.REPO, "web", "app.mjs"), encoding="utf-8") as f:
            page = f.read()
        with open(os.path.join(gpu_matrix.HERE, "ui_live.py"), encoding="utf-8") as f:
            tool = f.read()
        self.assertIn('LEFT = "#history li[data-left]"', tool)
        self.assertIn('li.dataset.left = "1"', page)
        self.assertIn('if page.query_selector(LEFT):', tool)
        self.assertLess(tool.index("if page.query_selector(LEFT):"), tool.index("deadline = time.time() + a.timeout * 8"), "before the wait for the render")

    def test_a_case_hands_its_strokes_as_written_and_its_seed_to_the_page(self):
        a = argparse.Namespace(url="http://127.0.0.1:8188", comfy="/comfy", channel="chrome", timeout=900, memory="", graph=False)
        cases = gpu_matrix.load_cases()
        erase = gpu_matrix.command(a, cases["horse_erase"], "/out/horse_erase")
        self.assertNotIn("--graph", erase)
        self.assertIn("--graph", gpu_matrix.command(argparse.Namespace(**{**vars(a), "graph": True}), cases["horse_erase"], "/out/horse_erase"))
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

    def matrix(self, cases, alive, *more, jobs=(), result=None):
        """main() on `cases`: what was called, in order, the exit code and the report. `alive` holds ComfyUI's answer after
        each case, and `jobs` the jobs each case ran."""
        calls, alive = [], iter(alive)

        def case(a, name, case, folder):
            calls.append(name)
            return {"name": name, "seconds": 255.0, "vram": 0, "ram": 0, "own": 0, "container": 0, "folder": folder, "log": "", "marks": [],
                    **gpu_matrix.read_log(""), "jobs": list(jobs), "passed": True, "why": "", "matte": None, "live_files": 0, "seed": case.get("seed"), **(result or {})}

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

    def test_a_matte_warning_fails_a_case_that_passed_and_the_report_lists_each_detail(self):
        summary = ("Paint matte (full): tracked on 53 of 121 frames.\n  Warning: object left its place from frame 56. Check the composite there.\n"
                   "  Removed: areas where the plate stands in front of the object, on 66 frames.")
        quiet = "Paint matte (640x352): tracked on 51 of 121 frames.\n  Held: last matte, on 1 frame with no SAM mask."
        self.assertEqual(gpu_matrix.matte_verdict(True, "", [quiet]), (True, ""))
        self.assertEqual(gpu_matrix.matte_verdict(True, "", [quiet, summary]),
                         (False, "Warning: object left its place from frame 56. Check the composite there. "
                                 "The case fails on this matte warning: check its picture on the sheet."))
        self.assertEqual(gpu_matrix.matte_verdict(False, "FAILED: no export", [summary]), (False, "FAILED: no export"), "a failed case keeps its reason")
        real = gpu_matrix.read_log
        with mock.patch.object(gpu_matrix, "read_log", lambda text: {**real(text), "mattes": [summary]}):
            report = self.matrix("horse_cow", [True])[2]
        self.assertIn("- Paint matte (full): tracked on 53 of 121 frames.\n  - Warning: object left its place from frame 56. Check the composite "
                      "there.\n  - Removed: areas where the plate stands in front of the object, on 66 frames.\n", report)

    def test_the_report_gives_one_fact_a_line_and_counts_frames_from_1(self):
        GB = gpu_matrix.GB
        report = self.matrix("horse_cow", [True], result={"vram": 15 * GB, "ram": 49.8 * GB, "own": 49.7 * GB, "container": 50 * GB,
                                                          "matte": ("/m/paint", [0.0522, 0.0261, 0.0726, 0.0])})[2]
        for line in ("GB means 2^30 bytes.", "- Peak VRAM: 15.0 GB.\n", "- Peak RAM: 49.8 GB, 49.7 GB of it not backed by a file.\n",
                     "- This container's own count, page cache included: 50.0 GB.\n", "- Out-of-memory retries: 0.\n",
                     "- Jobs from the job index (not timed): 0.\n", "frames; frame 1 covers 5.22% of the frame.\n",
                     "- Area against frame 1: 0.00 to 1.39 times. Furthest: frame 4, 0.00 times.\n", "- Every frame, against frame 1: 1.00 0.50 1.39 0.00"):
            self.assertIn(line, report)

    def test_the_report_reads_the_render_s_lines_in_their_old_and_new_words(self):
        old = ("11:02:07 PMRender v1: Track the erase (about 12 s)\n11:02:36 PMRender v1: Track the erase took 28.7 s\n"
               "11:02:40 PMMemory profile small: 16 GB of VRAM, 52 GB of RAM. Models load one at a time\n11:02:41 PMLive preview is off: no frames\n")
        new = ("11:02:07 PMRender v1: Track the erase: about 12 s.\n11:02:36 PMRender v1: Track the erase: done in 28.7 s (estimate 12 s).\n"
               "11:02:40 PMMemory profile: small (16 GB of VRAM, 52 GB of RAM).\n  Models load one at a time.\n11:02:41 PMWarning: live preview off: no frames.\n")
        for log in (old, new):
            r = gpu_matrix.read_log(log)
            self.assertEqual((r["steps"], r["announced"]), ([("v1 Track the erase", 28.7)], {"v1 Track the erase": 12}))
            self.assertEqual(r["profile"], "small (16 GB of VRAM, 52 GB of RAM. Models load one at a time)")
            self.assertEqual(len(r["live_off"]), 1)

    def test_fresh_frees_comfyui_before_each_case(self):
        """On the pod of 11 Nov a case's first job read the 138 GB that the case before it had left."""
        calls, _, report = self.matrix("horse_cow,horse_erase", [True], "--fresh")
        self.assertEqual(calls, ["free", "horse_cow", "free", "horse_erase"])
        self.assertIn("| Before each case | ComfyUI is freed (--fresh) |", report)
        calls, _, report = self.matrix("horse_cow,horse_erase", [True])
        self.assertEqual(calls, ["horse_cow", "horse_erase"])
        self.assertIn("| Before each case | ComfyUI stays as the case before left it: a first job can read its RAM |", report)

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


class Tools(unittest.TestCase):
    """The GPU tools do not depend on the page's words and keys (wave 5, R8). A stroke names its tool by its button's
    data-tool, which stays when a label or a key changes, and a matte line is read whatever word comes before « matte »."""

    def test_every_stroke_names_a_tool_the_page_has(self):
        html = "".join(open(p, encoding="utf-8").read() for p in glob.glob(os.path.join(gpu_matrix.REPO, "web", "*.html")))
        tools = set(re.findall(r'data-tool="([a-z]+)"', html))
        self.assertTrue({"paint", "erase", "light"} <= tools, tools)
        for name, case in gpu_matrix.load_cases().items():
            self.assertTrue(all(s[0] in tools for s in case.get("strokes", [])), name)

    def test_ui_live_picks_a_tool_by_its_button(self):
        with open(os.path.join(gpu_matrix.HERE, "ui_live.py"), encoding="utf-8") as f:
            tool = f.read()
        self.assertIn("""page.click(f'.tools [data-tool="{tool}"]')""", tool)
        self.assertEqual(len(re.findall(r"(?<!def )pick\(page, tool\)", tool)), 2, "both runs, besides its def")
        self.assertNotIn("keyboard.press(key)", tool)

    def test_a_matte_line_is_read_whatever_its_first_word(self):
        log = ("11:02:36 PMClean matte: tracked on 76 of 121 frames.\n  Object stands still: its place of frame 0 added where the plate shows it, on 68 frames.\n"
               "  Removed: areas where the plate stands in front of the object, on 77 frames.\n"
               "11:02:40 PMRender v1: Track the object took 26.2 s\n"
               "23:02:37Paint matte (full): tracked on 54 of 121 frames.\n")
        mattes = gpu_matrix.read_log(log)["mattes"]
        self.assertEqual([m.split(":")[0] for m in mattes], ["Clean matte", "Paint matte (full)"])
        self.assertEqual(mattes[0].count("\n  "), 2, "the summary's detail lines come with their headline, and the next log line does not")


class ReportLines(unittest.TestCase):
    """What the report says (wave 5, R9): a fluid shot's steps, the RAM a first job can read, the page's figure for an erase."""

    FLUID = ("11:38:49 PMFluid v1: 2 keyframe(s) at 1, 121, 1280 x 704, 121 frames at 24 fps, seed 104\n"
             "11:38:49 PMFluid shot v1: one LTX 2.5 pass with ainvfx-fluid\n"
             "11:40:38 PMfluid fd2d3d7a: done in 108.9 s (29 nodes, 4 previews)\n"
             "11:40:38 PMFluid shot v1: SDR to HDR, one LTX 2.5 pass with Lightricks' IC-LoRA\n"
             "11:43:33 PMhdr 647d4dd4: done in 175.3 s (29 nodes, 3 from ComfyUI's cache, 4 previews)\n"
             "11:43:33 PMFluid v1: SDR to HDR took 175.3 s: half-float EXR frames in output:paintaplate/x/fluid_v1/hdr\n"
             "11:43:33 PMFluid v1: done in 284.3 s: 1 file(s) in /data/ComfyUI/output/paintaplate/x/fluid_v1/plate\n")

    def test_a_fluid_shot_has_its_steps(self):
        """fluid_720 on the laptop, 12 Nov: its table of steps was empty, as only « Render vN: … took » lines were read."""
        self.assertEqual(gpu_matrix.read_log(self.FLUID)["steps"], [("fluid v1 LTX pass", 108.9), ("fluid v1 SDR to HDR", 175.3), ("fluid v1 in all", 284.3)])

    def test_render_steps_keep_their_names_and_order(self):
        log = "11:02:36 PMRender v1: Track the erase took 28.7 s\n11:03:35 PMRender v1: Erase pass, preview took 59.1 s\n"
        self.assertEqual(gpu_matrix.read_log(log)["steps"], [("v1 Track the erase", 28.7), ("v1 Erase pass, preview", 59.1)])

    def test_an_erase_gives_the_page_s_figure(self):
        log = "11:02:06 PMEdit 1: the object left the first frame (59% of it changed)\n"
        self.assertEqual(gpu_matrix.read_log(log)["figures"], ["Edit 1: the object left the first frame (59% of it changed)"])
        held = "11:02:06 PMEdit 1: the object may still be there (17% of it changed, edges held at 0.62)\n"  # the page's line since wave 7 (logic.leftLines)
        self.assertEqual(gpu_matrix.read_log(held)["figures"], ["Edit 1: the object may still be there (17% of it changed, edges held at 0.62)"])

    def test_without_fresh_a_first_job_can_read_the_case_before(self):
        """horse_erase_barn's ingest on the laptop, 12 Nov: 30.3 GB of peak RAM for a 2.6 s job, the case before's memory."""
        r, gb = {"jobs": [{"name": "ingest", "id": "69cce02d", "run": 2.6, "ram": 30.3e9}]}, (lambda x: f"{x / 1e9:.1f} GB")
        note = gpu_matrix.carried(r, False, gb)
        self.assertTrue(len(note) == 1 and "ingest 69cce02d" in note[0] and "--fresh" in note[0], note)
        self.assertEqual(gpu_matrix.carried(r, True, gb), [])


class MatteCases(unittest.TestCase):
    """Two cases for the matte agent (wave 5, R4), outside quick and all: a paint on a moving object, and an object that
    stands still for 12 frames or more, then leaves by itself (Adrien accepted that the matte loses it and wants a recording)."""

    def test_two_paint_cases_outside_quick_and_all(self):
        cases = gpu_matrix.load_cases()
        html = "".join(open(p, encoding="utf-8").read() for p in glob.glob(os.path.join(gpu_matrix.REPO, "web", "*.html")))
        for name in ("horse_saddle", "horse_bird"):
            case = cases[name]
            self.assertNotIn(name, gpu_matrix.ALL + gpu_matrix.QUICK)
            self.assertEqual((case["path"], [s[0] for s in case["strokes"]]), ("plates/horse.mp4", ["paint"]))
            self.assertIsInstance(case["seed"], int, "the same jobs at every run")
            self.assertIn(f'data-color="{case["strokes"][0][4]["color"]}"', html, "one of the page's swatches")
        self.assertIn("still", cases["horse_bird"]["strokes"][0][1])
        self.assertIn("flies away", cases["horse_bird"]["strokes"][0][1])


class Estimates(unittest.TestCase):
    """Each step beside what the page announced before it started (wave 5, R2): a GPU run checks the estimates."""

    def test_the_report_holds_each_step_against_its_announcement(self):
        log = ("11:02:07 PMRender v1: Track the erase (about 12 s)\n11:02:36 PMRender v1: Track the erase took 28.7 s\n"
               "11:03:36 PMRender v1: Composite, preview (about 8 s) in the background\n11:03:47 PMRender v1: Composite, preview took 9.0 s\n")
        info = gpu_matrix.read_log(log)
        self.assertEqual(info["announced"], {"v1 Track the erase": 12, "v1 Composite, preview": 8})
        self.assertEqual(gpu_matrix.estimates_off(info["steps"], info["announced"]), ["v1 Track the erase: about 12 s, done in 28.7 s"])


class NodeClock(unittest.TestCase):
    """Where a job's time goes (wave 5, D7): ui_live.py keeps ComfyUI's « executing » messages, gpu_matrix.py sums them by node."""

    def test_each_node_s_seconds_from_comfyui_s_executing_messages(self):
        pid = "b05b5b84-7022-4f56-a1c9-cf9dc1a678cd"
        events = [[10.0, pid, "3"], [12.5, pid, "7"], [518.5, pid, "9"], [549.5, pid, "11"], [550.0, pid, None]]
        graph = {"3": {"class_type": "CLIPTextEncode"}, "7": {"class_type": "SamplerCustomAdvanced"},
                 "9": {"class_type": "VAEDecodeTiled"}, "11": {"class_type": "PaintAPlate_SavePlate"}}
        self.assertEqual(gpu_matrix.node_times(events, {pid: graph}), {"b05b5b84": [
            ("SamplerCustomAdvanced", 506.0), ("VAEDecodeTiled", 31.0), ("CLIPTextEncode", 2.5), ("PaintAPlate_SavePlate", 0.5)]})

    @unittest.skipUnless(importlib.util.find_spec("playwright"), "tests/ui_live.py imports Playwright")
    def test_ui_live_keeps_the_executing_messages_only(self):
        spec = importlib.util.spec_from_file_location("ui_live_clock", os.path.join(gpu_matrix.HERE, "ui_live.py"))
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)

        class Socket:
            def on(self, event, fn):
                self.event, self.fn = event, fn
        ws, events = Socket(), []
        tool.executing(events, 0.0)(ws)
        for frame in (b"\x00\x01 a preview", '{"type": "progress", "data": {"value": 1}}', '{"type": "executing", "data": {"node": "7", "prompt_id": "abc"}}'):
            ws.fn(frame)
        self.assertEqual((ws.event, [e[1:] for e in events]), ("framereceived", [["abc", "7"]]))


class Hdr(unittest.TestCase):
    """--hdr (wave 6, R13, the plate workstream's proposal): SDR to HDR on for a run, so HDR Match's line can be read."""

    def test_hdr_reaches_ui_live_for_a_run_or_a_case(self):
        a = argparse.Namespace(url="http://127.0.0.1:8188", comfy="/comfy", channel="chrome", timeout=900, memory="", graph=False)
        cases = gpu_matrix.load_cases()
        self.assertNotIn("--hdr", gpu_matrix.command(a, cases["horse_cow"], "/out/horse_cow"))
        self.assertIn("--hdr", gpu_matrix.command(argparse.Namespace(**vars(a), hdr=True), cases["horse_cow"], "/out/horse_cow"))
        self.assertIn("--hdr", gpu_matrix.command(a, cases["hdr_cow"], "/out/hdr_cow"))

    def test_the_hdr_case_paints_horse_cow_on_the_hdr_test_plate(self):
        cases = gpu_matrix.load_cases()
        hdr, cow = cases["hdr_cow"], cases["horse_cow"]
        self.assertEqual((hdr["path"], hdr["seed"], hdr["strokes"], hdr["hdr"]), ("plates/horse_hdr", cow["seed"], cow["strokes"], True))
        self.assertNotIn("hdr_cow", gpu_matrix.ALL + gpu_matrix.QUICK)

    def test_ui_live_turns_it_on_before_the_strokes(self):
        with open(os.path.join(gpu_matrix.HERE, "ui_live.py"), encoding="utf-8") as f:
            tool = f.read()
        self.assertTrue(all(s in tool for s in ('page.click("#deliver-hdr")', 'page.click("#deliver-yes")', 'page.is_visible("#deliver-auto")')))
        self.assertLess(tool.index("mark(deliver_hdr(page))"), tool.index("for i, (tool, words, pts, *size) in enumerate(strokes)"))

    def test_hdr_match_lines_come_from_comfyui_s_log_since_the_case_began(self):
        entries = [{"t": "2026-11-13T09:59:59.900000", "m": "PaintAPlate HDR Match: a case before\n"},
                   {"t": "2026-11-13T10:00:00.500000", "m": "PaintAPlate HDR Match: level +0.02 stops on 121 frames\n"},
                   {"t": "2026-11-13T10:00:01.000000", "m": "[Paint a plate] HDR Match: level +0.02 stops on 121 frames.\n"},
                   {"t": "2026-11-13T10:00:01.000000", "m": "Prompt executed in 9.10 seconds\n"}]
        with mock.patch.object(gpu_matrix, "get", return_value={"entries": entries}):
            self.assertEqual(gpu_matrix.comfy_lines("http://x", "2026-11-13T10:00:00"), ["PaintAPlate HDR Match: level +0.02 stops on 121 frames",
                              "[Paint a plate] HDR Match: level +0.02 stops on 121 frames."], "both marks of HDR Match's line")
        with mock.patch.object(gpu_matrix, "get", side_effect=OSError("404")):
            self.assertEqual(gpu_matrix.comfy_lines("http://x", "2026-11-13T10:00:00"), [])


@unittest.skipUnless(importlib.util.find_spec("av") and importlib.util.find_spec("PIL"), "the sheet reads movies with PyAV, draws with Pillow")
class Sheet(unittest.TestCase):
    """The pictures (wave 6, R10): the plate and the export around each edit, on four frames, from an export.zip laid out as
    the page writes it: export/<plate>.mp4, matte/matte_00001_.png and on, MODELS.md."""

    def test_the_sheet_follows_the_matte_and_shows_what_the_export_lost(self):
        import av
        import numpy as np
        from PIL import Image
        tmp, (w, h, n) = tempfile.mkdtemp(prefix="paintaplate_sheet_"), (320, 192, 12)

        def at(i):  # the object: a red square sliding left 12 px a frame, as the barn slides behind the horse
            return slice(80, 110), slice(260 - 12 * i, 290 - 12 * i)

        def movie(path, with_object):
            with av.open(path, "w") as c:
                s = c.add_stream("mpeg4", rate=24)
                s.width, s.height, s.pix_fmt = w, h, "yuv420p"
                for i in range(n):
                    a = np.full((h, w, 3), 128, np.uint8)
                    if with_object:
                        a[at(i)] = (220, 20, 20)
                    for p in s.encode(av.VideoFrame.from_ndarray(a, format="rgb24")):
                        c.mux(p)
                for p in s.encode():
                    c.mux(p)
        plate = os.path.join(tmp, "plate.mp4")
        movie(plate, True)
        movie(os.path.join(tmp, "result.mp4"), False)
        with zipfile.ZipFile(os.path.join(tmp, "export.zip"), "w") as z:
            z.write(os.path.join(tmp, "result.mp4"), "export/plate.mp4")
            for i in range(n):
                m = np.zeros((h, w), np.uint8)
                m[at(i)] = 255
                Image.fromarray(m).save(os.path.join(tmp, "m.png"))
                z.write(os.path.join(tmp, "m.png"), f"matte/matte_{i + 1:05d}_.png")
            z.writestr("MODELS.md", "# Models behind this export\n")
        case = {"path": "plates/plate.mp4", "strokes": [["erase", "", [[0.85, 0.5], [0.88, 0.5]], 30, {"whole": True}]]}
        made = gpu_matrix.sheet(case, tmp, plate)
        self.assertEqual(made["frames"], [1, 5, 9, 12])
        pic = np.asarray(Image.open(made["path"]).convert("RGB")).astype(int)
        red = (pic[..., 0] > 150) & (pic[..., 1] < 90)
        self.assertEqual(len(made["cells"]), 8, "four frames, the plate and the export")
        for row, column, x0, y0, x1, y1 in made["cells"]:  # a box that stayed on frame 1 would miss the object on frame 12
            self.assertEqual(bool(red[y0:y1, x0:x1].any()), column == 0, (row, column))
        self.assertFalse(os.path.exists(os.path.join(tmp, "sheet_files")), "the unzipped frames are removed")
        self.assertIsNone(gpu_matrix.sheet({**case, "strokes": []}, tmp, plate), "no edit, no sheet")

    @unittest.skipUnless(shutil.which("node"), "the verdict runs the page's rules with Node")
    def test_the_sheet_says_gone_or_left_by_the_page_s_own_rule(self):
        """R15: logic.eraseCheck, run with Node on the export's first frame against the plate's, inside the page's mask."""
        import av
        import numpy as np
        from PIL import Image
        tmp, (w, h, n), place = tempfile.mkdtemp(prefix="paintaplate_verdict_"), (320, 192, 4), (slice(80, 120), slice(200, 260))

        def movie(path, with_object):
            with av.open(path, "w") as c:
                s = c.add_stream("mpeg4", rate=24)
                s.width, s.height, s.pix_fmt = w, h, "yuv420p"
                for _ in range(n):
                    a = np.full((h, w, 3), 128, np.uint8)
                    if with_object:
                        a[place] = (220, 20, 20)
                    for p in s.encode(av.VideoFrame.from_ndarray(a, format="rgb24")):
                        c.mux(p)
                for p in s.encode():
                    c.mux(p)
        plate, mask = os.path.join(tmp, "plate.mp4"), os.path.join(tmp, "e2_mask_full.png")
        movie(plate, True)
        m = np.zeros((h, w), np.uint8)
        m[place] = 255
        Image.fromarray(m).save(mask)
        case = {"path": "plates/plate.mp4", "strokes": [["erase", "", [[0.65, 0.5], [0.8, 0.5]], 30, {"whole": True}]]}
        for with_object, state in ((False, "gone"), (True, "left")):
            movie(os.path.join(tmp, "result.mp4"), with_object)
            with zipfile.ZipFile(os.path.join(tmp, "export.zip"), "w") as z:
                z.write(os.path.join(tmp, "result.mp4"), "export/plate.mp4")
            made = gpu_matrix.sheet(case, tmp, plate, mask=mask, judge_at=(w // 2, h // 2))
            self.assertIs(made["verdict"]["left"], with_object, made["verdict"])
            self.assertTrue(made["verdict"]["text"].startswith(f"Clean, frame 1: {state} ("), made["verdict"]["text"])
        self.assertIn("no verdict", gpu_matrix.sheet(case, tmp, plate)["verdict"]["text"], "no mask from the page, no verdict")

class StoppedComfy(unittest.TestCase):
    """hdr_cow on the laptop, 13 Nov: ComfyUI stopped in SDR to HDR, its /history went with it, and the report named nodes
    « node 26 ». The pack's own workflows name them; the node that had no end is the one running at the stop."""

    def test_nodes_are_named_from_the_pack_s_workflow_when_history_is_gone(self):
        shot, hdr = gpu_matrix.workflow("shot"), gpu_matrix.workflow("hdr")
        self.assertEqual((shot["26"]["class_type"], shot["29"]["class_type"]), ("SamplerCustomAdvanced", "VAEDecodeTiled"))
        events = [[0.0, "b23042ca-1", "26"], [519.0, "b23042ca-1", "29"], [542.1, "b23042ca-1", None],
                  [600.0, "b6ade25f-2", "26"], [1115.0, "b6ade25f-2", "29"]]
        names = {"b23042ca": "shot", "b6ade25f": "hdr"}
        spent = gpu_matrix.node_times(events, {}, names)
        self.assertEqual(spent["b23042ca"], [("SamplerCustomAdvanced", 519.0), ("VAEDecodeTiled", 23.1)])
        self.assertEqual(gpu_matrix.running_at_stop(events, {}, names), {"b6ade25f": hdr["29"]["class_type"]})
        self.assertEqual(gpu_matrix.node_times(events, {}), {"b23042ca": [("node 26", 519.0), ("node 29", 23.1)], "b6ade25f": [("node 26", 515.0)]})
        self.assertEqual(gpu_matrix.FAILED_JOB.findall("hdr b6ade25f: failed after 628.5 s (29 nodes, 4 previews): ComfyUI stopped answering"), [("hdr", "b6ade25f")])

    def test_hdr_match_is_looked_for_after_a_render_s_sdr_to_hdr_only(self):
        self.assertFalse(gpu_matrix.render_hdr([("fluid v1 SDR to HDR", 175.8), ("fluid v1 in all", 281.1)]))
        self.assertTrue(gpu_matrix.render_hdr([("v1 Shot, full size", 580.0), ("v1 SDR to HDR", 640.0)]))


    def test_a_fluid_case_s_sheet_shows_its_keyframes_and_four_frames_of_its_shot(self):
        import av
        import numpy as np
        from PIL import Image
        tmp = tempfile.mkdtemp(prefix="paintaplate_fluid_")
        out, (w, h, n) = os.path.join(tmp, "output", "paintaplate", "f1"), (64, 48, 17)
        os.makedirs(os.path.join(out, "control"))

        def movie(path, colour):
            with av.open(path, "w") as c:
                s = c.add_stream("mpeg4", rate=24)
                s.width, s.height, s.pix_fmt = w, h, "yuv420p"
                for i in range(n):
                    for p in s.encode(av.VideoFrame.from_ndarray(np.full((h, w, 3), colour(i), np.uint8), format="rgb24")):
                        c.mux(p)
                for p in s.encode():
                    c.mux(p)
        movie(os.path.join(out, "control", "c_00001_.mp4"), lambda i: (245, 124, 0) if i in (0, n - 1) else (0, 0, 0))
        movie(os.path.join(out, "preview_00001_.mp4"), lambda i: (12 * i,) * 3)
        graph = {"5": {"class_type": "PaintAPlate_SaveMovie"}, "27": {"class_type": "PaintAPlate_SavePlate"}, "29": {"class_type": "SaveVideo"}}
        outputs = {"5": {"images": [{"filename": "c_00001_.mp4", "subfolder": "paintaplate/f1/control", "type": "output"}], "animated": [True]},
                   "27": {"images": [{"filename": "plate_00001.exr", "subfolder": "paintaplate/f1", "type": "output"}]},
                   "29": {"images": [{"filename": "preview_00001_.mp4", "subfolder": "paintaplate/f1", "type": "output"}], "animated": [True]}}
        history = {"abcdef12-34": {"prompt": [0, "abcdef12-34", graph], "outputs": outputs}}
        movies = gpu_matrix.fluid_movies(tmp, [{"name": "fluid", "id": "abcdef12"}], history)
        self.assertEqual(movies, {"control": os.path.join(out, "control", "c_00001_.mp4"), "shot": os.path.join(out, "preview_00001_.mp4")})
        self.assertEqual(gpu_matrix.fluid_movies(tmp, [{"name": "shot", "id": "abcdef12"}], history), {}, "a case with no fluid job")
        case = {"fluid": {"keys": [[0, "#f57c00", [[0.5, 0.5]], 64], [-1, "#f57c00", [[0.5, 0.5]], 96]]}}
        made = gpu_matrix.fluid_sheet(case, tmp, movies)
        self.assertEqual((made["keys"], made["frames"]), ([1, n], [1, n // 3 + 1, 2 * n // 3 + 1, n]), "the keyframes as painted, the last as -1")
        with Image.open(made["path"]) as im:
            a = np.asarray(im.convert("RGB")).astype(int)
        orange = (abs(a[..., 0] - 245) < 24) & (abs(a[..., 1] - 124) < 24) & (a[..., 2] < 40)
        self.assertGreaterEqual(orange.sum(), 2 * w * h * 0.9, "both keyframes show their blob")
        self.assertIn("error", gpu_matrix.fluid_sheet(case, tmp, {}))

class Verdict(unittest.TestCase):
    """What the verdict and the tree case read: the page's mask and quick-pass size, the case, the end of ui_live.py's wait."""

    def test_the_verdict_takes_the_mask_of_the_case_s_last_edit_job_and_the_quick_pass_size(self):
        tmp = tempfile.mkdtemp(prefix="paintaplate_mask_")
        folder = os.path.join(tmp, "input", "paintaplate", "up")
        os.makedirs(folder)
        quick, full = (os.path.join(folder, f"{h * 32}.png") for h in "ab")
        for path in (quick, full):  # named by the hash of its content, and older than the case: only the job's graph names it
            open(path, "wb").close()
            os.utime(path, (1000, 1000))
        graph = lambda h: {"4": {"class_type": "LoadImage", "inputs": {"image": f"paintaplate/up/{'c' * 32}.png"}},  # noqa: E731
                           "8": {"class_type": "LoadImageMask", "inputs": {"image": f"paintaplate/up/{h * 32}.png", "channel": "red"}}}
        jobs = [{"name": "prompt", "id": "11111111"}, {"name": "edit", "id": "22222222"}, {"name": "edit", "id": "33333333"}]
        graphs = {"22222222-quick": graph("a"), "33333333-full": graph("b"), "44444444-other": graph("d")}
        self.assertEqual(gpu_matrix.page_mask(tmp, jobs, graphs), full, "the full-size pass: the case's last edit job")
        self.assertEqual(gpu_matrix.page_mask(tmp, jobs, {k: v for k, v in graphs.items() if k[0] != "3"}), quick,
                         "the last edit job that /history still holds")
        self.assertIsNone(gpu_matrix.page_mask(tmp, jobs[:1], graphs), "a case with no edit job")
        self.assertEqual(gpu_matrix.erase_verdict(None, None, None, (768, 432))["text"],
                         "Clean, frame 1: no verdict. No mask: ComfyUI's history holds no edit job of this case.")
        self.assertEqual(gpu_matrix.erase_verdict(None, None, os.path.join(folder, "gone.png"), (768, 432))["text"],
                         "Clean, frame 1: no verdict. No mask: gone.png is not in ComfyUI's input folder.")
        log = "Working sizes: edits at 1920 x 1088, quick passes at 768 x 432, preview at 608 x 352, tracking at 960 x 544"
        self.assertEqual(gpu_matrix.quick_size(log), (768, 432), "the size the page judges at (p.prev), not the shot's preview size")
        log = "Working sizes: edits at 1920 x 1088, edit preview at 768 x 432, shot preview at 640 x 352, tracking at 960 x 544."
        self.assertEqual(gpu_matrix.quick_size(log), (768, 432), "the line's words of the edit preview")
        self.assertIsNone(gpu_matrix.quick_size(""))

    def test_the_arm_case_paints_the_exr_plate_with_sdr_to_hdr_outside_quick_and_all(self):
        arm = gpu_matrix.load_cases()["tos_arm"]
        self.assertEqual((arm["path"], arm["hdr"], len(arm["strokes"])), ("plates/tos_05_4a", True, 1))
        tool, words, points, _, options = arm["strokes"][0]
        self.assertEqual((tool, options), ("paint", {"color": "#000000"}))
        self.assertTrue(words.startswith("a robotic arm: ") and words.endswith("a row of very bright blue-white LEDs along the wiring"))
        self.assertTrue(all(0 <= v <= 1 for point in points for v in point))
        self.assertNotIn("tos_arm", gpu_matrix.ALL + gpu_matrix.QUICK)

    def test_the_tree_case_expects_the_name_and_stays_out_of_quick_and_all(self):
        cases = gpu_matrix.load_cases()
        tree, plain = cases["horse_erase_tree"], cases["horse_erase"]
        self.assertEqual((tree["path"], tree["seed"], tree["expect"]), (plain["path"], plain["seed"], "name asked"))
        self.assertEqual(tree["strokes"], [["erase", "", [[0.79, 0.26], [0.83, 0.25], [0.87, 0.27]], 36, {"whole": True}]])
        self.assertNotIn("horse_erase_tree", gpu_matrix.ALL + gpu_matrix.QUICK)
        asked = ["page ready: Ready.", "name asked: Edit 2: the prompt writer took the stroke for another object, so nothing ran"]
        self.assertEqual(gpu_matrix.name_asked(asked, "Edit 2: asking Klein's prompt writer", [{"name": "prompt"}]), (True, ""))
        self.assertEqual(gpu_matrix.name_asked(asked, "Edit 2: Klein quick pass at 768 x 432, 16 steps", []), (False, "a Klein pass ran"))
        self.assertEqual(gpu_matrix.name_asked(asked[:1], "", [{"name": "shot"}]), (False, "the page did not ask for the name"))

    def test_ui_live_ends_on_a_row_marked_left_even_behind_a_dialog(self):
        """The edit agent's dialog (« Render anyway » or « Cancel ») can keep its row busy: ui_live.py waits for the rows to
        finish or for a row marked left, whichever comes first, and tells a name asked from an object left."""
        tool = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_live.py"), encoding="utf-8").read()
        self.assertIn("|| !!document.querySelector('{LEFT}')", tool)
        self.assertIn('mark(f"name asked: {exc}")', tool)
        self.assertIn("raise NameAsked(", tool)


if __name__ == "__main__":
    unittest.main()
