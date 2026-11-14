"""SDR to HDR on a plate with no edit: the plate is its own SDR shot, brought into the model space at the working size,
and its HDR frames come back at the plate's size and frame count. A shot from the shot pass goes through as before."""
import json, os, socket, subprocess, sys, tempfile, time, unittest, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path[:0] = [REPO, os.path.join(REPO, "tools")]
import build_workflows  # noqa: E402


def titled(prompt, title):
    found = [nid for nid, n in prompt.items() if n.get("_meta", {}).get("title", n.get("title")) == title]
    assert len(found) == 1, (title, found)
    return found[0]


def filled(values):
    wf = build_workflows.fill("hdr", values)
    return wf[0] if isinstance(wf, tuple) else wf


PLATE = {"path": "plates/desk.mp4", "color_space": "sRGB - Display", "width": 1920, "height": 1088, "plate_width": 1920,
         "plate_height": 1080}


class HdrOnAPlate(unittest.TestCase):
    def setUp(self):
        self.prompt = build_workflows.load("hdr")[0]

    def test_a_shot_goes_through_as_it_is(self):
        """With no plate size (a shot), the plate_level link goes with the nodes that set a plate's level, and the rest
        passes the shot on with no copy: Color Space (OCIO) from @model to @model, Upscale Image at 0 x 0, HDR Match
        with no plate."""
        p = filled({"path": "output/shot", "max_frames": 121})
        conv = p[titled(p, "SDR shot in the model space")]["inputs"]
        self.assertEqual((conv["source"], conv["destination"]), ("@model", "@model"))
        work = p[titled(p, "SDR shot at the working size")]["inputs"]
        self.assertEqual((work["width"], work["height"]), (0, 0))
        match = p[titled(p, "HDR Match: the HDR frames at the plate's level")]["inputs"]
        self.assertEqual(sorted(k for k, v in match.items() if isinstance(v, list)), ["image"])
        titles = {n.get("_meta", {}).get("title") for n in p.values()}
        self.assertFalse(titles & {"HDR frames at the plate's size", "Plate in ACEScg, for HDR Match", "Nothing changed: an empty matte"})
        self.assertNotIn("SolidMask", {n["class_type"] for n in p.values()})

    def test_a_plate_fills_the_slots(self):
        wf = filled(PLATE)
        self.assertEqual(wf[titled(wf, "SDR shot in the model space")]["inputs"]["source"], "sRGB - Display")
        work = wf[titled(wf, "SDR shot at the working size")]["inputs"]
        back = wf[titled(wf, "HDR frames at the plate's size")]["inputs"]
        self.assertEqual((work["width"], work["height"], back["width"], back["height"]), (1920, 1088, 1920, 1080))
        self.assertEqual(back["upscale_method"], "bilinear")  # no overshoot above a highlight, no value below 0

    def test_a_plate_is_set_to_its_own_level(self):
        """HDR Match fits the HDR frames at the plate's size to the plate in ACEScg with an empty matte: nothing changed,
        so the whole plate's mid-tones set the level, as an edit's untouched pixels do."""
        wf = filled(PLATE)
        load = titled(wf, "Shot (SDR)")
        match = wf[titled(wf, "HDR Match: the HDR frames at the plate's level")]["inputs"]
        plate, mask = wf[str(match["plate"][0])], wf[str(match["mask"][0])]
        self.assertEqual((plate["class_type"], plate["inputs"]["source"], plate["inputs"]["destination"]),
                         ("PaintAPlate_ColorSpace", "sRGB - Display", "ACEScg"))
        self.assertEqual(str(plate["inputs"]["image"][0]), load)
        self.assertEqual((mask["class_type"], mask["inputs"]["value"]), ("SolidMask", 0.0))
        size = wf[str(mask["inputs"]["width"][0])]
        self.assertEqual((size["class_type"], str(size["inputs"]["image"][0])), ("GetImageSize", load))
        self.assertEqual((str(match["hdr"][0]), match["grow"]), (titled(wf, "HDR frames at the plate's size"), 0.0))

    def test_an_empty_matte_fits_the_whole_plate(self):
        """HDR Match's measure with nothing changed: every sample is untouched, and one gain per channel brings the HDR
        frames to the plate's level."""
        import numpy as np
        import mathops
        rng = np.random.default_rng(1)
        plate = rng.uniform(0.05, 0.9, (3, 96, 128, 3)).astype(np.float32)
        hdr = plate * np.array([2 ** 0.3, 2 ** -0.2, 2 ** 0.1], np.float32)
        frames, _ = mathops.hdr_match(3, lambda i: hdr[i], lambda i: plate[i], lambda i: np.zeros((96, 128), np.float32),
                                      grow=0.0, step=2, workers=1)
        np.testing.assert_allclose(np.stack(frames), plate, rtol=0.02)

    def test_the_guide_and_keep_black_read_the_sdr_shot(self):
        p = self.prompt
        work = titled(p, "SDR shot at the working size")
        guide = p[titled(p, "Guide: the shot from sRGB to ACEScct")]["inputs"]["image"]
        black = [n for n in p.values() if n["class_type"] == "PaintAPlate_KeepBlack"][0]["inputs"]["sdr"]
        self.assertEqual((guide[0], black[0]), (work, work))

    def test_the_result_keeps_the_plates_frame_count(self):
        p = self.prompt
        load = titled(p, "Shot (SDR)")
        savers = [n for n in p.values() if n["class_type"] in ("PaintAPlate_SaveFrames", "PaintAPlate_SaveMovie")]
        self.assertEqual(len(savers), 2)
        for n in savers:  # Load Plate's 'frames': the plate's own count, without the 8n+1 padding
            self.assertEqual(n["inputs"]["frames"], [load, 4])


