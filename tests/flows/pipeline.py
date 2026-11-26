"""The page checks (tests/flows/README.md): renders, passes, bit depth, scenes."""
import time
import zip_rows  # noqa: E402


def settled(page, limit=240):  # Generate reads Generate for three seconds running: no edit, no render step left
    calm, t0 = 0, time.time()
    while calm < 3 and time.time() - t0 < limit:
        page.wait_for_timeout(1000)
        calm = calm + 1 if page.text_content("#generate").strip() == "Generate" else 0


def fluid16_scene(page, U):
    """A 16-bit fluid shot with a paint edit on it, saved as a scene and opened again: Finish > SDR to HDR comes back on,
    and every job comes back from the job index, SDR to HDR included, with none posted twice."""
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "17")
    page.select_option("#b-depth", "16"); page.dispatch_event("#b-frames", "input")
    page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    page.evaluate(U.WATCH)
    U.paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)])
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line(("Plate, HDR: done in", "Plate, HDR took")), 240000, "the fluid shot through SDR to HDR")
    page.keyboard.press("p")
    U.paint_once(page, "a lantern", [(0.3, 0.5), (0.34, 0.56)])
    page.keyboard.press("Enter")
    rows = """(() => { const t = [...document.querySelectorAll('#history li .title')].map((e) => e.textContent);
      return t.join() === '2. Paint,1. Fluid' && !document.querySelector('#history li.busy'); })()"""
    page.wait_for_function(rows, timeout=240000)
    U.wait_log(page, U.added_line(U.REVIEWED), 300000, "the full-size composite of the edit on the fluid shot")
    settled(page)
    name, scene = U.save_scene(page)
    U.check(scene["deliver"]["hdr"] and scene["edits"][0]["tool"] == "fluid" and scene["plate"]["color_space"] != "ACES2065-1",
            f"the scene saves Finish > SDR to HDR on, the fluid shot as History's first row, the blank plate in the model space: {scene['plate']['color_space']}")
    page.evaluate(U.WATCH)
    U.open_scene(page, name)
    page.wait_for_function("window.__lines.some((t) => t.startsWith('Scene opened'))", timeout=240000)
    page.wait_for_function(rows, timeout=240000)
    U.wait_log(page, "window.__lines.some((t) => t.startsWith('review: made before') || t.startsWith('review: taken from the job index') || t.startsWith('review '))", 300000, "the review")
    settled(page)
    grew = U.added(page, ("ingest", "fluid", "hdr", "edit", "shot", "matte", "comp", "review"))
    posted = {k: v for k, v in grew.items() if k.endswith("posted") and v}
    U.check(not posted and all(grew[f"{s}: made before"] >= 1 for s in ("ingest", "fluid", "hdr", "edit", "shot", "review")),
            f"a 16-bit fluid scene opens again from the job index: the fluid shot, its SDR to HDR, the edit and every render step, nothing posted: {grew}")
    U.check(not errors, f"no console errors in the 16-bit fluid scene: {errors}")


PICTURE = """() => { const c = document.querySelector('#view'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
  let spread = 0, white = 0, lit = 0;  // spread: the largest gap between a pixel's channels; a grey picture keeps it small
  for (let i = 0; i < d.length; i += 4) { const hi = Math.max(d[i], d[i + 1], d[i + 2]), lo = Math.min(d[i], d[i + 1], d[i + 2]);
    spread = Math.max(spread, hi - lo); if (lo > 200) white++; if (hi > 40) lit++; }
  return { spread, white, lit }; }"""


def rows(page):
    return page.eval_on_selector_all("#stages li.pick .name", "els => els.map(e => e.textContent)")


def shown(page):
    return page.eval_on_selector_all("#stages li.shown .name", "els => els.map(e => e.textContent)")


def frames_seen(page, keys=("Home", "ArrowRight", "End")):  # the picture on the first frame, the next one and the last
    seen = []
    for k in keys:
        page.keyboard.press(k); page.wait_for_timeout(700); seen.append(page.evaluate(PICTURE))
    return seen


