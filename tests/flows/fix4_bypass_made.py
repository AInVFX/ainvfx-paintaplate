"""The top edit of a made set turned off: the set below, made already, plays at once, and nothing is posted, no render step, no
matte and no SAM 3.1; turned on again, the set above comes back the same way (app.toggle, rebuild). The set below was
rendered alone before the second edit came."""
RESTS = "['full size ready', 'finish ready'].includes(document.querySelector('#render-left').textContent)"


def run(browser, port, U):
    page = U.load(browser, port, "?blank=0")
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.keyboard.press("p")
    U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)])
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, full size: done in"), 240000, "the first set's full-size composite")
    U.settled(page)
    U.paint_once(page, "a blue lamp", [(0.6, 0.4), (0.65, 0.45)])
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Edit 2: done in"), 120000, "the second edit")
    page.wait_for_function("window.__lines.filter((t) => t.includes('Composite, full size: done in')).length >= 2", timeout=240000)
    U.settled(page)
    posted = []
    page.on("request", lambda req: posted.append(req.url) if req.method == "POST" and req.url.endswith("/prompt") else None)
    eye = page.locator("#history li", has_text="2. Paint").locator(".eye")
    eye.click()
    page.wait_for_timeout(3000)
    off = page.text_content("#status") or ""
    U.check(not posted and off == "Edit 2 is bypassed." and page.evaluate(RESTS),
            f"the top edit off: the set below plays at once, with nothing posted: {off!r}, {len(posted)} jobs")
    eye.click()
    page.wait_for_timeout(3000)
    on = page.text_content("#status") or ""
    U.check(not posted and on == "Edit 2 is back on." and page.evaluate(RESTS), f"on again: the set above plays at once, with nothing posted: {on!r}, {len(posted)} jobs")
    page.close()
