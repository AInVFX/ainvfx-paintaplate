"""A fluid shot's other seed comes from its History row's arrow, as an edit's does, also while the shot is being made.
The fluid panel has no button of its own for it, and the right-click menu says « Try another seed », as for an edit."""
FLUID = '#history li[data-id="fluid"]'


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    U.paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)])
    page.keyboard.press("End")
    U.stroke(page, [(0.45, 0.3), (0.55, 0.2)])
    page.keyboard.press("Enter")
    full = "[...document.querySelectorAll('#log li span')].filter((e) => /^Render v\\d+: Fluid shot, full size: done in /.test(e.textContent)).length"
    page.wait_for_function(full + " >= 1 && document.querySelector('#fluid').hidden", timeout=120000)
    U.check(page.query_selector("#fluid-again") is None, "the fluid panel has no button of its own for another seed")
    U.mock_route(port, "/mock/hold", {"output": "plate", "seconds": 4, "times": 1})  # the next fluid shot lasts 4 s
    page.click(f"{FLUID} .again")
    page.wait_for_function("document.querySelector('#stages li.now')?.textContent.includes('Fluid shot') === true", timeout=10000)
    U.check(page.is_enabled(f"{FLUID} .again"), "while the fluid shot is being made, its arrow still works, as an edit's does")
    page.click("#view", button="right")
    entries = page.eval_on_selector_all("#ctx li", "els => els.map((e) => e.textContent.trim())")
    U.check(any(t.startswith("Try another seed") for t in entries) and not any(t.startswith("Another seed") for t in entries),
            f"the right-click menu says Try another seed, as for an edit: {[t for t in entries if 'seed' in t]}")
    page.mouse.click(5, 5)  # a press outside the menu closes it and does nothing else
    page.click(f"{FLUID} .again")
    page.wait_for_function("""(() => { const t = [...document.querySelectorAll('#log li span')].map((e) => e.textContent);
      const i = t.findIndex((x) => x.startsWith('Fluid shot v3: started.'));
      return i >= 0 && t.slice(i).some((x) => / Fluid shot, full size: done in /.test(x)); })()""", timeout=120000)
    lines = U.log_lines(page)
    U.check(any(t.startswith("Fluid shot v3: started.") for t in lines) and not any(t.startswith("Error:") for t in lines),
            f"the arrow pressed during the second shot starts a third, which is made: {[t[:60] for t in lines if t.startswith('Fluid shot v')]}")
    page.close()
