"""The check of View > Cache memory > Custom… (tests/flows/README.md). It asks for a size in MB or GB in a field, sets
the frame cache's budget, and the next session keeps it. A size it cannot read changes nothing, and the status line
says what to type. Whatever the cache holds, a paused frame shows at the plate's own size."""

import re

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
KEPT = "localStorage.getItem('paintaplate.cache')"


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    U.menu(page, "View", "Cache memory", "Custom…")
    page.wait_for_function("document.querySelector('#ask').open", timeout=5000)
    U.check(page.is_visible("#ask-field"), "Custom… asks for the size in a field")
    page.fill("#ask-field", "1.5 GB"); page.keyboard.press("Enter")
    U.check(U.poll(page, lambda: page.text_content("#hud") == page.text_content("#status") == "Cache memory: 1.5 GB.", 5) and page.evaluate(KEPT) == "1500000000",
            f"Enter sets 1.5 GB, the HUD and the status line say so in the same words, and the next session keeps it: {page.text_content('#hud')!r}, {page.evaluate(KEPT)}")
    page.click("#view", button="right")  # as U.menu, with the row found by its text: a ticked row's name holds its tick
    for label in ("View", "Cache memory"):
        page.locator("#ctx li.group > span:first-child", has_text=re.compile(f"^{label}$")).first.hover()
    page.locator("#ctx [role=menuitemcheckbox]", has_text="Custom…").click()
    page.wait_for_function("document.querySelector('#ask').open", timeout=5000)
    U.check(page.input_value("#ask-field") == "1.5 GB", "the field opens on the size in use")
    U.check([page.text_content("#ask-no"), page.text_content("#ask-yes")] == ["Keep the current size", "Set this size"],
            f"Custom… names what each button does: {[page.text_content('#ask-no'), page.text_content('#ask-yes')]}")
    page.fill("#ask-field", "5 TB"); page.click("#ask-yes")
    U.check(U.poll(page, lambda: "from 128 MB to 32 GB" in page.text_content("#status"), 5) and page.evaluate(KEPT) == "1500000000",
            f"a size outside 128 MB to 32 GB changes nothing, and the status line says what to type: {page.text_content('#status')!r}")
    said = page.text_content("#status")
    U.check("error" in (page.get_attribute("#status", "class") or "").split() and said.startswith('Error: Cache memory not changed: "5 TB"')
            and said.endswith("Type a size such as 2 GB.") and not any("Type a size" in t for t in U.log_lines(page)),
            f"the fault shows in red with its word, and what to type stays out of the log: {said!r}")
    page.click("#view", button="right")
    for label in ("View", "Cache memory"):
        page.locator("#ctx li.group > span:first-child", has_text=re.compile(f"^{label}$")).first.hover()
    page.locator("#ctx [role=menuitemcheckbox]", has_text="Custom…").click()
    page.wait_for_function("document.querySelector('#ask').open", timeout=5000)
    page.fill("#ask-field", "1.5 GB"); page.keyboard.press("Enter")
    U.check(U.poll(page, lambda: page.text_content("#status") == "Cache memory: 1.5 GB.", 5) and "error" not in (page.get_attribute("#status", "class") or ""),
            f"a right size then replaces the fault on the status line, in the normal colour: {page.text_content('#status')!r}")
    page.reload()
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    U.check(U.poll(page, lambda: any(t.startswith("Frame cache, 1.5 GB (View > Cache memory): ") for t in U.log_lines(page)), 10),
            f"the next session plans its frame cache on 1.5 GB: {[t for t in U.log_lines(page) if t.startswith('Frame cache')]}")
    lines = lambda: [t for t in U.log_lines(page) if t.startswith("Frame cache, ")]  # noqa: E731
    before, size = lines(), page.viewport_size
    for w in (size["width"] - 120, size["width"] - 240, size["width"] - 60):  # as the log panel opens and the window shrinks
        page.set_viewport_size({"width": w, "height": size["height"]}); page.wait_for_timeout(700)
    page.set_viewport_size(size); page.wait_for_timeout(700)
    U.check(lines() == before, f"a resize keeps the frame cache and writes no line: {lines()[len(before):]}")
    page.close()
    # Paused, the viewer reads the frame on show at the plate's own size, whatever the cache holds: 40 MB keeps desk.mp4's
    # frames at 960 x 528 for playback, and the frame on show still comes at 1280 x 704 from the frames route.
    page = U.load(browser, port, "?blank=0&cache=40")
    asked = []
    page.on("request", lambda r: asked.append(r.url) if "/paintaplate/frames?" in r.url else None)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    U.check(U.poll(page, lambda: any(" at 960 x 528" in t for t in U.log_lines(page) if t.startswith("Frame cache, ")), 10),
            f"40 MB keeps the frames smaller than the plate: {[t for t in U.log_lines(page) if t.startswith('Frame cache')]}")
    for _ in range(5):
        page.keyboard.press("ArrowRight")
    U.check(U.poll(page, lambda: any("first=5&count=1&side=4096" in u for u in asked), 10), f"paused on frame 6, the viewer reads it at its own size: {asked[-2:]}")
    U.check(page.evaluate("document.querySelector('#view').width") == 1280, "the viewer's canvas holds the plate's own 1280 px: from 1:1, its pixels show as squares")
    page.close()
