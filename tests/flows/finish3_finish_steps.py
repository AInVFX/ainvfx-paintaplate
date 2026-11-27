"""Each Finish step plays as it is made and the HUD names it, one rule for every step. A paint with SDR to HDR and Upscale at
1600 x 880 on: « Plate, HDR », « Layer, HDR », « Composite, HDR », « Plate, HDR, upscaled », « Layer, HDR, upscaled » and
« Composite, HDR, upscaled » each say « …: playing. » (or « …: ready. Press Space to play it. »), and the last one's status
line says to use Export. Upscale turned off, then on over the result it made: that result plays again, named. The plate
alone's SDR to HDR step is « Plate, HDR » (labelOf), in the HUD and the status line."""
RESTS = "['full size ready', 'finish ready'].includes(document.querySelector('#render-left').textContent) || document.querySelector('#status').textContent.startsWith('Error')"
SEEN = """window.__seen = []; for (const id of ['#status', '#hud']) new MutationObserver(() => window.__seen.push(document.querySelector(id).textContent))
  .observe(document.querySelector(id), { childList: true, subtree: true, characterData: true });"""  # the status line and the HUD, each text they show
STEPS = ["Plate, HDR", "Layer, HDR", "Composite, HDR", "Plate, HDR, upscaled", "Layer, HDR, upscaled", "Composite, HDR, upscaled"]
named = lambda texts, step: f"{step}: playing." in texts or f"{step}: ready. Press Space to play it." in texts  # noqa: E731


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH); page.evaluate(SEEN)
    page.click("#finish-btn"); page.click("#finish-hdr"); page.click("#finish-hdr-yes"); page.keyboard.press("Escape")
    page.keyboard.press("Enter")  # the plate alone: SDR to HDR on the plate
    U.wait_log(page, U.added_line("Plate, HDR: done in"), 240000, "SDR to HDR on the plate alone")
    page.wait_for_function(RESTS, timeout=60000); page.wait_for_timeout(1000)
    texts, status = page.evaluate("window.__seen"), page.text_content("#status") or ""
    U.check(named(texts, "Plate, HDR") and not any(t.startswith("SDR to HDR: ") for t in texts)
            and status == "Plate, HDR: ready, in the viewer with its EXR frames at full precision. Use Export to write them out for compositing.",
            f"the plate alone's step is « Plate, HDR », in the HUD and the status line: {status!r}")
    page.evaluate("window.__seen = []")
    page.click("#finish-btn"); page.click("#finish-upscale")
    U.upscale_custom(page, "1600")
    page.keyboard.press("Escape")
    page.wait_for_function(RESTS, timeout=240000)  # the plate alone's Upscale step runs at once: the paint comes after it
    page.evaluate("window.__seen = []")
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, HDR, upscaled: done in"), 300000, "both passes on the paint")
    page.wait_for_function(RESTS, timeout=60000); page.wait_for_timeout(1000)
    texts = page.evaluate("window.__seen")
    U.check(all(named(texts, s) for s in STEPS), f"each Finish step plays as it is made, the HUD naming it: missing {[s for s in STEPS if not named(texts, s)]}")
    status = page.text_content("#status") or ""
    U.check(status == "Composite, HDR, upscaled: ready, in the viewer. Use Export to write it out for compositing.", f"the last step's status line: {status!r}")
    page.click("#finish-btn"); page.click("#finish-upscale"); page.keyboard.press("Escape")
    page.wait_for_function(RESTS, timeout=30000); page.wait_for_timeout(1000)
    page.evaluate("window.__seen = []")
    page.click("#finish-btn"); page.click("#finish-upscale"); page.keyboard.press("Escape")
    page.wait_for_function(RESTS, timeout=30000); page.wait_for_timeout(1500)
    texts = page.evaluate("window.__seen")
    U.check(named(texts, "Composite, HDR, upscaled") and not any(named(texts, s) for s in STEPS[:5]),
            f"Upscale on again over the result it made: that result plays, named, and no earlier step flashes by: {texts[-8:]}")
    page.close()
