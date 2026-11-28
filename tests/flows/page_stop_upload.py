"""A pass that a stop reaches while it waits posts no further job. The uploads are slowed, and the edit's eye is turned off
while a picture of the pass is still on its way to ComfyUI: first the frame under the edit, so the prompt writer is not
asked; then, for an edit whose caption is ready, its mask, so Klein's job is not posted. No job of the edit runs behind
the stop. Turned on again, each edit is made."""
import re

SLOW = """() => { const open = XMLHttpRequest.prototype.open, send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) { this.__url = String(url); return open.call(this, method, url, ...rest); };
  XMLHttpRequest.prototype.send = function (body) { const wait = this.__url.includes('/upload/image') ? (window.__slowUpload || 0) : 0;
    if (wait) setTimeout(() => send.call(this, body), wait); else send.call(this, body); }; }"""  # an upload waits window.__slowUpload ms before it leaves


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    page.evaluate(SLOW)
    U.open_plate(page)
    page.click('.tools [data-tool="paint"]')
    page.fill("#prompt", "a red ball"); page.evaluate("document.activeElement.blur()")
    page.evaluate("window.__slowUpload = 2500")
    page.evaluate(U.WATCH)
    U.stroke(page, [(0.3, 0.5), (0.36, 0.52)])
    page.keyboard.press("Enter")
    page.wait_for_function(U.added_line('Edit 1: Paint "a red ball"'), timeout=30000)  # the pass has started: its uploads are on their way
    page.click("#history li .eye")  # the edit bypassed: its pass stops
    page.wait_for_function(U.added_line("Edit 1 is bypassed."), timeout=10000)
    page.evaluate("window.__slowUpload = 0")
    page.wait_for_timeout(6500)  # past both uploads, and past what a prompt writer's job would take
    lines = page.evaluate("window.__lines")
    asked = [t for t in lines if "asking Klein's prompt writer" in t or re.match(r"(prompt|edit) \\w+: ", t)]
    U.check(not asked, f"stopped while its uploads were on their way, the pass asks no prompt writer and posts no job: {asked}")
    page.click("#history li .eye")  # back on: the edit is made
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    U.check(U.row_titles(page) == ["1. Paint"] and "Edit 1 is back on." in page.evaluate("window.__lines"), f"turned on again, the edit is made: {U.row_titles(page)}")
    page.keyboard.press("n")  # a second edit, whose caption arrives while its strokes rest
    page.evaluate(U.WATCH)
    U.paint_once(page, "a blue kite", [(0.62, 0.3), (0.68, 0.32)])
    page.wait_for_function(U.added_line("Edit 2: caption from the prompt writer."), timeout=60000)
    page.evaluate("window.__slowUpload = 2500")
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelector('#status').textContent === 'Edit 2: Paint, edit preview.'", timeout=30000)  # its mask leaves next
    page.click("#history li:first-child .eye")
    page.wait_for_function(U.added_line("Edit 2 is bypassed."), timeout=10000)
    page.evaluate("window.__slowUpload = 0")
    page.wait_for_timeout(6500)
    lines = page.evaluate("window.__lines")
    posted = [t for t in lines if "Klein edit preview" in t or re.match(r"edit \\w+: ", t)]
    U.check(not posted, f"stopped while its mask was on its way, the pass posts no job to Klein: {posted}")
    page.click("#history li:first-child .eye")
    page.wait_for_function(U.DONE.format(n=2), timeout=120000)
    U.check(U.row_titles(page) == ["2. Paint", "1. Paint"], f"turned on again, the second edit is made: {U.row_titles(page)}")
    U.no_errors(errors, "after the stops and the passes that followed")
    page.close()
