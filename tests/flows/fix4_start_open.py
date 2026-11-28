"""The invitation's click opens the Open dialog, even while the page's start makes its blank plate: the canvas made after the
click opens nothing over the dialog (app.openBlank). The mock's answer for the blank canvas is held until the click."""
READY = "document.querySelector('#status').textContent.startsWith('Ready')"
OPENED = "document.querySelector('#open').open"


def run(browser, port, U):
    page = browser.new_page(viewport=U.VIEWPORT)
    held = []
    page.route("**/paintaplate/blank", lambda route: held.append(route))
    page.goto(U.PAGE.format(port=port, query="?autoplay=0"))  # with a blank plate at start, as the page opens by default
    page.wait_for_function(READY, timeout=60000)
    U.poll(page, lambda: bool(held), 20)
    U.check(bool(held) and page.is_visible("#empty-open"), "the start asks for its blank canvas, and the invitation shows while it is made")
    page.click("#empty-open")
    U.check(page.evaluate(OPENED), "the invitation's click opens the Open dialog")
    held[0].continue_()
    page.wait_for_timeout(3000)
    spec, opened = (page.text_content("#spec") or "").strip(), page.evaluate(OPENED)
    U.check(opened and not spec, f"the canvas, made after the click, opens nothing over the dialog: dialog open {opened}, spec {spec!r}")
    page.close()
