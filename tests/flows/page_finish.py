"""The page workstream's check of the Finish menu (tests/flows/README.md): the passes on the whole plate after the
full-size composite. On desk.mp4, whose format holds nothing above 1.0, SDR to HDR is a switch that asks first, under its
row. Turned on, the button counts it and the log says so. Esc or a click outside closes the menu. History holds no such
switch."""


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    shown = lambda: page.is_visible("#finish")  # noqa: E731
    U.check(page.query_selector("#deliver-hdr-row") is None and page.text_content("#finish-btn") == "Finish" and not shown(),
            "History holds no SDR to HDR switch; the Finish button is closed, with nothing on")
    page.click("#finish-btn")
    U.check(shown() and page.text_content("#finish .finish-row .name") == "SDR to HDR" and page.is_enabled("#finish-hdr") and not page.is_checked("#finish-hdr"),
            "the button opens the menu: SDR to HDR, off")
    page.click("#finish-hdr")
    U.check(page.is_visible("#finish-hdr-ask") and not page.is_checked("#finish-hdr"), "turning it on asks first, under its row")
    start = len(U.log_lines(page))
    page.click("#finish-hdr-yes")
    U.check(page.is_checked("#finish-hdr") and page.text_content("#finish-btn") == "Finish · 1" and any(t.startswith("Finish: SDR to HDR on.") for t in U.log_lines(page)[start:]),
            f"« Turn on » turns it on: the button counts it and the log says so: {page.text_content('#finish-btn')!r}")
    page.keyboard.press("Escape")
    U.check(not shown(), "Esc closes the menu")
    page.click("#finish-btn")
    page.click("#finish-hdr")
    U.check(not page.is_checked("#finish-hdr") and page.text_content("#finish-btn") == "Finish" and page.is_hidden("#finish-hdr-ask"), "turning it off asks nothing")
    page.click("#status")
    U.check(not shown(), "a click outside closes the menu")
    page.close()
