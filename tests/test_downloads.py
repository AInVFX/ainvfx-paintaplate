"""The two download tools, get_models.py and get_plates.py, against a stand-in for huggingface_hub: no network. Where
each file lands, what the tools print, what a refusal says, and the exit codes."""
import contextlib
import io
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import get_models  # noqa: E402
import get_plates  # noqa: E402

KLEIN, LTX, HDR = "black-forest-labs/flux-3-image-klein-comfy", "Lightricks/LTX-2.5", "Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR"
PLATES = {"horse.mp4": 6_500_000, "tea.mp4": 5_000_000}


class Refused(Exception):  # as huggingface_hub's HTTP errors: the answer's status code on .response
    def __init__(self, code):
        super().__init__(f"{code} Client Error\nsecond line")
        self.response = types.SimpleNamespace(status_code=code)


class Hub(types.ModuleType):
    """huggingface_hub for a test: hf_hub_download writes the file asked for unless its repository refuses, and
    HfApi().list_repo_tree lists the plates dataset with its card. `calls` keeps what was asked."""

    def __init__(self, refuse=None):
        super().__init__("huggingface_hub")
        self.refuse, self.calls = refuse or {}, []
        self.HfApi = lambda: types.SimpleNamespace(list_repo_tree=self.list_repo_tree)

    def hf_hub_download(self, repo, path, revision=None, repo_type="model", local_dir=None):
        self.calls.append((repo, path, revision, repo_type))
        if repo in self.refuse:
            raise Refused(self.refuse[repo])
        got = os.path.join(local_dir, path)
        os.makedirs(os.path.dirname(got), exist_ok=True)
        with open(got, "wb") as fh:
            fh.write(b"model")
        return got

    def list_repo_tree(self, repo, repo_type=None, revision=None):
        self.calls.append((repo, "", revision, repo_type))
        return [types.SimpleNamespace(path="README.md", size=900)] + [types.SimpleNamespace(path=p, size=n) for p, n in PLATES.items()]


