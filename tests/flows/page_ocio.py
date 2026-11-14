"""The page workstream's check of the OCIO menu (tests/flows/README.md). Two headings say which part affects generation
and which is for display only, and each line shows its value. The plate's line ends with « from file » or « override ».
With an edit that has a result, an OCIO change that regenerates asks first, with one question: a new config, then a new
colour space. Cancel changes nothing and keeps the menu's tick; Continue goes on. A new view asks nothing. In the plate's tree the
config's family « Display » reads « Display-referred »: the view's Display line keeps the word."""
import re

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
GROUP = "[...document.querySelectorAll('#ctx li.group')].find((li) => li.firstChild.textContent === label)"
ROWS = """() => { const label = 'OCIO', g = %s;
  return [...g.querySelector(':scope > ul.sub').children].map((li) => li.classList.contains('head') ? `# ${li.textContent}`
    : li.classList.contains('sep') ? '-' : li.firstChild.textContent); }""" % GROUP
TICKED = "(label) => [...%s.querySelectorAll(':scope > ul.sub > li > button[aria-checked=\"true\"]')].map((b) => b.children[1].textContent)" % GROUP
OTHER = """(label) => { const b = [...%s.querySelectorAll(':scope > ul.sub > li > button')].find((x) => x.getAttribute('aria-checked') === 'false');
  b.dataset.pick = '1'; return b.children[1].textContent; }""" % GROUP
FAMILIES = "(label) => [...%s.querySelectorAll(':scope > ul.sub > li.group')].map((li) => li.firstChild.textContent)" % GROUP
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

    def ticked(label):
        page.click("#view", button="right")
        got = page.evaluate(TICKED, label)
        page.keyboard.press("Escape")
        return got

    first = rows()
    U.check(first[:5] == ["# Plate (affects generation)", f"Colour space: {FILE}, from file", "# View (display only)", "View: Un-tone-mapped", "Display: sRGB - Display"]
            and all(r.startswith("Look: ") for r in first[5:-2]) and first[-2] == "-" and first[-1].startswith("Config: "),
            f"two headings say what affects generation and what is display only, and each line shows its value: {first}")
    config = first[-1]
    page.click("#view", button="right")
    families = page.evaluate(FAMILIES, f"Colour space: {FILE}, from file")
    page.keyboard.press("Escape")
    U.check("Display-referred" in families and "Display" not in families and "Display: sRGB - Display" in first,
            f"the plate's tree names the config's family of display spaces Display-referred, and the view keeps its Display line: {families}")

    page.click('.tools [data-tool="paint"]')
    U.paint_once(page, "a lantern", [(0.30, 0.50), (0.36, 0.50)])
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    page.evaluate(U.WATCH)
    changed = lambda: [t for t in page.evaluate("window.__lines") if t.startswith(("Plate colour space", "ingest ", "OCIO config"))]  # noqa: E731

    U.menu(page, "OCIO", "View: Un-tone-mapped", "ACES 2.0 - SDR 100 nits (Rec.709)")
    page.wait_for_timeout(500)
    U.check(page.is_hidden("#ask") and not changed(), f"a new view is display only: no question, nothing regenerates: {changed()}")
    U.menu(page, "OCIO", "View: ACES 2.0 - SDR 100 nits (Rec.709)", "Un-tone-mapped")

    before = ticked(config)
    page.click("#view", button="right")
    for label in ("OCIO", config):
        page.locator("#ctx li.group > span:first-child", has_text=re.compile(f"^{re.escape(label)}$")).first.hover()
    other = page.evaluate(OTHER, config)
    page.click('#ctx button[data-pick="1"]')
    page.wait_for_selector("#ask[open]", timeout=5000)
    asked, buttons = page.text_content("#ask-text"), page.eval_on_selector_all("#ask menu button", "els => els.map((e) => e.textContent)")
    page.click("#ask-no")
    page.wait_for_timeout(1000)
    U.check(asked == "Changing the OCIO config affects generation: 1 edit will be regenerated. Continue?" and buttons == ["Cancel", "Continue"] and ticked(config) == before and not changed() and page.is_hidden("#ask"),
            f"a new config ({other}) asks first, and Cancel keeps the config and its tick: {asked!r} {buttons}, {before} then {ticked(config)}, {changed()}")

    pick = (f"Colour space: {FILE}, from file", "Utility", LINEAR)
    U.menu(page, "OCIO", *pick)
    page.wait_for_selector("#ask[open]", timeout=5000)
    asked = page.text_content("#ask-text")
    page.click("#ask-no")
    page.wait_for_timeout(1000)
    U.check(asked == "Changing the plate's colour space affects generation: 1 edit will be regenerated. Continue?" and FILE in page.text_content("#spec") and not changed() and page.is_hidden("#ask"),
            f"a new colour space asks the same question, and Cancel changes nothing: {asked!r}, {changed()}")
    U.menu(page, "OCIO", *pick)
    page.wait_for_selector("#ask[open]", timeout=5000)
    page.click("#ask-yes")
    page.wait_for_function(f"document.querySelector('#spec').textContent.includes('{LINEAR}') && document.querySelector('#opening').hidden", timeout=60000)
    U.check(any(t.startswith(f"Plate colour space: {LINEAR}, was {FILE}") for t in changed()), f"Continue opens the plate again in the new colour space: {changed()}")
    after = rows()
    U.check(after[1] == f"Colour space: {LINEAR}, override", f"the plate's line now ends with override: {after[1]!r}")
    U.check(not errors, f"no page errors: {errors}")
    page.close()
