"""Preview size: Off. A render skips the four preview steps and starts with the full-size passes, the Render panel lists no
preview row, and the viewer keeps the plate until the full-size composite is ready."""
import re

STATUS = "document.querySelector('#status').textContent"


def run(browser, port, U):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
    page.wait_for_function(f"{STATUS}.startsWith('Ready')", timeout=60000)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden", timeout=60000)
    first = page.evaluate("[document.querySelector('#preview-size').options[0].value, document.querySelector('#preview-size').options[0].text]")
    U.check(first[0] == "0" and first[1].startswith("Off"), f"Off is the first choice of Preview size: {first}")
    page.select_option("#preview-size", "0")
    U.check(page.text_content("#status") == "Shot preview: off. A render starts with the full-size passes.", f"the status line says so: {page.text_content('#status')}")
    page.evaluate(U.WATCH)
    page.keyboard.press("p")
    U.paint_once(page, "a lantern", [(0.3, 0.5), (0.34, 0.56)])
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelector('#render-left').textContent === 'full size ready'", timeout=180000)
    lines = page.evaluate("window.__lines")
    started = [t for t in lines if re.match(r"Render v\d+: .+: about \d+ s", t)]
    U.check(any(t.startswith("Render v1: Composite, full size: about") for t in started) and not any(", preview: about" in t for t in started),
            f"the render starts no preview step, and makes the full-size composite: {started}")
    U.check(any(t.startswith("Render v1: 1 edit (") and "shot preview off" in t for t in lines), "the render's line says that the shot preview is off")
    U.check(not any(t.startswith("Viewer: full-size shot") for t in lines), "the viewer keeps the plate until the full-size composite")
    rows = page.evaluate("[...document.querySelectorAll('#stages li .name')].map((e) => e.textContent)")
    U.check(bool(rows) and not any(", preview" in r for r in rows), f"the Render panel lists no preview row: {rows}")
    page.close()
