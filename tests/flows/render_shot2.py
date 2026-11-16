"""The full-size shot in two stages (tests/flows/README.md): with ?shot=2 in the address, the full-size shot runs at half
the working size first, then 2 steps at full size from it (the workflow shotup), and the render goes on to its composite."""

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, "?blank=0&shot=2", errors=errors)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    page.evaluate(U.WATCH)
    page.click('.tools [data-tool="paint"]')
    U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)])
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Shot, full size: stage 2 of 2, 2 steps at"), 240000, "the shot's second stage")
    U.wait_log(page, U.added_line("Composite, full size: done in"), 240000, "the full-size composite after the two stages")
    lines = page.evaluate("window.__lines")
    U.check(any(t.startswith("shotup ") and ": done in" in t for t in lines), "?shot=2: the second stage is a job of its own, shotup")
    U.no_errors(errors, "with ?shot=2 in the address")
    page.close()