def exr_shape(path):
    import OpenEXR
    if hasattr(OpenEXR, "File"):
        with OpenEXR.File(path) as f:
            return next(iter(f.channels().values())).pixels.shape[:2]
    box = OpenEXR.InputFile(path).header()["dataWindow"]
    return (box.max.y - box.min.y + 1, box.max.x - box.min.x + 1)


class StandInAnswer(unittest.TestCase):
    """The page suite's stand-in ComfyUI answers SDR to HDR as the workflow does: Load Plate's frame count, the working
    size when the slots give one, and the plate's size when the slots give it."""

    def test_frames_at_the_given_size_and_the_plates_count(self):
        import av
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        root = tempfile.mkdtemp(prefix="hdr_plate_")
        mock = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_comfy.py"), "--port", str(port), "--root", root,
                                 "--speed", "16", "--plate"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        url = f"http://127.0.0.1:{port}"
        try:
            for _ in range(120):
                try:
                    urllib.request.urlopen(url + "/system_stats", timeout=2).close()
                    break
                except OSError:
                    time.sleep(0.5)
            plate = next(os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f == "desk.mp4")
            with av.open(plate) as c:
                count = min(50, sum(1 for _ in c.decode(video=0)))  # Load Plate pads 50 frames to 57 for LTX
            for name, values, size in (("a", {"width": 96, "height": 64}, (64, 96)),
                                       ("b", {"width": 96, "height": 64, "plate_width": 90, "plate_height": 50}, (50, 90))):
                wf = filled({"path": "plates/desk.mp4", "max_frames": 50, "prefix": f"t/{name}/f", "video_prefix": f"t/{name}_movie",
                             **values})
                req = urllib.request.Request(url + "/prompt", data=json.dumps({"prompt": wf, "client_id": "t"}).encode(),
                                             headers={"Content-Type": "application/json"})
                pid = json.loads(urllib.request.urlopen(req, timeout=10).read())["prompt_id"]
                for _ in range(400):
                    if json.loads(urllib.request.urlopen(f"{url}/history/{pid}", timeout=5).read()).get(pid, {}).get("outputs"):
                        break
                    time.sleep(0.25)
                folder = next(d for d, _, fs in os.walk(root) if d.endswith(os.path.join("t", name)) and any(f.endswith(".exr") for f in fs))
                exrs = sorted(f for f in os.listdir(folder) if f.endswith(".exr"))
                self.assertEqual((len(exrs), exr_shape(os.path.join(folder, exrs[0]))), (count, size))
        finally:
            mock.terminate()
            mock.wait(10)


if __name__ == "__main__":
    unittest.main()
