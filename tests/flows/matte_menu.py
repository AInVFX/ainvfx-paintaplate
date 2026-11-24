"""The matte menu under a paint's row (tests/flows/README.md): « Auto » shows Follow Matte's choice; another strategy runs the
matte and the composite again and takes the shot from the job index; undo and redo carry it; a saved scene keeps it and
opens with it; the scene's ComfyUI graph has it as Follow Matte's input."""
import io
import json
import zipfile

MENU = "#history li select.matte"


def run(browser, port, U):
    U.mock_route(port, "/mock/follow", {"auto": "Object and effects"})
    page = U.load(browser, port)
    errors = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    posted = []
    page.on("request", lambda req: posted.append(req.post_data) if req.method == "POST" and req.url.endswith("/prompt") else None)
    U.open_plate(page)
    page.fill("#prompt", "a red fire"); page.evaluate("document.activeElement.blur()")
    U.stroke(page, [(0.3, 0.5), (0.4, 0.52), (0.5, 0.5)])
    page.click("#generate")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    U.wait_log(page, "document.querySelector('#render-left').textContent === 'full size ready'", 180000, "full-size composite")
    U.settled(page)
    texts = lambda: page.eval_on_selector_all(f"{MENU} option", "os => os.map((o) => o.textContent)")  # noqa: E731
    U.check(texts() == ["Auto: Object and effects", "Object", "Object and effects", "Whole shot"] and page.input_value(MENU) == "Auto",
            f"a paint's row has the menu; « Auto » shows Follow Matte's choice: {texts()} {page.input_value(MENU)!r}")
    matte = [json.loads(b)["prompt"] for b in posted if b and '"PaintAPlate_FollowMatte"' in b]
    U.check(matte and all(n["inputs"].get("strategy") == "Auto" for p in matte for n in p.values() if n["class_type"] == "PaintAPlate_FollowMatte"),
            f"Generate posts the paint matte with « Auto »: {len(matte)} matte jobs")
    page.evaluate(U.WATCH)
    del posted[:]
    page.select_option(MENU, "Whole shot")
    U.wait_log(page, U.added_line("Edit 1: matte Whole shot. The matte and the composite run again."), 10000, "the menu's log line")
    U.wait_log(page, "document.querySelector('#render-left').textContent === 'full size ready'", 180000, "full-size composite again")
    U.settled(page)
    grew = U.added(page, ("edit", "shot", "matte", "comp", "review"))
    matte = [json.loads(b)["prompt"] for b in posted if b and '"PaintAPlate_FollowMatte"' in b]
    strategies = {n["inputs"].get("strategy") for p in matte for n in p.values() if n["class_type"] == "PaintAPlate_FollowMatte"}
    U.check(grew["shot: posted"] == 0 and grew["edit: posted"] == 0 and grew["shot: made before"] >= 1 and grew["matte: posted"] >= 1
            and grew["review: posted"] >= 1 and strategies == {"Whole shot"},
            f"another strategy runs the matte and the composite, and takes the shot from the job index: {grew} {strategies}")
    U.check(page.input_value(MENU) == "Whole shot", f"the menu shows the strategy chosen: {page.input_value(MENU)!r}")
    page.click("#undo-btn")
    U.until(page, f"document.querySelector('{MENU}').value === 'Auto'")
    U.check(page.input_value(MENU) == "Auto", "undo brings « Auto » back")
    page.click("#redo-btn")
    U.until(page, f"document.querySelector('{MENU}').value === 'Whole shot'")
    U.check(page.input_value(MENU) == "Whole shot", "redo brings « Whole shot » back")
    U.settled(page)
    name, scene = U.save_scene(page)
    U.check([e.get("matte") for e in scene["edits"]] == ["Whole shot"], f"the saved scene keeps the strategy: {[e.get('matte') for e in scene['edits']]}")
    with page.expect_download(timeout=180000) as dl:
        page.click("#export-btn"); page.check("#x-graph"); page.click("#x-go")
    graph = json.loads(zipfile.ZipFile(io.BytesIO(open(dl.value.path(), "rb").read())).read("scene.comfyui.json"))
    follow = [n for n in graph["nodes"] if n.get("type") == "PaintAPlate_FollowMatte"]
    U.check(follow and all("Whole shot" in n.get("widgets_values", []) for n in follow),
            f"the scene's ComfyUI graph has the strategy as Follow Matte's input: {[n.get('widgets_values') for n in follow]}")
    page.evaluate(U.WATCH)
    U.open_scene(page, name)
    U.wait_log(page, U.added_line("Scene opened"), 120000, "the scene opened")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    U.until(page, f"!!document.querySelector('{MENU}')")
    U.check(page.input_value(MENU) == "Whole shot", f"the scene opens with the strategy: {page.input_value(MENU)!r}")
    U.check(not errors, f"no page errors: {errors}")
    page.close()
