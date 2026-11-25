"""The matte menu under a paint's row (tests/flows/README.md), on a 16 GB GPU with the shot preview off:
« Auto » shows Follow Matte's choice; another strategy runs the matte and the composite again, takes the shot from the
render of the same edits (never the shot again, job index or not), and every free keeps ComfyUI's cache, so SAM 3.1's
answers serve again; undo and redo carry it; a saved scene keeps it and opens with it; the scene's ComfyUI graph has it as
Follow Matte's input; the Help says what the tooltips say."""
import io
import json
import zipfile

import zip_rows

MENU = "#history li label.matte select"
CARD = {"vram": 17.2e9, "ram": 65.5e9}  # a 16 GB GPU with 61 GB of RAM: the small profile, which frees between families
SIGNATURE = """(() => { const c = document.querySelector('#view'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
  let s = 0; for (let i = 0; i < d.length; i += 4 * 97) s += d[i] + 2 * d[i + 1] + 3 * d[i + 2]; return s; })()"""  # the viewer's picture, in one number


def frees(page, port, U, seen_lines, seen_events):  # each « Memory freed before … » line with the free_memory the page posted
    lines = [t for t in U.log_lines(page)[seen_lines:] if t.startswith("Memory freed before")]
    events = [e for e in U.mock_route(port, "/mock/events") if e[0] == "free"][seen_events:]
    return [(line.split(":")[0].removeprefix("Memory freed before "), e[2]) for line, e in zip(lines, events)], len(lines) == len(events)


