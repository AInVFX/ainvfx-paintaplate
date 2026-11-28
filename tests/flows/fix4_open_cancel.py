"""An opening cancelled with Esc while a plate is open brings that plate back, displayed as it was, with no invitation over it:
only Close plate, or a reload of the page, empties the page (app.cancelOpen, app.comeBack). The mock holds the new plate's
upload, so Esc meets the opening under way."""
import fix4_drops


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    spec = page.text_content("#spec")
    U.mock_route(port, "/mock/slow", {"seconds": 20, "times": 1})
    fix4_drops.drop(page, files=[{"name": "take.mp4", "text": "a movie"}])
    U.check(U.until(page, "!document.querySelector('#opening').hidden", 10000), "the new plate's opening is under way")
    page.keyboard.press("Escape")
    U.poll(page, lambda: page.is_hidden("#opening"), 5)
    status = page.text_content("#status") or ""
    U.check(fix4_drops.displayed(page, spec) and status == "Opening cancelled.",
            f"Esc: the plate open before shows again, with no invitation over it: {page.text_content('#spec')!r}, {status!r}")
    page.close()
