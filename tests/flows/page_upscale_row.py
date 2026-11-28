"""Finish > Upscale: its switch turns it on with no question, the note under the size list gives the time on this GPU, and
Custom… opens its dialog each time it is picked, on the custom size in use."""


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    page.click("#finish-btn")
    page.click("#finish-upscale")
    U.check(page.is_checked("#finish-upscale") and page.is_hidden("#finish-upscale-ask"), "its switch turns it on, with no question")
    note = page.text_content("#finish-upscale-time") or ""
    U.check(page.is_visible("#finish-upscale-time") and note.startswith("About ") and note.endswith(" min on this GPU."), f"the note under the size list gives the time: {note!r}")
    chosen = lambda: page.evaluate("() => { const s = document.querySelector('#finish-upscale-size'); return s.options[s.selectedIndex].textContent; }")
    page.select_option("#finish-upscale-size", "custom")
    page.fill("#ask-field", "3000"); page.keyboard.press("Enter")
    U.poll(page, lambda: chosen() == "Custom: 3000 x 1650")
    options = page.eval_on_selector_all("#finish-upscale-size option", "os => os.map((o) => o.textContent)")
    U.check(chosen() == "Custom: 3000 x 1650" and options[-1] == "Custom…", f"a custom size shows as in use, with Custom… still last: {options}")
    page.select_option("#finish-upscale-size", "custom")
    U.check(page.is_visible("#ask-field") and page.input_value("#ask-field") == "3000", f"Custom… picked again opens its dialog on the size in use: {page.input_value('#ask-field')!r}")
    page.click("#ask-no")
    U.poll(page, lambda: chosen() == "Custom: 3000 x 1650")
    U.check(chosen() == "Custom: 3000 x 1650", f"Keep the current size keeps it: {chosen()}")
    U.no_errors(errors, "in the Finish menu")
    page.close()
