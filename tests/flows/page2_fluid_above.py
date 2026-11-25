"""A fluid shot made again with two Paint edits above it: both wait for its new first frame, outside the render, and their
rows say so. The render displayed is the fluid shot alone, its preview then its full size. Then each Paint is made again
in History's order, once each, and the render of all three edits starts after both. The mock holds the fluid shot's
preview open, so the check always meets the wait."""

FLUID = '#history li[data-id="fluid"]'
LOG = "[...document.querySelectorAll('#log li')].map((e) => e.textContent)"
SMALL = "[...document.querySelectorAll('#history li')].map((li) => [li.querySelector('.title').textContent, li.querySelector('small').textContent])"
ALL = "3 edits (Fluid 1, Paint 2, Paint 3)"


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    lines = lambda: page.evaluate(LOG)
    at = lambda part, since=0: next((i for i, line in enumerate(lines()) if i >= since and part in line), None)

    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    U.paint_once(page, "thick white smoke", [(0.3, 0.7), (0.4, 0.6), (0.5, 0.7)])
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1) + " && document.querySelector('#fluid').hidden", timeout=120000)
    U.settled(page)
    page.click('.tools [data-tool="paint"]')
    U.paint_once(page, "a red ball", [(0.4, 0.5), (0.45, 0.52), (0.5, 0.5)])
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=2), timeout=120000)
    U.settled(page)
    page.click("#new-edit")
    U.paint_once(page, "a blue cube", [(0.45, 0.5), (0.5, 0.52), (0.55, 0.5)])
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=3), timeout=120000)
    U.settled(page)

    # The fluid shot made again: one more stroke on its keyframe, its preview held open
    since = len(lines())
    page.click(f"{FLUID} .edit")
    U.stroke(page, [(0.6, 0.3), (0.65, 0.35), (0.7, 0.3)])
    U.mock_route(port, "/mock/hold", {"output": "plate", "seconds": 8, "times": 1})  # the first job that writes the fluid shot: its preview, when it renders alone
    page.keyboard.press("Enter")
    U.check(U.poll(page, lambda: any(e[0] == "held" for e in U.mock_route(port, "/mock/events")), 60), "the fluid shot's preview runs, held open: the fluid shot alone renders")
    rows = dict(page.evaluate(SMALL))
    U.check(rows.get("2. Paint") == "Waits for the fluid shot" and rows.get("3. Paint") == "Waits for the fluid shot" and at(ALL, since) is None,
            f"while the fluid shot renders, both Paint edits wait outside the render, and their rows say so: {rows}")
    U.settled(page)
    done2, done3, render = at("Edit 2: done", since), at("Edit 3: done", since), at(ALL, since)
    preview, full = at("Fluid shot, preview: done", since), at("Fluid shot, full size: done", since)
    U.check(None not in (done2, done3, render, preview, full) and preview < full < done2 < done3 < render,
            f"the fluid shot's preview, then its full size, then Paint 2, then Paint 3, then the render of all three: lines {preview}, {full}, {done2}, {done3}, {render}")
    twice = [n for n in ("Edit 2: done", "Edit 3: done") if sum(n in line for line in lines()[since:]) != 1]
    U.check(not twice, f"each Paint edit is made again once: {twice or 'both once'}")
    U.no_errors(errors, "after the fluid shot made again")
    page.close()
