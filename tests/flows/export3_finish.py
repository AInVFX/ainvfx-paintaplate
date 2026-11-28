"""Export with « ComfyUI graph » ticked holds Finish's graph (tests/flows/README.md), job for job the prompts the mock received
from Finish's steps: the same workflow and the same values, paths aside, in the same order. A plate with no edit, upscaled at
its own size, offers the tick and gives Finish's graph alone. A Paint on a plate that holds nothing above 1.0, with SDR to
HDR and Upscale, gives the edits' graph with no SDR to HDR in it, and Finish's graph with SDR to HDR's jobs and Upscale's."""
import io
import json
import urllib.request
import zipfile

import zip_rows

READERS = {"PaintAPlate_LoadPlate": "path", "PaintAPlate_JoinWindows": "folder"}  # paths, set aside with every other path
SAVED = {"HDR frames (half-float EXR, ACES2065-1)": "hdr", "Composite, HDR (half-float EXR, ACES2065-1)": "hdr_comp",
         "Upscaled frames": "upscale", "Upscaled export": "upscale_export"}  # a node title that names each of Finish's workflows


def finish_prompts(port, after=0):
    """The prompts of Finish's workflows the mock received, in the order it received them, from its job `after` on."""
    history = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/history?max_items=100000"))
    found = sorted((h["prompt"][0], h["prompt"][2]) for h in history.values() if h["prompt"][0] >= after)
    return [p for _, p in found if any(n.get("_meta", {}).get("title") in SAVED for n in p.values())]


def signature(n):  # a node, paths and links aside
    keep = {k: v for k, v in n["inputs"].items() if not isinstance(v, list) and READERS.get(n["class_type"]) != k
            and not (isinstance(v, str) and ("paintaplate/" in v or v.startswith("output:")))}
    return f"{n['class_type']} {json.dumps(keep, sort_keys=True)}"


def jobs_of(api):
    """Finish's graph, job by job: each job's nodes and the shared nodes they read (the model loaders), order gates aside."""
    gate = lambda i: "order gate" in api[i]["_meta"]["title"]  # noqa: E731
    out = []
    for k in range(1, 1000):
        todo = [i for i, n in api.items() if f" · job {k} · " in n["_meta"]["title"] and not gate(i)]
        if not todo:
            return out
        seen = set()
        while todo:
            i = todo.pop()
            if i in seen or gate(i):
                continue
            seen.add(i)
            todo += [v[0] for v in api[i]["inputs"].values() if isinstance(v, list)]
        out.append({signature(api[i]) for i in seen})


def same_jobs(U, api, prompts, what):
    jobs = jobs_of(api)
    U.check(len(jobs) == len(prompts) > 0 and all(j == {signature(n) for n in p.values()} for j, p in zip(jobs, prompts)),
            f"{what}: Finish's graph holds the {len(prompts)} jobs Finish's steps posted, in order, value for value, paths aside: {len(jobs)} in the graph")


def export(page, U):  # Export with « ComfyUI graph » ticked: the zip's names and the graphs it holds, by row
    page.click("#export-btn")
    U.check(page.is_visible("#x-graph"), "Export offers « ComfyUI graph »")
    page.check("#x-graph")
    with page.expect_download(timeout=240000) as dl:
        page.click("#x-go")
    z = zipfile.ZipFile(io.BytesIO(open(dl.value.path(), "rb").read()))
    graphs = {zip_rows.row_of(n): json.loads(z.read(n)) for n in z.namelist() if n.endswith("_comfyui_graph.json")}
    return z.namelist(), graphs


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.click("#finish-btn"); page.click("#finish-upscale"); page.select_option("#finish-upscale-size", "0"); page.keyboard.press("Escape")
    names, graphs = export(page, U)
    U.check(list(graphs) == ["comfyui_graph"], f"a plate with no edit, upscaled: Finish's graph alone: {sorted(graphs)}")
    same_jobs(U, graphs["comfyui_graph"]["extra"]["paintaplate"]["prompt"], finish_prompts(port), "Upscale on the plate at its own size")
    mark = max(h["prompt"][0] for h in json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/history?max_items=100000")).values()) + 1
    page.click("#finish-btn"); page.click("#finish-hdr"); page.click("#finish-hdr-yes"); page.keyboard.press("Escape")
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.wait_for_timeout(1500); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, full size: done in"), 240000, "the Paint's composite")
    names, graphs = export(page, U)
    U.check(sorted(graphs) == ["edits_comfyui_graph", "finish_comfyui_graph"], f"a Paint with SDR to HDR and Upscale: the edits' graph and Finish's: {sorted(graphs)}")
    edits = graphs["edits_comfyui_graph"]["extra"]["paintaplate"]["prompt"]
    U.check(not any(n["class_type"] == "LTXVLoadConditioning" for n in edits.values()),
            "on a plate that holds nothing above 1.0, the edits' graph holds no SDR to HDR: the page runs it after the composite")
    finish = graphs["finish_comfyui_graph"]["extra"]["paintaplate"]["prompt"]
    prompts = finish_prompts(port, mark)
    U.check([SAVED[t] for p in prompts for t in (n.get("_meta", {}).get("title") for n in p.values()) if t in SAVED][:3] == ["hdr", "hdr", "hdr_comp"],
            "Finish's steps ran SDR to HDR on the plate and the layer, then the composite, before Upscale")
    same_jobs(U, finish, prompts, "SDR to HDR and Upscale after a Paint")
    page.close()
