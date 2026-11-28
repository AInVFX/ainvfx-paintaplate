"""An edit turned off over a set that was never rendered alone: the viewer pauses on the first frame, as the edits still on make
it, and the status line says that this set renders now (app.toggle). The two edits are asked for one after the other, so
the first one's set never renders by itself."""
LINE = "Edit 2 is bypassed. This set of edits renders now: its first frame shows until its shot is made."


def run(browser, port, U):
    page = U.load(browser, port, "?blank=0")
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.keyboard.press("p")
    U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)])
    page.keyboard.press("Enter")
    U.paint_once(page, "a blue lamp", [(0.6, 0.4), (0.65, 0.45)])
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Edit 2: done in"), 180000, "the second edit")
    U.wait_log(page, U.added_line("Composite, full size: done in"), 240000, "the two edits' full-size composite")
    U.settled(page)
    renders = page.evaluate("window.__lines.filter((t) => /^Render v\\d+: \\d+ edit/.test(t))")
    page.click("#play-btn")  # playing, as a person watching the result
    page.wait_for_timeout(1000)
    page.locator("#history li", has_text="2. Paint").locator(".eye").click()
    U.poll(page, lambda: (page.text_content("#status") or "") == LINE, 5)
    status, frame = page.text_content("#status") or "", (page.text_content("#frame-now") or "").strip()
    U.check(status == LINE and frame == page.evaluate("String(1)"),
            f"the set below was never made: the first frame shows, paused, and the line says it renders: {status!r}, frame {frame!r}, renders before: {renders}")
    page.close()