def run(tool, argv, hub):
    out = io.StringIO()
    with mock.patch.dict(sys.modules, {"huggingface_hub": hub}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = tool.main(argv)
    return code, out.getvalue().splitlines()


class Models(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.models = self.tmp.name

    def test_every_file_lands_in_its_folder_once(self):
        hub = Hub()
        code, lines = run(get_models, [self.models], hub)
        self.assertEqual((code, lines[-1]), (0, f"15 of 15 model files in {self.models}: 15 downloaded, 0 already there"))
        for repo, path, folder in get_models.MODELS:
            self.assertTrue(os.path.isfile(os.path.join(self.models, folder, os.path.basename(path))), path)
            self.assertIn((repo, path, get_models.REVISIONS[repo], "model"), hub.calls, "each file at its tested revision")
        self.assertEqual(sorted(os.listdir(self.models)), sorted({folder for _, _, folder in get_models.MODELS}), "the staging folder is gone")
        again = Hub()
        code, lines = run(get_models, [self.models], again)
        self.assertEqual((code, lines[-1], again.calls), (0, f"15 of 15 model files in {self.models}: 0 downloaded, 15 already there", []))

    def test_a_refusal_names_the_page_to_open(self):
        code, lines = run(get_models, [self.models], Hub({KLEIN: 401, LTX: 403}))
        self.assertEqual(code, 1, "a file the workflows need is missing")
        no_token = [line for line in lines if line.startswith("MISSING: diffusion_models/flux3-image-klein")]
        self.assertTrue(no_token and all(f"https://huggingface.co/{KLEIN}" in line and "set HF_TOKEN" in line and get_models.TOKENS in line for line in no_token), no_token)
        no_licence = [line for line in lines if line.startswith("MISSING: vae/ltx-2.5-video-vae")]
        self.assertTrue(no_licence and all(f"open https://huggingface.co/{LTX} and accept it" in line for line in no_licence), no_licence)
        self.assertTrue(lines[-1].startswith(f"7 of 15 model files in {self.models}: 7 downloaded, 0 already there, 8 missing."), lines[-1])
        self.assertFalse(any("second line" in line for line in lines), "one sentence per file")

    def test_an_optional_file_missing_leaves_the_rest_working(self):
        code, lines = run(get_models, [self.models], Hub({HDR: 403}))
        self.assertEqual((code, lines[-1]), (0, "Off while their files are missing: SDR to HDR. The rest works without them."))
        code, lines = run(get_models, [self.models, "--no-hdr"], Hub())
        self.assertEqual((code, lines[-1]), (0, f"13 of 13 model files in {self.models}: 0 downloaded, 13 already there"))

    def test_list_prints_sizes_and_what_is_in_place_without_the_hub(self):
        os.makedirs(os.path.join(self.models, "vae"))
        with open(os.path.join(self.models, "vae", "flux2-vae.safetensors"), "wb") as fh:
            fh.write(b"model")
        hub = Hub()
        code, lines = run(get_models, [self.models, "--list"], hub)
        self.assertEqual((code, len(lines), hub.calls), (1, 16, []))
        self.assertIn(f"in place    336 MB  vae/flux2-vae.safetensors  ({KLEIN} at feef60b)", lines)
        self.assertIn(f"missing    21.5 GB  diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors  ({LTX} at 49b093a)", lines)
        self.assertEqual(lines[-1], f"1 of 15 model files in place in {self.models}: 61.8 GB to download")
        code, lines = run(get_models, [self.models, "--list", "--only", "flux2-vae.safetensors"], hub)
        self.assertEqual((code, lines[-1]), (0, f"1 of 1 model files in place in {self.models}"))

    def test_every_file_has_its_size_and_the_docstring_its_total(self):
        names = [os.path.basename(path) for _, path, _ in get_models.MODELS + [get_models.NVFP4]]
        self.assertEqual(sorted(names), sorted(get_models.SIZES))
        total = sum(get_models.SIZES[os.path.basename(path)] for _, path, _ in get_models.MODELS)
        self.assertIn(f"about {total / 1e9:.0f} GB in all", " ".join(get_models.__doc__.split()))

    def test_no_models_folder_is_said(self):
        code, lines = run(get_models, [os.path.join(self.models, "absent")], Hub())
        self.assertEqual((code, lines), (2, ["Name ComfyUI's models folder: python get_models.py path/to/ComfyUI/models"]))

    def test_the_folders_of_the_comfyui_the_pack_is_in(self):
        pack = os.path.join(self.models, "ComfyUI", "custom_nodes", "ainvfx-paintaplate")
        for folder in (pack, os.path.join(self.models, "ComfyUI", "models"), os.path.join(self.models, "ComfyUI", "input")):
            os.makedirs(folder)
        with mock.patch.object(get_models, "__file__", os.path.join(pack, "get_models.py")):
            self.assertEqual(get_models.comfy_folder("models"), os.path.join(self.models, "ComfyUI", "models"))
            self.assertIsNone(get_models.comfy_folder("output"))
            code, lines = run(get_plates, [], Hub())
        self.assertEqual((code, lines[-1]), (0, f"2 of 2 example plates in {os.path.join(self.models, 'ComfyUI', 'input', 'plates')}: 2 downloaded, 0 already there"))


class Plates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = os.path.join(self.tmp.name, "input", "plates")

    def test_the_mp4_files_of_the_dataset_land_once(self):
        hub = Hub()
        code, lines = run(get_plates, [self.folder], hub)
        self.assertEqual((code, lines[-1]), (0, f"2 of 2 example plates in {self.folder}: 2 downloaded, 0 already there"))
        self.assertEqual(sorted(os.listdir(self.folder)), sorted(PLATES), "the plates only: no card, no staging folder")
        self.assertIn((get_plates.REPO, "horse.mp4", "main", "dataset"), hub.calls)
        again = Hub()
        code, lines = run(get_plates, [self.folder, "--revision", "7a5bbf9"], again)
        self.assertEqual((code, lines[-1], again.calls), (0, f"2 of 2 example plates in {self.folder}: 0 downloaded, 2 already there", [(get_plates.REPO, "", "7a5bbf9", "dataset")]))

    def test_list_and_only(self):
        code, lines = run(get_plates, [self.folder, "--list"], Hub())
        self.assertEqual((code, lines), (1, [f"missing       6 MB  horse.mp4  ({get_plates.REPO} at main)", f"missing       5 MB  tea.mp4  ({get_plates.REPO} at main)",
                                             f"0 of 2 example plates in place in {self.folder}: 12 MB to download"]))
        self.assertFalse(os.path.exists(self.folder), "--list downloads nothing and makes no folder")
        code, lines = run(get_plates, [self.folder, "--only", "horse.mp4"], Hub())
        self.assertEqual((code, os.listdir(self.folder)), (0, ["horse.mp4"]))
        code, lines = run(get_plates, [self.folder, "--only", "cow.mp4"], Hub())
        self.assertEqual((code, lines), (2, ["The dataset has no plate named cow.mp4: python get_plates.py --list names them all."]))

    def test_no_network_is_one_sentence(self):
        hub = Hub()
        hub.list_repo_tree = mock.Mock(side_effect=OSError("Name or service not known"))
        code, lines = run(get_plates, [self.folder], hub)
        self.assertEqual((code, lines), (1, [f"The list of plates did not come from huggingface.co/datasets/{get_plates.REPO}: Name or service not known"]))

    def test_the_pod_scripts_call_the_same_tool(self):
        for script, call in (("pod_setup.sh", 'python "$PACK/get_plates.py" "$W/ComfyUI/input/plates"'), ("runpod_start.sh", '"$HERE/get_plates.py" "$W/ComfyUI/input/plates"'),
                             ("get_plates.sh", '/../get_plates.py"')):
            with open(os.path.join(ROOT, "tools", script), encoding="utf-8") as fh:
                self.assertIn(call, fh.read(), script)


if __name__ == "__main__":
    unittest.main()