def pass_rows(page, U):
    """The Render panel's rows for mattes and fluid shots. On a video plate with a paint and an erase: the erase matte, the
    paint matte at the preview and at full size, each a grey movie its row shows on
    every frame. Export adds no row. A fluid shot: its keyframes (the control video), its shot and its SDR to HDR, with the keyframes closed
    and open. A second click, or Esc, gives the latest result back."""
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    U.open_path(page, "plates/desk.mp4")  # waits for desk's own spec: the plate before also says fps
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden", timeout=60000)
    page.evaluate(U.WATCH)
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line(U.REVIEWED), 240000, "the full-size composite of the paint")
    page.keyboard.press("c"); U.paint_once(page, "the cup", [(0.6, 0.4), (0.62, 0.45)]); page.wait_for_timeout(1500); page.keyboard.press("Enter")
    U.wait_log(page, f"window.__lines.filter((t) => {U.HAS_REVIEWED}).length >= 2", 240000, "the full-size composite of both edits")
    settled(page)
    page.keyboard.press("n")  # New edit: nothing selected, so frame 0 shows the pass, not the strokes
    mattes = ["Track the object to clean", "Track the paint, preview", "Track the paint, full size"]
    U.check(set(mattes) <= set(rows(page)), f"each matte is a row to click: {rows(page)}")
    for label in mattes:
        page.click(f"#stages li.pick:has-text('{label}')"); page.wait_for_timeout(800)
        seen = frames_seen(page)
        U.check(shown(page) == [label] and all(x["spread"] <= 12 and x["white"] > 0 for x in seen),
                f"{label}: its matte shows, grey, on the first frame, the next and the last: {shown(page)}, {seen}")
        page.click(f"#stages li.pick:has-text('{label}')"); page.wait_for_timeout(500)
        U.check(shown(page) == ["Composite, full size"], f"{label}: a second click gives the latest back: {shown(page)}")
    page.click("#stages li.pick:has-text('Track the object to clean')"); page.wait_for_timeout(500)
    page.keyboard.press("Escape"); page.wait_for_timeout(500)
    U.check(shown(page) == ["Composite, full size"], f"Esc gives the latest back from a matte: {shown(page)}")
    page.click("#export-btn")
    with page.expect_download(timeout=240000):
        page.click("#x-go")
    page.wait_for_function("document.querySelector('#render-left').textContent === 'exported'", timeout=60000)
    names = page.eval_on_selector_all("#stages li .name", "els => els.map(e => e.textContent)")
    U.check("Export" not in names, f"Export adds no row to the Render panel: {names}")
    page.keyboard.press("?"); page.click("#help [role=tab][data-help=models]")  # Help > Models and licences
    page.wait_for_function("!!document.querySelector('#models').dataset.shown", timeout=20000)
    named = page.evaluate("document.querySelector('#models').dataset.shown").split(",")
    U.check({"klein", "ltx", "sam", "ripple"} <= set(named) and "hdr" not in named and "fluid" not in named,
            f"Models and licences names the models the render ran (r.flows): Klein, LTX, SAM, its paint IC-LoRA; no SDR to HDR, no fluid: {named}")
    page.keyboard.press("Escape"); page.keyboard.press("Escape"); page.wait_for_timeout(300)

    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "17")
    page.select_option("#b-depth", "16"); page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    page.evaluate(U.WATCH)
    U.paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line(("Plate, HDR: done in", "Plate, HDR took")), 240000, "the fluid shot through SDR to HDR")
    steps = ["Fluid shot, full size", "Plate, HDR"]
    U.check(rows(page)[-2:] == steps, f"the fluid shot's render lists its steps as every render does: {rows(page)}")
    for label in steps:  # each finished step shows its pass, and a second click gives the latest result back
        page.click(f"#stages li.pick:has-text('{label}')"); page.wait_for_timeout(800)
        U.check(shown(page) == [label], f"{label}: a click shows its pass: {shown(page)}")
        page.click(f"#stages li.pick:has-text('{label}')"); page.wait_for_timeout(500)
        U.check(shown(page) == [steps[-1]], f"{label}: a second click gives the latest result back, SDR to HDR's: {shown(page)}")
    U.check(not errors, f"no console errors in the pass rows: {errors}")


