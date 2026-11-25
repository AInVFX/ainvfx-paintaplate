"""Export: « ComfyUI graph » is a tick box among Export's parts, and the scene's graph comes in the zip, beside the result;
a fluid shot alone offers it too, its graph beside the shot.
The dialog's words come from one source, none says « The zip downloads at once », and the Help's Export entry opens with
the dialog's own line."""
import json
import zipfile
import zip_rows  # noqa: E402


def loaded(graph):  # the images a graph loads: its image loaders' images, and the keyframes of its Keyframe Video
    names = []
    for n in graph["nodes"]:
        if n.get("type") in ("LoadImage", "LoadImageMask"):
            names.append(n["widgets_values"][0])
        elif n.get("type") == "PaintAPlate_KeyframeVideo":
            names += [k["image"] for v in n.get("widgets_values", []) if isinstance(v, str) and v.startswith("[") for k in json.loads(v)]
    return names


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    page.click('.tools [data-tool="paint"]')
    U.paint_once(page, "a lantern", [(0.3, 0.5), (0.36, 0.5)]); page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    page.click("#export-btn")
    U.check(page.is_visible("#x-graph") and page.get_attribute("#x-graph", "type") == "checkbox" and not page.is_checked("#x-graph"),
            "ComfyUI graph is a tick box among Export's parts, off")
    U.check("downloads at once" not in (page.text_content("#export") or "") and page.text_content("#x-hint").startswith("Export writes the selected files"),
            f"the dialog says what Export does: {page.text_content('#x-hint')!r}, {page.text_content('#x-note')!r}")
    U.check(page.text_content("#help-export").startswith(page.text_content("#x-hint")) and page.text_content("#x-hint") == "Export writes the selected files to ComfyUI's output folder, then downloads them as one zip.",
            f"the Help's Export entry opens with the same line: {page.text_content('#help-export')!r}")
    page.check("#x-graph")
    with page.expect_download(timeout=180000) as dl:
        page.click("#x-go")
    z = zipfile.ZipFile(dl.value.path())
    U.check(zip_rows.files(z.namelist(), "comfyui_graph") and zip_rows.composite(z.namelist()),
            f"the zip holds the graph beside the result: {sorted({n.split('/')[0] for n in z.namelist()})}")
    graph = json.loads(z.read(zip_rows.files(z.namelist(), "comfyui_graph")[0]))
    loads = loaded(graph)
    U.check(loads and all(f"input/{v}" in z.namelist() for v in loads), f"the zip holds every image the graph loads, in input/: {loads}")
    U.check(bool(graph["nodes"]) and bool(graph["groups"]), f"the graph is a ComfyUI workflow: {len(graph['nodes'])} nodes in {len(graph['groups'])} groups")
    page.click("#open-btn"); page.click("#open [data-tab=blank]")  # a fluid shot alone
    page.fill("#b-frames", "17"); page.dispatch_event("#b-frames", "input")
    page.evaluate(U.WATCH)
    page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    U.paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Fluid shot, full size: done in"), 240000, "the fluid shot")
    page.click("#export-btn")
    U.check(page.is_visible("#x-graph"), "a fluid shot alone offers the ComfyUI graph among Export's parts (the box keeps its last choice)")
    page.check("#x-graph")
    with page.expect_download(timeout=180000) as dl:
        page.click("#x-go")
    z = zipfile.ZipFile(dl.value.path())
    U.check(zip_rows.files(z.namelist(), "comfyui_graph") and zip_rows.files(z.namelist(), "fluid_shot_full_size"),
            f"the zip holds the fluid shot's graph beside the shot: {sorted({n.split('/')[0] for n in z.namelist()})}")
    graph = json.loads(z.read(zip_rows.files(z.namelist(), "comfyui_graph")[0]))
    loads = loaded(graph)
    U.check(loads and all(f"input/{v}" in z.namelist() for v in loads), f"the zip holds every image the graph loads, in input/: {loads}")
    titles = [g["title"] for g in graph["groups"]]
    keys = [n for n in graph["nodes"] if n.get("properties", {}).get("Node name for S&R") == "PaintAPlate_KeyframeVideo"]
    U.check(titles[:4] == ["README", "INPUT", "MODELS", "FLUID SHOT"] and len(keys) == 1, f"the graph makes the fluid shot: groups {titles}, {len(keys)} Keyframe Video")
    U.no_errors(errors, "after the exports with their graphs")
    page.close()
