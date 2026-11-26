"""Models and licences tints the models of the job displayed, as planned from its start. A Paint edit being painted, not
generated yet, already shows Klein, LTX, the Ripple IC-LoRA and SAM 3.1, each card tinted over its whole surface; once
the render is done, the same models stay tinted."""
OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
TINT = """(() => [...document.querySelectorAll('#models-all article.behind')].map((a) => getComputedStyle(a).backgroundColor))()"""


def models(page):  # opens Help > Models and licences: the models of the job displayed, and the line above them
    page.keyboard.press("?")
    page.click("#help [role=tab][data-help=models]")
    page.wait_for_function("document.querySelector('#help').open && !document.querySelector('#models').hidden", timeout=10000)
    return set(filter(None, page.get_attribute("#models", "data-shown").split(","))), page.text_content("#models-shown")


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    named, line = models(page)
    U.check(named == set() and line == "No edit turned on: no model works on this plate yet.", f"a plate with no edit: {line!r}, {sorted(named)}")
    page.keyboard.press("Escape")
    page.keyboard.press("p")
    U.paint_once(page, "a red lantern", [(0.3, 0.5), (0.34, 0.56)])
    planned, line = models(page)
    U.check({"klein", "ltx", "ripple", "sam"} <= planned and "fluid" not in planned and line == f"In gold: the {len(planned)} models these edits use.",
            f"a Paint edit being painted already shows its whole stack: {line!r}, {sorted(planned)}")
    tints = page.evaluate(TINT)
    U.check(len(tints) == len(planned) and all(t.startswith("rgba(245, 184, 0") for t in tints), f"each of its cards is tinted over its whole surface: {tints[:2]}")
    page.keyboard.press("Escape")
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelector('#render-left').textContent === 'full size ready'", timeout=180000)
    made, _ = models(page)
    U.check(made == planned, f"once the render is done, the same models: {sorted(made)} against {sorted(planned)}")
    page.keyboard.press("Escape")
    U.no_errors(errors, "with Models and licences planned from the start")
    page.close()
