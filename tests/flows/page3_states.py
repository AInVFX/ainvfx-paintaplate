"""The line under the timeline follows the Render panel's status line: for a fluid shot alone, which makes no composite,
it turns grey once the preview is made and while the full size runs, then green once the full size is made. On a plate
with no edit, a Finish switch turned on lists its step, and the status line names no time before Enter: it counts once
the render runs, then says « finish ready »."""


def run(browser, port, U):
    page = U.load(browser, port)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24")
    page.fill("#b-frames", "33"); page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    page.evaluate(U.WATCH)
    U.paint_once(page, "thick white smoke", [(0.3, 0.7), (0.4, 0.6), (0.5, 0.7)])
    page.keyboard.press("Enter")
    bar = lambda: page.get_attribute("#tl-render", "class") or ""  # noqa: E731
    U.wait_log(page, U.added_line("Fluid shot, preview: done in"), 120000, "the fluid shot's preview")
    U.mock_route(port, "/mock/hold", {"slot": "path", "seconds": 8})  # the full size's job stays open while the bar is read
    U.wait_log(page, U.added_line("Fluid shot, full size: about"), 60000, "the full size starting")
    U.check(U.poll(page, lambda: "final" in bar().split(), 5),
            f"the preview made and the full size running: the line under the timeline is grey ({bar()!r}), as the status line reads « {page.text_content('#render-left')} »")
    U.wait_log(page, U.added_line("Fluid shot, full size: done in"), 120000, "the fluid shot's full size")
    U.check(U.poll(page, lambda: "ready" in bar().split(), 5),
            f"a fluid shot alone, made at full size: the line under the timeline is green ({bar()!r}), as the status line reads « {page.text_content('#render-left')} »")
    page.close()

    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.click("#finish-btn"); page.click("#finish-upscale"); page.keyboard.press("Escape")
    left = lambda: page.text_content("#render-left")  # noqa: E731
    U.check(U.poll(page, lambda: page.locator("#stages li", has_text="Plate, upscaled").count() == 1, 5),
            "Upscale on, on a plate with no edit: its step is listed, to come")
    page.wait_for_timeout(1000)
    U.check(left() == "" and "final" not in bar().split() and "ready" not in bar().split(),
            f"before Enter no render runs: the status line names no time ({left()!r}), and the line under the timeline agrees ({bar()!r})")
    page.keyboard.press("Enter")
    U.check(U.poll(page, lambda: left().startswith("finish") and left() != "finish ready", 10), f"after Enter the render runs, and the line counts: {left()!r}")
    U.wait_log(page, U.added_line("Plate, upscaled: done in"), 240000, "the plate's upscaled step")
    U.check(U.poll(page, lambda: left() == "finish ready" and "ready" in bar().split(), 5), f"made: « finish ready », the line under the timeline green: {left()!r}, {bar()!r}")
    page.close()
