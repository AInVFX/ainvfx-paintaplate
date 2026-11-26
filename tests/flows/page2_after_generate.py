"""After Generate no edit stays selected: the text prompt field empties and its chip hides, for a Paint edit and for a
fluid shot, so the next strokes start a new edit. Enter with nothing painted and no edit selected says what to do."""


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    page.click('.tools [data-tool="paint"]')
    U.paint_once(page, "a red ball", [(0.4, 0.5), (0.45, 0.52)])
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    U.check(page.input_value("#prompt") == "" and page.is_hidden("#editing") and "selected" not in (page.get_attribute("#history li", "class") or ""),
            f"after Generate the field is empty, its chip hidden, no row selected: « {page.input_value('#prompt')} »")
    U.stroke(page, [(0.6, 0.3), (0.65, 0.32)])
    page.fill("#prompt", "a blue cube"); page.evaluate("document.activeElement.blur()")
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=2), timeout=120000)
    U.check(U.row_titles(page)[:2] == ["2. Paint", "1. Paint"], f"the next strokes start a new edit: {U.row_titles(page)}")
    U.settled(page)
    page.fill("#prompt", "a green tree")
    page.press("#prompt", "Enter")
    U.check(U.poll(page, lambda: "Paint on the first frame, then press Enter." in page.text_content("#hud"), 3),
            f"Enter with words and nothing painted says what to do: « {page.text_content('#hud')} »")
    page.close()

    page = U.load(browser, port, errors=errors)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    U.paint_once(page, "thick white smoke", [(0.3, 0.7), (0.4, 0.6), (0.5, 0.7)])
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1) + " && document.querySelector('#fluid').hidden", timeout=120000)
    U.check(page.input_value("#prompt") == "" and page.is_hidden("#editing"), f"after the fluid shot's Generate the field is empty: « {page.input_value('#prompt')} »")
    U.no_errors(errors, "after Generate")
    page.close()
