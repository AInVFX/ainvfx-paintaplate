"""The page workstream's check of the OCIO menu (tests/flows/README.md). Two headings say which part changes the result,
and each line shows its value. The plate's line says where its value comes from. With an edit that has a result, a new
plate colour space asks first: Cancel changes nothing, Change opens the plate again in it, and the line then says
« chosen by you »."""

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
ROWS = """() => { const g = [...document.querySelectorAll('#ctx li.group')].find((li) => li.firstChild.textContent === 'OCIO');
  return [...g.querySelector(':scope > ul.sub').children].map((li) => li.classList.contains('head') ? `# ${li.textContent}`
    : li.classList.contains('sep') ? '-' : li.firstChild.textContent); }"""
FILE, LINEAR = "sRGB Encoded Rec.709 (sRGB)", "Linear Rec.709 (sRGB)"


def run(browser, port, U):
    page = U.load(browser, port)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)

    def rows():
        page.click("#view", button="right")
        got = page.evaluate(ROWS)
        page.keyboard.press("Escape")
        return got

    first = rows()
    U.check(first[:5] == ["# THE PLATE · changes the result", f"Plate colour space: {FILE}, read from the file", "# THE VIEW · never changes a result",
                          "View: Un-tone-mapped", "Display: sRGB - Display"]
            and all(r.startswith("Look: ") for r in first[5:-2]) and first[-2] == "-" and first[-1].startswith("Config: "),
            f"two headings say which part changes the result, and each line shows its value: {first}")

    page.keyboard.press("p")
    U.paint_once(page, "a lantern", [(0.30, 0.50), (0.36, 0.50)])
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    page.evaluate(U.WATCH)
    changed = lambda: [t for t in page.evaluate("window.__lines") if t.startswith(("Plate colour space", "ingest "))]  # noqa: E731
    pick = (f"Plate colour space: {FILE}, read from the file", "Utility", LINEAR)
    U.menu(page, "OCIO", *pick)
    page.wait_for_selector("#ask[open]", timeout=5000)
    asked = page.text_content("#ask-text")
    page.click("#ask-no")
    page.wait_for_timeout(1000)
    U.check(asked == "This makes the first frame and 1 edit again." and FILE in page.text_content("#spec") and not changed() and page.is_hidden("#ask"),
            f"with an edit made, a new plate colour space asks first, and Cancel changes nothing: {asked!r}, {changed()}")

    U.menu(page, "OCIO", *pick)
    page.wait_for_selector("#ask[open]", timeout=5000)
    page.click("#ask-yes")
    page.wait_for_function(f"document.querySelector('#spec').textContent.includes('{LINEAR}') && document.querySelector('#opening').hidden", timeout=60000)
    U.check(any(t.startswith(f"Plate colour space: {LINEAR}, was {FILE}") for t in changed()), f"Change opens the plate again in the new space: {changed()}")
    after = rows()
    U.check(after[1] == f"Plate colour space: {LINEAR}, chosen by you", f"the plate's line now says the value is chosen by you: {after[1]!r}")
    U.check(not errors, f"no page errors: {errors}")
    page.close()
