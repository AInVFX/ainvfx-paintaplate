"""A Finish switch waits for Generate on a plate with no edit, as on a made edit (fix4_finish_edit). SDR to HDR turned on adds
« Plate, HDR » in grey, with its estimate, and posts no job: Generate runs it. Upscale turned on over that made result adds its
step in grey too, the status line says what Generate runs, and no job is posted until Generate, which runs it."""
ROWS = "els => els.map((e) => [e.querySelector('.name').textContent, e.querySelector('.time').textContent, e.className])"
RESTS = "['full size ready', 'finish ready'].includes(document.querySelector('#render-left').textContent)"


def run(browser, port, U):
    page = U.load(browser, port)
    posted = []
    page.on("request", lambda req: posted.append(req.url) if req.method == "POST" and req.url.endswith("/prompt") else None)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    rows = lambda: page.eval_on_selector_all("#stages li", ROWS)  # noqa: E731
    grey = lambda name: [r for r in rows() if r[0] == name and r[2] == "" and r[1].startswith("~")]  # noqa: E731  # waiting, with its estimate
    page.wait_for_timeout(1000)
    made = len(posted)  # the jobs that opened the plate
    page.click("#finish-btn"); page.click("#finish-hdr"); page.click("#finish-hdr-yes"); page.keyboard.press("Escape")
    page.wait_for_timeout(1500)
    U.check(len(posted) == made and grey("Plate, HDR") and page.is_enabled("#generate"),
            f"SDR to HDR on: its step waits in grey with its estimate, no job is posted, and Generate is live: {rows()}, {len(posted) - made} new jobs")
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Plate, HDR: done in"), 120000, "SDR to HDR on the plate, from Generate")
    page.wait_for_function(RESTS, timeout=60000)
    made = len(posted)
    page.click("#finish-btn"); page.click("#finish-upscale"); U.upscale_custom(page, "1024"); page.keyboard.press("Escape")
    page.wait_for_timeout(1500)
    up = [r[0] for r in rows() if r[0].endswith("upscaled")]
    status = page.text_content("#status") or ""
    U.check(len(posted) == made and up and grey(up[0]) and page.is_enabled("#generate") and "Generate runs it: about " in status,
            f"Upscale on over the made result: its step waits in grey, no job is posted, Generate is live, and the status line says "
            f"what it runs: {rows()}, {len(posted) - made} new jobs, {status!r}")
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("upscaled: done in"), 120000, "Upscale on the plate, from Generate")
    page.wait_for_function(RESTS, timeout=60000)
    U.check(len(posted) > made and page.is_disabled("#generate") and up and not grey(up[0]),
            f"Generate ran it, and has nothing left to start: {rows()}")
    page.close()