def hdr_video(page, U):
    """SDR to HDR on a video plate, from Deliver's bit-depth pass: off by default; turning it on asks first; once on, the result is an EXR
    sequence that the player reads at full precision, and Export writes that sequence instead of a video file."""
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    U.open_path(page, "plates/desk.mp4")  # waits for desk's own spec: the plate before also says fps
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden", timeout=60000)
    page.click("#finish-btn")
    U.check(page.is_enabled("#finish-hdr") and not page.is_checked("#finish-hdr") and not page.query_selector("#hdr-switch"),
            "a video plate: the Finish menu offers SDR to HDR, off; no switch near the render steps")
    page.click("#finish-hdr")
    U.check(not page.is_hidden("#finish-hdr-ask") and not page.is_checked("#finish-hdr"), "turning it on asks first, and stays off until confirmed")
    page.click("#finish-hdr-no")
    U.check(page.is_hidden("#finish-hdr-ask") and not page.is_checked("#finish-hdr"), "Cancel leaves it off")
    page.click("#finish-hdr"); page.click("#finish-hdr-yes")
    U.check(page.is_hidden("#finish-hdr-ask") and page.is_checked("#finish-hdr"), "« Yes, turn it on » turns it on")
    page.keyboard.press("Escape")  # the Finish menu closes
    page.evaluate("document.activeElement.blur()")
    page.evaluate(U.WATCH)
    page.keyboard.press("p"); U.paint_once(page, "a red lamp", [(0.3, 0.6), (0.36, 0.7)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, HDR: done in"), 240000, "the full-size composite, then SDR to HDR on its elements")
    lines = page.evaluate("window.__lines")
    U.check(all(any(f"{name}: done in" in t or f"{name} took" in t for t in lines) for name in ("Plate, HDR", "Layer, HDR", "Composite, HDR")),
            "the plate and the layer went through SDR to HDR, then « Composite, HDR » made the composite again")
    settled(page)
    page.keyboard.press("n")
    page.wait_for_function("document.querySelector('canvas[data-precision]').dataset.precision === 'float'", timeout=60000)
    U.check(True, "paused, the player shows the result's EXR frames at full precision")
    page.click("#export-btn")
    ticks = [k for k in ("composite", "full", "hdr") if page.is_checked(f"#x-{k}")]  # the dialog opens on the result at its last stage
    with page.expect_download(timeout=240000) as dl:
        page.click("#x-go")
    import zipfile
    names = zipfile.ZipFile(dl.value.path()).namelist()
    U.check(ticks[:1] == ["composite"] and zip_rows.composite(names, (".exr",)) and not any(n.endswith((".mp4", ".webm")) and n.startswith("composite_full_size/") for n in names),
            f"Export writes the EXR sequence, not a video file: {ticks}, {zip_rows.composite(names)[:3]}")
    listed = "".join(zipfile.ZipFile(dl.value.path()).read(n).decode() for n in zip_rows.files(names, "models"))
    U.check("FLUX 3 Image Klein" in listed and listed.count("\n| ") >= 4,
            f"the zip lists the models behind the result, with their licences (its models' list): {listed.splitlines()[6:9]}")
    U.check(not errors, f"no console errors with SDR to HDR on a video plate: {errors}")


def movie_name(page, U):
    """A movie keeps its trailing digits in its name: desk_v2.mp4 is « desk_v2 », not « desk_v » (read as a frame
    number, train_v2.mp4 would show as « train_v »). Trailing digits are a frame number only in an image sequence."""
    base = page.url.split("/extensions/")[0]
    movie = page.request.get(f"{base}/view?filename=desk.mp4&subfolder=plates&type=input").body()
    page.request.post(f"{base}/upload/image", multipart={"image": {"name": "desk_v2.mp4", "mimeType": "video/mp4", "buffer": movie},
                                                         "subfolder": "plates", "overwrite": "true"})
    U.open_path(page, "plates/desk_v2.mp4")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('desk_v') && document.querySelector('#opening').hidden", timeout=60000)
    spec = page.text_content("#spec")
    U.check(spec.startswith("desk_v2: "), f"a movie keeps its trailing digits in its name: {spec}")


def run(browser, port, U):
    page = browser.new_page(viewport={"width": 1400, "height": 900}, accept_downloads=True)
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    movie_name(page, U)
    fluid16_scene(page, U)
    pass_rows(page, U)
    hdr_video(page, U)
    page.close()
