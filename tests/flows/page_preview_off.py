"""The Preview menu. A new browser starts on Latent preview: no preview pass, and each pass's live preview shows in the
player. Off makes the full size alone and asks the workflows for no live preview: the render starts no preview step, the
Render panel lists no preview row, the player shows no live preview, and every LTX pass posts live 0."""
import json
import re
import urllib.request

STATUS = "document.querySelector('#status').textContent"
LIVE = """() => { window.__live = []; const box = document.querySelector('#live');
  new MutationObserver(() => window.__live.push(box.hidden)).observe(box, { attributes: true, attributeFilter: ['hidden'] }); }"""


def posts(port):  # what the page posted to the mock ComfyUI
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/mock/posts", timeout=5) as r:
        return json.load(r)


def run(browser, port, U):
    page = browser.new_page(viewport={"width": 1400, "height": 900}, default_preview=True)
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
    page.wait_for_function(f"{STATUS}.startsWith('Ready')", timeout=60000)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden", timeout=60000)
    menu = page.eval_on_selector_all("#preview-size option", "els => els.map((e) => [e.value, e.textContent])")
    U.check([v for v, _ in menu] == ["off", "latent", "2", "4"] and menu[1][1] == "Latent preview", f"the Preview menu: Off, Latent preview, Half size, Quarter size: {menu}")
    U.check(page.input_value("#preview-size") == "latent", f"a new browser starts on Latent preview: {page.input_value('#preview-size')}")
    page.select_option("#preview-size", "off")
    U.check(page.text_content("#status") == "Preview: off. No live preview, no preview pass.", f"the status line says so: {page.text_content('#status')}")
    before = len(posts(port))
    page.evaluate(U.WATCH)
    page.evaluate(LIVE)
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
    ltx = [p["live"] for p in posts(port)[before:] if p["live"] is not None]
    U.check(len(ltx) >= 1 and all(every == 0 for every in ltx), f"every LTX pass asks for no live preview: {ltx}")
    U.check(False not in page.evaluate("window.__live"), "the player shows no live preview")
    rows = page.evaluate("[...document.querySelectorAll('#stages li .name')].map((e) => e.textContent)")
    U.check(bool(rows) and not any(", preview" in r for r in rows), f"the Render panel lists no preview row: {rows}")
    page.close()
