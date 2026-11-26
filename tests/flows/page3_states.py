"""The line under the timeline follows the Render panel's status line: for a fluid shot alone, which makes no composite,
it turns grey once the preview is made and while the full size runs, then green once the full size is made."""


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
