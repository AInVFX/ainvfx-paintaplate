"""A Light edit with SDR to HDR on, on an 8-bit video plate: the relit composite goes through SDR to HDR after it is made, so
the new light comes back in HDR, and the Export dialog and Export both give half-float EXR frames in ACES2065-1."""

READY = "/ready|exported/.test(document.querySelector('#render-left').textContent) && !document.querySelector('#stages li.now')"
LOG = "[...document.querySelectorAll('#log li span')].map((e) => e.textContent)"


def run(browser, port, U):
    page = U.load(browser, port)
    def settle(what):
        page.wait_for_function(U.SETTLED, timeout=180000); page.wait_for_timeout(1500); U.wait_log(page, READY, 180000, what)
    U.open_plate(page)
    page.click('.tools [data-tool="light"]'); U.paint_once(page, "warm sunset light", [(0.70, 0.30), (0.74, 0.34)])
    page.keyboard.press("Enter"); settle("the Light edit's render")
    page.click("#finish-btn"); page.click("#finish-hdr"); page.click("#finish-hdr-yes"); page.keyboard.press("Escape")
    left = page.evaluate("""() => new Promise((done) => { const t0 = Date.now(), tick = () => {
      const now = document.querySelector('#stages li.now');
      if (now && now.textContent.includes('SDR to HDR')) return done(document.querySelector('#render-left').textContent);
      if (Date.now() - t0 > 90000) return done(null);
      setTimeout(tick, 20); }; tick(); })""")  # the Render panel's note at the moment SDR to HDR runs on the composite
    U.check(left is not None and "ready" not in left, f"while SDR to HDR runs on the relit composite, the Render panel does not say the full size is ready: {left!r}")
    settle("SDR to HDR")
    log = page.evaluate(LOG)
    hdr = [i for i, t in enumerate(log) if ": SDR to HDR: done in " in t]
    comp = [i for i, t in enumerate(log) if ": Composite, full size: done in " in t or ": Light transfer, full size: done in " in t]  # Light edits alone: Relight Transfer
    U.check(hdr and comp and hdr[-1] > comp[-1], f"SDR to HDR runs after the full-size composite: {[log[i] for i in comp[-1:] + hdr[-1:]]}")
    U.check(page.evaluate("[...document.querySelectorAll('#stages li.done')].some((li) => li.textContent.includes('SDR to HDR'))"), "the Render panel shows SDR to HDR done")
    page.click("#export-btn")
    fmt, note = page.text_content("#x-format"), page.text_content("#x-note")
    U.check(fmt == "half-float EXR frames, ACES2065-1" and note.startswith("The relit result in HDR"), f"the Export dialog says what Export writes: {fmt!r} | {note!r}")
    U.check(page.is_hidden("#x-matte"), "a relit result in HDR exports its frames alone")
    page.click("#x-go")
    U.wait_log(page, "[...document.querySelectorAll('#log li span')].some((e) => e.textContent.startsWith('Export: done'))", 120000, "the export")
    done = [t for t in page.evaluate(LOG) if t.startswith("Export: done")][-1]
    U.check("half-float EXR frames in ACES2065-1" in done, f"Export writes the relit result in HDR: {done!r}")
    page.close()
