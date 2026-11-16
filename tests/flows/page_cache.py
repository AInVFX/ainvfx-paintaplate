"""The check of View > Cache memory > Custom… (tests/flows/README.md). It asks for a size in MB or GB in a field, sets
the frame cache's budget, and the next session keeps it. A size it cannot read changes nothing, and the status line
says what to type."""

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
    U.check(U.poll(page, lambda: page.text_content("#hud") == "Cache memory: 1.5 GB", 5) and page.evaluate(KEPT) == "1500000000",
            f"Enter sets 1.5 GB, and the next session keeps it: {page.text_content('#hud')!r}, {page.evaluate(KEPT)}")
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
    page.reload()
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    U.check(U.poll(page, lambda: any(t.startswith("Frame cache: 1.5 GB (set in View > Cache memory)") for t in U.log_lines(page)), 10),
            f"the next session plans its frame cache on 1.5 GB: {[t for t in U.log_lines(page) if t.startswith('Frame cache')]}")
    lines = lambda: [t for t in U.log_lines(page) if t.startswith("Frame cache:")]  # noqa: E731
    before, size = lines(), page.viewport_size
    for w in (size["width"] - 120, size["width"] - 240, size["width"] - 60):  # as the log panel opens and the window shrinks
        page.set_viewport_size({"width": w, "height": size["height"]}); page.wait_for_timeout(700)
    page.set_viewport_size(size); page.wait_for_timeout(700)
    U.check(lines() == before, f"a resize keeps the frame cache and writes no line: {lines()[len(before):]}")
    page.close()
