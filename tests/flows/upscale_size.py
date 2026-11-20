"""Finish > Upscale's size: with the row on, it lists the plate's sizes, the largest chosen and Custom… last; a size
chosen goes to the log; Custom… takes one number, the long side, and refuses anything else; the question gives the size
asked for. desk.mp4 is 1280 x 704."""


def chosen(page):
    return page.evaluate("() => { const s = document.querySelector('#finish-upscale-size'); return s.hidden ? null : s.options[s.selectedIndex].textContent; }")


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    page.click("#finish-btn")
    U.check(page.is_hidden("#finish-upscale-size"), "the size list waits for the row to turn on")
    page.click("#finish-upscale")
    options = page.eval_on_selector_all("#finish-upscale-size option", "os => os.map((o) => o.textContent)")
    U.check(options == ["1280 x 704 (the plate's size)", "2560 x 1408", "3840 x 2112", "Custom…"] and chosen(page) == "3840 x 2112",
            f"the row lists the plate's sizes, the largest chosen, Custom… last: {options}")
    start = len(U.log_lines(page))
    page.select_option("#finish-upscale-size", "1")
    U.check("Finish: Upscale at 2560 x 1408." in U.log_lines(page)[start:] and chosen(page) == "2560 x 1408",
            f"a size of the list is chosen, and the log says so: {U.log_lines(page)[start:]}")
    page.select_option("#finish-upscale-size", "custom")
    U.check(page.is_visible("#ask-field") and (page.text_content("#ask-text") or "").startswith("The long side in px, such as 3000."),
            "Custom… asks for the long side")
    page.fill("#ask-field", "3000 px"); page.keyboard.press("Enter")
    refused = 'Upscale size not changed: "3000 px" is not a long side from 640 to 3840 px.'
    U.poll(page, lambda: refused in (page.text_content("#status") or ""))  # the answer reaches the page one task after the dialog closes
    status = page.text_content("#status") or ""
    U.check(refused in status and chosen(page) == "2560 x 1408", f"Custom… refuses anything but a number and keeps the size: {status!r}")
    page.select_option("#finish-upscale-size", "custom")
    page.fill("#ask-field", "3000"); page.keyboard.press("Enter")
    U.poll(page, lambda: chosen(page) == "Custom: 3000 x 1650")
    U.check(chosen(page) == "Custom: 3000 x 1650", f"Custom… takes the long side, the other side from the plate: {chosen(page)}")
    page.click("#finish-upscale")
    page.click("#finish-upscale")
    U.check(chosen(page) == "Custom: 3000 x 1650", "and the row keeps it")
    page.close()
