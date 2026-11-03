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


def run(browser, port, U):
    page = browser.new_page(viewport={"width": 1400, "height": 900}, accept_downloads=True)
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    fluid16_scene(page, U)
    page.close()
