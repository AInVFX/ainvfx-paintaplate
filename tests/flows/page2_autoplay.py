"""A step's result plays by itself as it is made, and a player that plays goes on with the newest step. A pause by hand
(Space) holds that render's later steps still, and their line says how to play them. Esc, with nothing selected, lifts
that hold, and the latest result plays. The mock holds each fluid step open, so each check meets its window."""


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors, autoplay=True)  # the flow of autoplay itself
    playing = lambda: page.evaluate("document.querySelector('#play-btn').classList.contains('playing')")
    status = lambda: page.text_content("#status")

    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    U.paint_once(page, "thick white smoke", [(0.3, 0.7), (0.4, 0.6), (0.5, 0.7)])
    U.mock_route(port, "/mock/hold", {"output": "plate", "seconds": 6, "times": 2})  # the preview, then the full size
    page.keyboard.press("Enter")

    # 1. The preview is made: it plays by itself, and its line says so
    preview = "Fluid shot, preview: playing. The full-size fluid shot follows."
    U.check(U.poll(page, lambda: status() == preview, 60) and playing(), f"the preview plays as soon as it is made: « {status()} », playing {playing()}")

    # 2. Space while the full size runs: a pause by hand. The full size waits, paused, and its line says how to play it
    page.keyboard.press("Space")
    U.check(U.poll(page, lambda: not playing(), 5), "Space pauses the player")
    full = "Fluid shot, full size: ready. Press Space to play it. Use Paint, Clean or Light to edit it further."
    U.check(U.poll(page, lambda: status() == full, 60) and not playing(), f"after a pause by hand, the full size waits, paused: « {status()} », playing {playing()}")

    # 3. Esc, with nothing selected: the hold is lifted, and the latest result plays
    page.keyboard.press("Escape")
    U.check(U.poll(page, playing, 5), "Esc with nothing selected: the latest result plays")
    U.no_errors(errors, "after the steps played")
    page.close()
