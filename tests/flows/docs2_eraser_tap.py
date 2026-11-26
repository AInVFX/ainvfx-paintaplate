"""A tap on E stays a tap while the page is busy. The page reads the key's own times (the events' timestamps), so a tap of
50 ms switches the eraser on even when a long task holds the page for 0.6 s between the key's down and its up, as frames
being decoded can on a loaded machine."""
OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
BUSY = """() => addEventListener("keydown", (e) => {  // after the page's own handler: the page busy for 0.6 s
  if (e.key === "e") { const t = performance.now(); while (performance.now() - t < 600); } }, { once: true })"""


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    rub = lambda: page.get_attribute("#rub-btn", "aria-pressed") == "true"  # noqa: E731
    page.evaluate(BUSY)
    U.tap(page, "e", 0.05)
    U.check(rub(), "a tap of 50 ms on E switches the eraser on, though the page was busy for 0.6 s between the key's down and up")
    U.tap(page, "e", 0.05)
    U.check(not rub(), "a second tap switches it off")
