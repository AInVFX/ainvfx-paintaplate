"""An edit's time counts from its own run: edit 2, made again because edit 1 under it changed, says how long that run
took, never the time since edit 2 was first made."""
import re
import time


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    away = lambda: page.mouse.move(5, 5)  # noqa: E731  (hover off the frame)
    page.keyboard.press("p")
    for words, pts in (("a red fire", [(0.15, 0.25), (0.25, 0.25)]), ("a blue vase", [(0.22, 0.25), (0.50, 0.25)])):
        U.paint_once(page, words, pts); page.keyboard.press("n")  # edit 2 starts on edit 1's stroke: it depends on it
    page.wait_for_function(U.DONE.format(n=2), timeout=120000)
    U.settled(page)
    page.wait_for_timeout(6000)  # time that edit 2's next run must not count
    page.click("#history li:nth-child(2) .edit"); away()  # edit 1's pencil
    U.stroke(page, [(0.10, 0.32), (0.14, 0.32)]); away()
    page.evaluate(U.WATCH)
    t0 = time.monotonic()
    page.keyboard.press("Enter")
    U.check(U.until(page, U.added_line("Edit 2: done in"), 120000), "edit 2 is made again after edit 1, by itself")
    took = time.monotonic() - t0
    line = [x for x in page.evaluate("window.__lines") if "Edit 2: done in" in x][-1]
    said = float(re.search(r"done in ([0-9.]+) s", line).group(1))
    U.check(said <= took, f"edit 2's run says its own time: « {line} », within the {took:.1f} s since Enter")
    page.close()