def run(browser, port, U):
    U.mock_route(port, "/mock/follow", {"auto": "Object and effects"})
    U.mock_route(port, "/mock/card", CARD)
    page = U.load(browser, port)
    errors = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    posted = []
    page.on("request", lambda req: posted.append(req.post_data) if req.method == "POST" and req.url.endswith("/prompt") else None)
    U.open_plate(page)
    page.fill("#prompt", "a red fire"); page.evaluate("document.activeElement.blur()")
    U.stroke(page, [(0.3, 0.5), (0.4, 0.52), (0.5, 0.5)])
    page.select_option("#preview-size", label="Off")
    seen = (len(U.log_lines(page)), sum(e[0] == "free" for e in U.mock_route(port, "/mock/events")))
    page.click("#generate")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    U.wait_log(page, "document.querySelector('#render-left').textContent === 'full size ready'", 180000, "full-size composite")
    U.settled(page)
    texts = lambda: page.eval_on_selector_all(f"{MENU} option", "os => os.map((o) => o.textContent)")  # noqa: E731
    U.check(texts() == ["Auto: Object and effects", "Object", "Object and effects", "Whole shot"] and page.input_value(MENU) == "Auto",
            f"a paint's row has the menu; « Auto » shows Follow Matte's choice: {texts()} {page.input_value(MENU)!r}")
    made, paired = frees(page, port, U, *seen)
    U.check(paired and dict(made).get("the matte") is True and dict(made).get("the review movie") is False,
            f"Generate on a 16 GB GPU: the free before the matte clears ComfyUI's cache, the one before the review movie keeps it: {made}")
    label = page.text_content("#history li label.matte span")
    widths = page.evaluate(f"""() => {{ const m = document.querySelector('{MENU}'), was = m.value;
      const w = [...m.options].map((o) => {{ m.value = o.value; return m.offsetWidth; }}); m.value = was; return w; }}""")
    lines, left, thumb = page.evaluate("""() => { const li = document.querySelector('#history li'), l = li.querySelector('label.matte');
      return [l.querySelector('span').getClientRects().length, l.getBoundingClientRect().left, li.querySelector('.thumb').getBoundingClientRect().left]; }""")
    U.check(label == "Matte strategy" and len(set(widths)) == 1 and lines == 1 and abs(left - thumb) < 1,
            f"the menu has its label on one line under the thumbnail, and one width for every choice: {label!r} {lines} line(s), "
            f"left {left:.0f} against the thumbnail's {thumb:.0f}, widths {widths}")
    matte = [json.loads(b)["prompt"] for b in posted if b and '"PaintAPlate_FollowMatte"' in b]
    U.check(matte and all(n["inputs"].get("strategy") == "Auto" for p in matte for n in p.values() if n["class_type"] == "PaintAPlate_FollowMatte"),
            f"Generate posts the paint matte with « Auto »: {len(matte)} matte jobs")
    page.evaluate(U.WATCH)
    page.select_option(MENU, "Object and effects")  # the strategy « Auto » chose: its render stands for it
    U.wait_log(page, U.added_line("Edit 1: matte Object and effects."), 10000, "the menu's line for the strategy Auto chose")
    U.settled(page)
    grew = U.added(page, ("shot", "matte", "comp", "review"))
    said = page.evaluate("window.__lines")
    U.check(sum(grew[f"{s}: posted"] for s in ("shot", "matte", "comp", "review")) == 0 and page.input_value(MENU) == "Object and effects"
            and not any("run again" in t for t in said if t.startswith("Edit 1: matte")),
            f"« Object and effects », which « Auto » chose: Auto's render stands for it, and nothing runs: {grew}")
    page.evaluate(U.WATCH)
    del posted[:]
    seen = (len(U.log_lines(page)), sum(e[0] == "free" for e in U.mock_route(port, "/mock/events")))
    page.hover("#history li .title")  # the pointer on the row: frame 0 shows the edit's strokes until the menu changes
    page.select_option(MENU, "Whole shot")
    U.wait_log(page, U.added_line("Edit 1: matte Whole shot. The matte and the composite run again."), 10000, "the menu's log line")
    U.wait_log(page, "document.querySelector('#render-left').textContent === 'full size ready'", 180000, "full-size composite again")
    U.settled(page)
    grew = U.added(page, ("edit", "shot", "matte", "comp", "review"))
    matte = [json.loads(b)["prompt"] for b in posted if b and '"PaintAPlate_FollowMatte"' in b]
    strategies = {n["inputs"].get("strategy") for p in matte for n in p.values() if n["class_type"] == "PaintAPlate_FollowMatte"}
    reused = page.evaluate("window.__lines.some((t) => t.includes('Shot, full size: reused from render v1.'))")
    U.check(grew["shot: posted"] == 0 and grew["edit: posted"] == 0 and grew["shot: made before"] == 0 and reused and grew["matte: posted"] >= 1
            and grew["review: posted"] >= 1 and strategies == {"Whole shot"},
            f"another strategy runs the matte and the composite, and takes the shot from render v1, not from the job index: {grew} {strategies}")
    changed, paired = frees(page, port, U, *seen)
    U.check(paired and changed and all(flag is False for _, flag in changed),
            f"a change of strategy: every free keeps ComfyUI's cache, so SAM's answers serve again: {changed}")
    U.check(page.input_value(MENU) == "Whole shot", f"the menu shows the strategy chosen: {page.input_value(MENU)!r}")
    page.hover("#frame-now")  # from the menu to the viewer, as after a choice in the menu's popup
    page.wait_for_timeout(U.QUIET_MS)
    shown = page.evaluate(SIGNATURE)
    page.hover("#history li .title"); page.hover("#frame-now")  # a hover that starts and ends: frame 0 without strokes
    page.wait_for_timeout(U.QUIET_MS)
    clean = page.evaluate(SIGNATURE)
    U.check(shown == clean, f"after a change of strategy, frame 0 shows the new composite, not the edit's strokes: {shown} {clean}")
    page.evaluate(U.WATCH)
    page.select_option(MENU, "Auto")  # back to the strategy of the first render: it shows at once
    U.wait_log(page, U.added_line("Edit 1: matte Auto."), 10000, "the menu's line for a strategy made before")
    U.settled(page)
    grew = U.added(page, ("shot", "matte", "comp", "review"))
    lines = page.evaluate("window.__lines")
    U.check(sum(grew[f"{s}: posted"] for s in ("shot", "matte", "comp", "review")) == 0 and "Edit 1: matte Auto." in lines
            and not any("run again" in line for line in lines if line.startswith("Edit 1: matte")),
            f"back to a strategy made before: it shows at once, nothing runs, and the log says no more: {grew}")
    U.check(texts()[0] == "Auto: Object and effects", f"back on « Auto », the menu shows its choice again: {texts()}")
    page.select_option(MENU, "Whole shot")
    U.settled(page)
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
    with zipfile.ZipFile(io.BytesIO(open(dl.value.path(), "rb").read())) as z:
        graph = json.loads(z.read(zip_rows.files(z.namelist(), "comfyui_graph")[0]))  # the zip names the graph after the plate
    follow = [n for n in graph["nodes"] if n.get("type") == "PaintAPlate_FollowMatte"]
    U.check(follow and all("Whole shot" in n.get("widgets_values", []) for n in follow),
            f"the scene's ComfyUI graph has the strategy as Follow Matte's input: {[n.get('widgets_values') for n in follow]}")
    page.evaluate(U.WATCH)
    U.open_scene(page, name)
    U.wait_log(page, U.added_line("Scene opened"), 120000, "the scene opened")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    U.until(page, f"!!document.querySelector('{MENU}')")
    U.check(page.input_value(MENU) == "Whole shot", f"the scene opens with the strategy: {page.input_value(MENU)!r}")
    helped = page.evaluate("""() => { const dt = [...document.querySelectorAll('#help [data-help=tools] dt')].find((d) => d.textContent === 'Matte strategy');
      return dt ? dt.nextElementSibling.textContent : ''; }""")
    U.check(helped.startswith("Sets how a paint edit is composited back into the plate.") and helped.endswith("Auto picks Object or Object and effects, from what the edit changed.") and all(
            page.evaluate("(t) => [...document.querySelectorAll('#history li label.matte option')].find((o) => o.value === t)?.title", t).lower()
            in helped.lower() for t in ("Object", "Object and effects", "Whole shot")),
            f"the Help's Tools tab explains the menu with its tooltips' words: {helped[:90]!r}")
    U.check(not errors, f"no page errors: {errors}")
    page.close()
