"""View > Clear unused cache… (cache.py). A paint renders to its full-size composite and is saved as a scene; a second
paint renders a second version. The page loads again, so no plate is on screen: the dialog says how much it clears, Yes
clears the second version's files, and the saved scene then opens with every job from the job index."""

STEPS = ("ingest", "prompt", "edit", "snap", "clean", "cleanup", "shot", "matte", "comp", "review")
ROWS = """(() => {{ const t = [...document.querySelectorAll('#history li .title')].map((e) => e.textContent);
  return t.join() === '{rows}' && !document.querySelector('#history li.busy'); }})()"""


def edit(page, U, key, words, points, rows, what):
    page.evaluate(U.WATCH)
    page.keyboard.press(key)
    seen = len(U.log_lines(page))
    page.fill("#prompt", words); page.evaluate("document.activeElement.blur()")
    U.stroke(page, points)
    if key == "c":
        U.rested(page, seen)  # SAM finds the object while the strokes rest
    page.keyboard.press("Enter")
    page.wait_for_function(ROWS.format(rows=rows), timeout=120000)
    U.wait_log(page, U.added_line("Composite, full size: done in"), 240000, what)
    U.settled(page)


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, "?blank=0&memory=small", errors=errors)
    U.open_plate(page)
    edit(page, U, "p", "a red fire", [(0.3, 0.6), (0.35, 0.65)], "1. Paint", "the first full-size composite")
    name, _ = U.save_scene(page)
    edit(page, U, "c", "the cup", [(0.6, 0.4), (0.62, 0.45)], "2. Clean,1. Paint", "the second full-size composite")
    page.reload()
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    page.evaluate(U.WATCH)
    U.menu(page, "View", "Clear unused cache…")
    page.wait_for_function("document.querySelector('#ask').open", timeout=10000)
    asked, buttons = page.text_content("#ask-text"), (page.text_content("#ask-no"), page.text_content("#ask-yes"))
    page.click("#ask-yes")
    U.wait_log(page, U.added_line("Unused cache cleared:"), 30000, "the unused cache cleared")
    U.check(asked.startswith("Clear ") and asked.endswith("of unused cache? Saved scenes, exports and the plate on screen keep their files."),
            f"the dialog says how much it clears and what stays: {asked}")
    U.check(buttons == ("No, cancel", "Yes, clear it"), f"each button says what it does: {buttons}")
    U.check(page.text_content("#hud") == page.text_content("#status").strip(), "the HUD and the status line say the same")
    page.evaluate(U.WATCH)
    U.open_scene(page, name)
    page.wait_for_function("window.__lines.some((t) => t.startsWith('Scene opened'))", timeout=120000)
    page.wait_for_function(ROWS.format(rows="1. Paint"), timeout=120000)
    page.wait_for_function("window.__lines.some((t) => t.startsWith('review: taken from the job index') || t.startsWith('review '))", timeout=180000)
    U.settled(page)
    posted = {k: v for k, v in U.added(page, STEPS).items() if k.endswith("posted") and v}
    U.check(not posted, f"after the clear, the saved scene opens with every job from the job index: {posted}")
    U.no_errors(errors, "with the unused cache cleared")
    page.close()
