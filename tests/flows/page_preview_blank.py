"""Preview on a blank plate: the menu offers Off, Latent preview, Half and Quarter size from the start, keyframes open, on the
session's choice (Half size here, ui_mock.HalfSize), and its note says what each does. With Half size the fluid shot's render
runs « Fluid shot, preview » first, then the full size; with Off, another seed runs the full size alone. Bypassed, the fluid
shot leaves the menu as it was: the edits on the blank plate take a preview pass as on any plate."""
import re

FLUID = '#history li[data-id="fluid"]'
PREVIEW = re.compile(r"Render v\d+: Fluid shot, preview: done in ")
FULL = re.compile(r"Render v\d+: Fluid shot, full size: done in ")


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    options = lambda: page.eval_on_selector_all("#preview-size option", "els => els.map((e) => e.value)")
    U.check(options() == ["off", "latent", "2", "4"] and page.input_value("#preview-size") == "2" and page.is_visible("#preview-parts"),
            f"a blank plate offers the four choices at once, keyframes open, on the session's Half size, with their note: {options()}")
    U.paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)])
    page.keyboard.press("End")
    U.stroke(page, [(0.45, 0.3), (0.55, 0.2)])
    page.evaluate(U.WATCH)
    page.keyboard.press("Enter")
    page.wait_for_function("window.__lines.some((t) => / Fluid shot, full size: done in /.test(t))", timeout=120000)
    new = page.evaluate("window.__lines")
    pv, full = [i for i, t in enumerate(new) if PREVIEW.match(t)], [i for i, t in enumerate(new) if FULL.match(t)]
    U.check(pv and full and pv[0] < full[0], f"with Half size, the fluid shot's first pass runs at that size, then the full size: {[t[:55] for t in new if 'Fluid shot,' in t]}")
    page.select_option("#preview-size", "off")
    page.evaluate(U.WATCH)
    page.click(f"{FLUID} .again")  # another seed
    page.wait_for_function("window.__lines.some((t) => / Fluid shot, full size: done in /.test(t))", timeout=120000)
    new = page.evaluate("window.__lines")
    U.check(any(FULL.match(t) for t in new) and not any(PREVIEW.match(t) for t in new),
            f"with Off, another seed runs the full size alone: {[t[:55] for t in new if 'Fluid shot,' in t]}")
    page.select_option("#preview-size", "2")
    page.click(f"{FLUID} .eye")  # bypassed: the blank plate under the edits
    U.check(U.until(page, "[...document.querySelectorAll('#log li span')].some((e) => /^Fluid shot v\\d+ is bypassed\\.$/.test(e.textContent))", 60000),
            "the fluid shot's eye bypasses it")
    U.check(len(options()) == 4 and page.input_value("#preview-size") == "2" and page.is_visible("#preview-parts"),
            f"with the fluid shot bypassed, the menu keeps the sizes and the session's choice, which the render uses: {options()}, on {page.input_value('#preview-size')}")
    U.no_errors(errors, "on the blank plate and its fluid shot")
    page.close()
