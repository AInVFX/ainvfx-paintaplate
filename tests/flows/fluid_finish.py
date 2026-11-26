"""The Finish menu on a 16-bit blank plate, as a person uses it: open with the keyframes displayed, SDR to HDR turns off before
Generate and on afterwards. The fluid shot alone has no « First frame » row; the render made when the switch turns on takes
the fluid shot's preview and full size from the first render, and lists both. A displayed step that the displayed render no
longer has gives way to the latest result. A Paint over the fluid shot has its first frame, and with SDR to HDR on, its
composite goes through SDR to HDR whole, after « Composite, full size »."""
import re
import zipfile

ROWS = "[...document.querySelectorAll('#stages li .name')].map((e) => e.textContent)"
DONE = "window.__lines.some((t) => /{}/.test(t))"


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "16"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    U.check(page.is_enabled("#finish-btn") and page.evaluate("document.querySelector('#finish-hdr').checked"),
            "with the keyframes open, the Finish menu works, SDR to HDR on from 16-bit")
    page.click("#finish-btn"); page.click("#finish-hdr"); page.keyboard.press("Escape")
    U.check(not page.evaluate("document.querySelector('#finish-hdr').checked"), "SDR to HDR turns off before any Generate")
    U.paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)])
    page.keyboard.press("End"); U.stroke(page, [(0.45, 0.3), (0.55, 0.2)])
    page.evaluate(U.WATCH); page.keyboard.press("Enter")
    page.wait_for_function(DONE.format(r" Fluid shot, full size: done in "), timeout=120000)
    rows = page.evaluate(ROWS)
    U.check("Edited first frame" not in rows and rows[:2] == ["Fluid shot, preview", "Fluid shot, full size"] and "SDR to HDR" not in rows,
            f"the fluid shot alone: no first frame of an edit, its two steps, no SDR to HDR: {rows}")
    page.evaluate(U.WATCH)
    page.click("#finish-btn"); page.click("#finish-hdr")
    page.wait_for_function("!document.querySelector('#finish-hdr-ask').hidden", timeout=10000); page.click("#finish-hdr-yes"); page.keyboard.press("Escape")
    page.wait_for_function(DONE.format(r" SDR to HDR: done in "), timeout=120000)
    new, rows = page.evaluate("window.__lines"), page.evaluate(ROWS)
    U.check(rows[:3] == ["Fluid shot, preview", "Fluid shot, full size", "SDR to HDR"] and not any(re.match(r"Render v[2-9]", t) for t in new),
            f"SDR to HDR on afterwards: the same render runs it, as its last step, after its fluid steps: {rows}")
    page.click("#stages li.pick:has-text('SDR to HDR')")
    U.check(U.until(page, "document.querySelector('#stages li.shown')?.textContent.includes('SDR to HDR') === true", 5000), "SDR to HDR's step displayed")
    page.click("#finish-btn"); page.click("#finish-hdr"); page.keyboard.press("Escape")
    U.check(U.until(page, "!document.querySelector('#stages li.shown')?.textContent.includes('SDR to HDR')", 5000),
            f"SDR to HDR off: its step gives way to the latest result: {page.evaluate(ROWS)}")
    page.click("#finish-btn"); page.click("#finish-hdr")
    page.wait_for_function("!document.querySelector('#finish-hdr-ask').hidden", timeout=10000); page.click("#finish-hdr-yes"); page.keyboard.press("Escape")
    page.click(".tools [data-tool=paint]")
    page.fill("#prompt", "a fire"); U.stroke(page, [(0.3, 0.5), (0.35, 0.45)])
    page.evaluate(U.WATCH); page.keyboard.press("Enter")
    page.wait_for_function(DONE.format(r" SDR to HDR: done in "), timeout=180000)
    new, rows = page.evaluate("window.__lines"), page.evaluate(ROWS)
    comp = next((i for i, t in enumerate(new) if re.search(r" Composite, full size: done in ", t)), None)
    hdr = next((i for i, t in enumerate(new) if re.search(r" SDR to HDR: done in ", t)), None)
    U.check("Edited first frame" in rows and rows.index("Edited first frame") == rows.index("Fluid shot, full size") + 1 and comp is not None and hdr is not None and comp < hdr and rows.index("Composite, full size") < rows.index("SDR to HDR"),
            f"a Paint over the fluid shot: its first frame after the fluid shot's steps, then SDR to HDR on its composite, whole: {rows}")
    page.click("#export-btn")
    boxes = {k: page.is_visible(f"#x-{k}") for k in ("matte", "review", "shot")}
    U.check(all(boxes.values()) and "relit" not in (page.text_content("#x-note") or ""),
            f"over a fluid shot, Export offers the edits' composite, matte and shot, as for any edit: {boxes}")
    first = page.evaluate("document.querySelector('#x-export').closest('label').querySelector('span').textContent")
    U.check(first == "HDR", f"its first row names what the files hold, SDR to HDR's frames: {first!r}")
    page.check("#x-matte")
    with page.expect_download(timeout=120000) as dl:
        page.click("#x-go")
    names = zipfile.ZipFile(dl.value.path()).namelist()
    U.check(any(n.startswith("hdr/") and n.endswith(".exr") for n in names) and any(n.startswith("matte/") for n in names),
            f"its zip: the result as SDR to HDR's EXR frames, and the matte: {sorted({n.split('/')[0] for n in names})}")
    U.no_errors(errors, "with the Finish menu on a blank plate")
    page.close()
