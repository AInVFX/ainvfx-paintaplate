"""Export of a Paint over a fluid shot, « ComfyUI graph » ticked (tests/flows/README.md): the zip holds two graphs, named
after what each makes, the fluid shot's and the edits'. Every keyframe's image and every image of the edit are in input/.
The edits' graph reads the fluid shot where the fluid shot's graph writes it, and each README names the other graph."""
import json
import os
import zipfile

import zip_rows


def widgets(graph, cls):  # the widget values of the nodes of one class, in a graph in the editor's format
    return [n.get("widgets_values", []) for n in graph["nodes"] if n.get("type") == cls]


def readme(graph):
    return next(n["widgets_values"][0] for n in graph["nodes"] if n.get("type") == "MarkdownNote")


def run(browser, port, U):
    page = U.load(browser, port)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "17")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    page.evaluate(U.WATCH)
    U.paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Fluid shot, full size: done in"), 240000, "the fluid shot")
    page.click(".tools [data-tool=paint]"); page.fill("#prompt", "a red ball"); page.evaluate("document.activeElement.blur()")
    U.stroke(page, [(0.45, 0.45), (0.55, 0.55)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, full size: done in"), 240000, "the Paint's full-size composite")
    page.click("#export-btn")
    U.check(page.is_visible("#x-graph"), "a Paint over a fluid shot offers « ComfyUI graph »")
    page.check("#x-graph")
    with page.expect_download(timeout=180000) as dl:
        page.click("#x-go")
    z = zipfile.ZipFile(dl.value.path())
    names = z.namelist()
    fluid, edits = zip_rows.files(names, "fluid_shot_comfyui_graph"), zip_rows.files(names, "edits_comfyui_graph")
    U.check(len(fluid) == 1 and len(edits) == 1 and not zip_rows.files(names, "comfyui_graph"),
            f"two graphs, each named after what it makes: {sorted(n for n in names if n.endswith('.json'))}")
    fg, eg = json.loads(z.read(fluid[0])), json.loads(z.read(edits[0]))
    keys = [k["image"] for vals in widgets(fg, "PaintAPlate_KeyframeVideo") for v in vals if isinstance(v, str) and v.startswith("[") for k in json.loads(v)]
    U.check(keys and all(f"input/{k}" in names for k in keys), f"every keyframe's image is in input/: {keys}")
    images = [vals[0] for vals in widgets(eg, "PaintAPlate_LoadPlate") if not any(c in vals[0] for c in "/\\:")]  # the edit's images: the plate sits in the output folder
    U.check(images and all(f"input/{v}" in names for v in images), f"every image of the edit is in input/: {images}")
    blank = widgets(fg, "PaintAPlate_LoadPlate")[0][0]
    shot = f"output:{widgets(fg, 'PaintAPlate_SavePlate')[0][0]}/{os.path.basename(blank)}"  # Save Plate names the movie after the blank plate
    U.check([vals[0] for vals in widgets(eg, "PaintAPlate_LoadPlate") if vals[0] not in images] == [shot], f"the edits' graph reads the fluid shot its graph writes: {shot}")
    U.check(f"Then run {edits[0]}." in readme(fg) and f"First run {fluid[0]}." in readme(eg),
            "each README names the graph to run before it or after it, by its name in the zip")
    lines = U.log_lines(page)
    U.check(any("ComfyUI graph 1 of 2, fluid shot." in line for line in lines) and any("ComfyUI graph 2 of 2, edits." in line for line in lines),
            "the download's lines name both graphs, in the order they run")
    page.close()
