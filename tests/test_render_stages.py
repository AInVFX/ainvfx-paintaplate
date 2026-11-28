"""One edit drawn in several strokes, and the sheet of a render's stages at full size: the same frames of the plate, the
clean plate pass, the shot, the paint matte and the composite."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gpu_matrix  # noqa: E402
import ui_live  # noqa: E402


class WithoutPlaywright(unittest.TestCase):
    def test_the_report_s_tools_are_read_without_playwright(self):
        # the unit tests' job has no Playwright: the sheet and the strokes' paths must load without it
        code = ("import sys\n"
                "class Hidden:\n"
                "    def find_spec(self, name, path=None, target=None):\n"
                "        if name.split('.')[0] == 'playwright':\n"
                "            raise ModuleNotFoundError(name)\n"
                "sys.meta_path.insert(0, Hidden())\n"
                "import gpu_matrix, ui_live\n"
                "print(ui_live.paths([[0, 0], [1, 1]]), gpu_matrix.edit_box(['paint', '', [[0.5, 0.5]], 64], 640, 320))\n")
        done = subprocess.run([sys.executable, "-c", code], cwd=HERE, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-400:])
        self.assertIn("[[[0, 0], [1, 1]]]", done.stdout)


def frames(folder, name, values, size=(64, 32)):
    """Image files of one grey level each, named as a sequence: <name>.<number>.png, for (number, level) in values."""
    from PIL import Image
    os.makedirs(folder, exist_ok=True)
    paths = []
    for number, value in values:
        paths.append(os.path.join(folder, f"{name}.{number:04d}.png"))
        Image.new("RGB", size, (value, value, value)).save(paths[-1])
    return paths


def movie(path, values, size=(64, 32)):
    """A movie of one grey level per frame."""
    import av
    import numpy as np
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with av.open(path, "w") as c:
        stream = c.add_stream("mpeg4", rate=24)
        stream.width, stream.height, stream.pix_fmt = size[0], size[1], "yuv420p"
        for v in values:
            for packet in stream.encode(av.VideoFrame.from_ndarray(np.full((size[1], size[0], 3), v, np.uint8), format="rgb24")):
                c.mux(packet)
        for packet in stream.encode():
            c.mux(packet)
    return path


class Strokes(unittest.TestCase):
    def test_one_path_or_several_are_the_strokes_of_one_edit(self):
        one, two = [[0.1, 0.2], [0.3, 0.4]], [[[0.1, 0.2], [0.1, 0.6]], [[0.7, 0.2], [0.7, 0.6]]]
        self.assertEqual(ui_live.paths(one), [one])
        self.assertEqual(ui_live.paths(two), two)

    def test_an_edit_s_box_holds_every_stroke_and_half_its_brush(self):
        box = gpu_matrix.edit_box(["paint", "", [[[0.2, 0.2], [0.2, 0.5]], [[0.7, 0.1], [0.7, 0.5]]], 20], 1000, 500)
        self.assertEqual(box, (190.0, 40.0, 710.0, 260.0))

    def test_the_car_case_cleans_then_paints_two_strokes_as_one_edit_outside_quick_and_all(self):
        car = gpu_matrix.load_cases()["car_trees"]
        self.assertEqual([s[0] for s in car["strokes"]], ["erase", "paint"])
        self.assertEqual(len(ui_live.paths(car["strokes"][1][2])), 2)
        self.assertNotIn("car_trees", gpu_matrix.ALL)
        self.assertTrue(all(1 <= n <= 121 for n in car["stage_frames"]))


class Stages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="stages_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_each_stage_is_the_last_job_of_its_name_and_folder_its_movie_first_else_its_frames(self):
        out = os.path.join(self.tmp, "output", "paintaplate", "p")
        clean = frames(os.path.join(out, "matte_a"), "m", [(1, 255), (2, 0)])  # the Clean's tracking: the clean plate pass's hole
        matte = frames(os.path.join(out, "matte_b_full"), "m", [(1, 255), (2, 255), (3, 0)])
        frames(os.path.join(out, "matte_b_full"), "x", [(1, 0)])  # another node's files in the same folder
        movie_ = {"class_type": "PaintAPlate_SaveMovie"}
        saves = {  # job: (its graph's save nodes, the files ComfyUI lists for each)
            "aaaaaaaa": ({"16": {"class_type": "PaintAPlate_SaveFrames"}}, {"16": [("paintaplate/p/matte_a", "m.0001.png")]}),
            "bbbbbbbb": ({"35": {"class_type": "PaintAPlate_SaveFrames"}, "36": movie_}, {"35": [("paintaplate/p/full/clean", "f.0001.png")], "36": [("paintaplate/p/full", "clean.mp4")]}),
            "cccccccc": ({"31": movie_}, {"31": [("paintaplate/p", "shot_00001_.mp4")]}),
            "dddddddd": ({"31": movie_}, {"31": [("paintaplate/p", "shot_00002_.mp4")]}),
            "eeeeeeee": ({"16": {"class_type": "PaintAPlate_SaveFrames"}}, {"16": [("paintaplate/p/matte_b_full", "m.0001.png")]}),
        }
        history = {job + "-0000": {"prompt": [0, job, graph], "outputs": {node: {"images": [{"subfolder": sub, "filename": name} for sub, name in files]} for node, files in listed.items()}}
                   for job, (graph, listed) in saves.items()}
        jobs = [{"id": job, "name": name} for job, name in (("aaaaaaaa", "matte"), ("bbbbbbbb", "cleanup"), ("cccccccc", "shot"), ("dddddddd", "shot"),
                                                             ("eeeeeeee", "matte"), ("ffffffff", "review"))]  # review: not in this ComfyUI's history
        found = gpu_matrix.stage_movies(self.tmp, jobs, history)
        self.assertEqual(found["Clean plate pass"], os.path.join(out, "full", "clean.mp4"))
        self.assertEqual(found["Shot"], os.path.join(out, "shot_00002_.mp4"))
        self.assertEqual((found["Clean matte"], found["Paint matte"]), (clean, matte))
        self.assertNotIn("Composite", found)

    def test_the_sheet_shows_the_same_frames_of_each_stage_by_the_plate_s_own_numbers(self):
        from PIL import Image
        plate = os.path.join(self.tmp, "plate")
        frames(plate, "plate", [(480 + k, 40 * k) for k in range(5)])
        movies = {"Clean plate pass": movie(os.path.join(self.tmp, "clean.mp4"), [10 + 40 * k for k in range(5)]),
                  "Shot": frames(os.path.join(self.tmp, "shot"), "f", [(k + 1, 20 + 40 * k) for k in range(5)]),
                  "Paint matte": frames(os.path.join(self.tmp, "matte"), "m", [(k + 1, 255 * (k % 2)) for k in range(5)])}
        made = gpu_matrix.stage_sheet({"stage_frames": [480, 482, 484, 999]}, self.tmp, plate, movies)
        self.assertEqual(made["frames"], [480, 482, 484])
        self.assertEqual(made["columns"], ["Plate", "Clean plate pass", "Shot", "Paint matte"])  # no export.zip in this folder
        self.assertEqual(made["missing"], ["Clean matte", "Composite"])
        (cw, ch), gap, head, left = gpu_matrix.SHEET_CELL, 8, 24, 76
        picture = Image.open(made["path"]).convert("RGB")
        self.assertEqual(picture.size, (left + 4 * (cw + gap), head + 3 * (ch + gap)))
        level = lambda r, c: picture.getpixel((left + c * (cw + gap) + 10, head + r * (ch + gap) + 10))[0]  # noqa: E731
        self.assertEqual([level(1, 0), level(1, 2), level(1, 3)], [80, 100, 0])  # frame 482: the third file of each sequence
        self.assertLess(abs(level(1, 1) - 90), 6)  # the movie's third frame, through its compression
        self.assertEqual(gpu_matrix.stage_sheet({}, self.tmp, os.path.join(self.tmp, "none"), movies), {"error": "the plate is not in ComfyUI's input folder"})

    def test_the_sheet_s_composite_is_the_export_from_the_case_s_zip(self):
        import zipfile
        from PIL import Image
        plate = os.path.join(self.tmp, "plate")
        frames(plate, "plate", [(1, 0), (2, 40)])
        made = frames(os.path.join(self.tmp, "made"), "f", [(1, 200), (2, 220)])
        with zipfile.ZipFile(os.path.join(self.tmp, "export.zip"), "w") as z:
            for k, path in enumerate(made):
                z.write(path, f"export/plate.{k + 1:04d}.png")
        result = gpu_matrix.stage_sheet({"stage_frames": [1, 2]}, self.tmp, plate, {})
        self.assertEqual(result["columns"], ["Plate", "Composite"])
        self.assertEqual(result["missing"], ["Clean matte", "Clean plate pass", "Shot", "Paint matte"])
        (cw, ch), gap, head, left = gpu_matrix.SHEET_CELL, 8, 24, 76
        self.assertEqual(Image.open(result["path"]).convert("RGB").getpixel((left + cw + gap + 10, head + ch + gap + 10))[0], 220)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "stage_files")))

    def test_a_movie_plate_counts_its_frames_from_1_and_a_sequence_by_its_files(self):
        self.assertEqual(gpu_matrix.frame_numbers(movie(os.path.join(self.tmp, "p.mp4"), [0, 50, 100])), [1, 2, 3])
        self.assertEqual(gpu_matrix.frame_numbers(["/a/tos_05_4a.000480.exr", "/a/tos_05_4a.000481.exr"]), [480, 481])


if __name__ == "__main__":
    unittest.main()
