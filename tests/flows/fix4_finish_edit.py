"""A Finish switch waits for Generate on a made edit, as on a plate with no edit (fix4_finish_plate). Over a Paint whose render is
made, SDR to HDR turned on adds its three steps in grey, with their estimates, posts no job, and the status line says what
Generate runs: Generate runs them. Upscale turned on then waits in the same way, until Generate runs its steps on SDR to HDR's set."""
ROWS = "els => els.map((e) => [e.querySelector('.name').textContent, e.querySelector('.time').textContent, e.className])"
RESTS = "['full size ready', 'finish ready'].includes(document.querySelector('#render-left').textContent)"
HDR = ["Plate, HDR", "Layer, HDR", "Composite, HDR"]


def run(browser, port, U):
    page = U.load(browser, port)
    posted = []
    page.on("request", lambda req: posted.append(req.url) if req.method == "POST" and req.url.endswith("/prompt") else None)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    rows = lambda: page.eval_on_selector_all("#stages li", ROWS)  # noqa: E731
    waiting = lambda: [r[0] for r in rows() if r[2] == "" and r[1].startswith("~")]  # noqa: E731  # steps in grey, with their estimates
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, full size: done in"), 240000, "the Paint's full-size composite")
    page.wait_for_function(RESTS, timeout=60000)
    made = len(posted)
    page.click("#finish-btn"); page.click("#finish-hdr"); page.click("#finish-hdr-yes"); page.keyboard.press("Escape")
    page.wait_for_timeout(1500)
    status = page.text_content("#status") or ""
    U.check(len(posted) == made and waiting() == HDR and page.is_enabled("#generate") and status.startswith("Finish: SDR to HDR on. Generate runs it: about "),
            f"SDR to HDR on over a made render: its steps wait in grey, no job is posted, Generate is live, and the status line says "
            f"what it runs: {rows()}, {len(posted) - made} new jobs, {status!r}")
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, HDR: done in"), 240000, "SDR to HDR's steps, from Generate")
    page.wait_for_function(RESTS, timeout=60000)
    made = len(posted)
    page.click("#finish-btn"); page.click("#finish-upscale"); U.upscale_custom(page, "1024"); page.keyboard.press("Escape")
    page.wait_for_timeout(1500)
    up = [name for name in waiting() if name.endswith("upscaled")]
    U.check(len(posted) == made and len(up) == 3 and page.is_enabled("#generate") and "Generate runs it: about " in (page.text_content("#status") or ""),
            f"Upscale on over SDR to HDR's made set: its steps wait in grey, no job is posted, and Generate is live: {rows()}, {len(posted) - made} new jobs")
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, HDR, upscaled: done in"), 300000, "Upscale's steps on SDR to HDR's set, from Generate")
    page.wait_for_function(RESTS, timeout=60000)
    U.check(not waiting() and page.is_disabled("#generate"), f"Generate ran them, and has nothing left to start: {rows()}")
    page.close()
