"""Preview on a blank plate: the menu shows before the first fluid shot, with Off and Latent preview only, and its note
leaves out half and quarter size. Half and Quarter size come back once the fluid shot is the plate, with the session's
choice, Half size here (ui_mock.HalfSize)."""


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    options = lambda: page.eval_on_selector_all("#preview-size option", "els => els.map((e) => e.value)")
    U.check(page.is_visible("#preview-size") and options() == ["off", "latent"] and page.input_value("#preview-size") == "latent",
            f"a blank plate shows the Preview menu at once, with Off and Latent preview only: {options()}, on {page.input_value('#preview-size')}")
    U.check(page.is_hidden("#preview-parts"), "its note leaves out half and quarter size")
    U.paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)])
    page.keyboard.press("End")
    U.stroke(page, [(0.45, 0.3), (0.55, 0.2)])
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1) + " && document.querySelector('#fluid').hidden", timeout=120000)
    U.check(U.until(page, "document.querySelectorAll('#preview-size option').length === 4", 10000) and page.input_value("#preview-size") == "2"
            and page.is_visible("#preview-parts"), f"with the fluid shot as the plate, Half and Quarter size come back, on the session's Half size: {options()}")
    U.no_errors(errors, "on the blank plate and its fluid shot")
    page.close()
