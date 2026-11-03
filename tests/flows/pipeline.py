"""The pipeline workstream's page checks (tests/flows/README.md): renders, passes, bit depth, scenes."""
import time


def settled(page, limit=240):  # Generate reads Generate for three seconds running: no edit, no render step left
    calm, t0 = 0, time.time()
    while calm < 3 and time.time() - t0 < limit:
        page.wait_for_timeout(1000)
        calm = calm + 1 if page.text_content("#generate").strip() == "Generate" else 0


def fluid16_scene(page, U):
    """A 16-bit fluid shot with a paint edit on it, saved as a scene and opened again: every job comes back from the job
    index, the fluid shot's SDR to HDR included, and none is posted twice. Before the fix, SDR to HDR ran again on reopen
    and rewrote the EXR frames under the edits: the plate's time changed, so every job on it missed the index (2 Nov)."""
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
    U.wait_log(page, U.added_line("under the edits: the fluid shot v"), 240000, "the HDR fluid shot under the edits")
    page.keyboard.press("b")
    U.paint_once(page, "a lantern", [(0.3, 0.5), (0.34, 0.56)])
    page.keyboard.press("Enter")
    rows = """(() => { const t = [...document.querySelectorAll('#history li .title')].map((e) => e.textContent);
      return t.join() === '2. Paint,1. Fluid' && !document.querySelector('#history li.busy'); })()"""
    page.wait_for_function(rows, timeout=240000)
    U.wait_log(page, U.added_line(U.REVIEWED), 300000, "the full-size composite of the edit on the HDR fluid shot")
    settled(page)
    name, scene = U.save_scene(page)
    U.check(scene["fluid"]["depth"] == 16 and scene["plate"]["color_space"] != "ACES2065-1",
            f"the scene saves the blank plate in its own colour space, not the HDR frames' ACES2065-1: {scene['plate']['color_space']}")
    page.evaluate(U.WATCH)
    U.open_scene(page, name)
    page.wait_for_function("window.__lines.some((t) => t.startsWith('Scene opened'))", timeout=240000)
    page.wait_for_function(rows, timeout=240000)
    U.wait_log(page, "window.__lines.some((t) => t.startsWith('review: made before') || t.startsWith('review: posted'))", 300000, "the review")
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
    paint matte at the preview and at full size, then after Export the export's matte, each a grey movie its row shows on
    every frame. A fluid shot: its keyframes (the control video), its shot and its SDR to HDR, with the keyframes closed
    and open. A second click, or Esc, gives the latest result back."""
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('fps') && document.querySelector('#opening').hidden", timeout=60000)
    page.evaluate(U.WATCH)
    page.keyboard.press("b"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line(U.REVIEWED), 240000, "the full-size composite of the paint")
    page.keyboard.press("e"); U.paint_once(page, "the cup", [(0.6, 0.4), (0.62, 0.45)]); page.wait_for_timeout(1500); page.keyboard.press("Enter")
    U.wait_log(page, f"window.__lines.filter((t) => t.includes('{U.REVIEWED}')).length >= 2", 240000, "the full-size composite of both edits")
    settled(page)
    page.keyboard.press("n")  # New edit: nothing selected, so frame 0 shows the pass, not the strokes
    mattes = ["Track the erase", "Track the paint, preview", "Track the paint, full size"]
    U.check(set(mattes) <= set(rows(page)), f"each matte is a row to click: {rows(page)}")
    for label in mattes:
        page.click(f"#stages li.pick:has-text('{label}')"); page.wait_for_timeout(800)
        seen = frames_seen(page)
        U.check(shown(page) == [label] and all(x["spread"] <= 12 and x["white"] > 0 for x in seen),
                f"{label}: its matte shows, grey, on the first frame, the next and the last: {shown(page)}, {seen}")
        page.click(f"#stages li.pick:has-text('{label}')"); page.wait_for_timeout(500)
        U.check(shown(page) == ["Composite, full size"], f"{label}: a second click gives the latest back: {shown(page)}")
    page.click("#stages li.pick:has-text('Track the erase')"); page.wait_for_timeout(500)
    page.keyboard.press("Escape"); page.wait_for_timeout(500)
    U.check(shown(page) == ["Composite, full size"], f"Esc gives the latest back from a matte: {shown(page)}")
    page.click("#export-btn")
    with page.expect_download(timeout=240000):
        page.click("#x-go")
    page.wait_for_function("[...document.querySelectorAll('#stages li.pick .name')].some((e) => e.textContent === 'Export')", timeout=60000)
    page.click("#stages li.pick:has-text('Export')"); page.wait_for_timeout(800)
    seen = frames_seen(page)
    U.check(shown(page) == ["Export"] and all(x["spread"] <= 12 and x["white"] > 0 for x in seen),
            f"after Export, its row shows the export's matte, grey, on every frame: {shown(page)}, {seen}")
    page.keyboard.press("Escape"); page.wait_for_timeout(500)

    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "17")
    page.select_option("#b-depth", "16"); page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    page.evaluate(U.WATCH)
    U.paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("under the edits: the fluid shot v"), 240000, "the HDR fluid shot under the edits")
    fluid = ["Fluid: keyframes", "Fluid: shot", "Fluid: SDR to HDR"]
    for state in ("closed", "open"):
        if state == "open":
            page.click('#history li[data-id="fluid"] .edit')
            page.wait_for_function("!document.querySelector('#fluid').hidden", timeout=10000)
        U.check(rows(page) == fluid, f"keyframes {state}: the fluid shot's rows: {rows(page)}")
        for label in fluid:
            page.click(f"#stages li.pick:has-text('{label}')"); page.wait_for_timeout(800)
            second = frames_seen(page, ("Home", "ArrowRight"))[1]  # frame 1 holds no keyframe: the control video is black there
            black = second["lit"] == 0
            U.check(shown(page) == [label] and black == (label == "Fluid: keyframes"),
                    f"keyframes {state}, {label}: on show on every frame (frame 1 {'black' if black else 'lit'}): {shown(page)}, {second}")
            page.click(f"#stages li.pick:has-text('{label}')"); page.wait_for_timeout(500)
            U.check(shown(page) == [], f"keyframes {state}, {label}: a second click gives the fluid shot back: {shown(page)}")
        page.click("#stages li.pick:has-text('Fluid: shot')"); page.wait_for_timeout(500)
        page.keyboard.press("Escape"); page.wait_for_timeout(500)
        U.check(shown(page) == [], f"keyframes {state}: Esc gives the fluid shot back: {shown(page)}")
    U.check(not errors, f"no console errors in the pass rows: {errors}")


def run(browser, port, U):
    page = browser.new_page(viewport={"width": 1400, "height": 900}, accept_downloads=True)
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    fluid16_scene(page, U)
    pass_rows(page, U)
    page.close()
