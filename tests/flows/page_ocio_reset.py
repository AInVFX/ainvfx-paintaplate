"""Reset OCIO: Shift+End and right-click > OCIO > Reset OCIO bring back the config's own display and view, with no look,
and say so in the same words in the status line and the log. Shift+End leaves the playhead where it is."""
import json
import re
import urllib.request


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    info = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/paintaplate/ocio", timeout=10).read())
    other = next(v for v in next(d for d in info["displays"] if d["name"] == info["display"])["views"] if v != info["view"])
    said = f"OCIO reset: display {info['display']}, view {info['view']}."
    resets = lambda: sum(t == said for t in U.log_lines(page))  # noqa: E731

    U.menu(page, "OCIO", f"View: {info['view']}", other)
    U.wait_log(page, f"[...document.querySelectorAll('#log li span')].some((e) => e.textContent.includes({json.dumps(other)}))", 5000, "the other view")
    frame = page.text_content("#frame-now")
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("Shift+End")
    U.check(U.until(page, f"document.querySelector('#status').textContent === {json.dumps(said)}", 5000) and resets() == 1,
            f"Shift+End resets OCIO, in the same words in the status line and the log: {page.text_content('#status')!r}")
    U.check(page.text_content("#frame-now") == frame, f"Shift+End leaves the playhead where it was: frame {page.text_content('#frame-now')}, was {frame}")

    U.menu(page, "OCIO", f"View: {info['view']}", other)
    page.click("#view", button="right")  # the entry carries its key, Shift+End
    page.locator("#ctx li.group > span:first-child", has_text=re.compile(r"^OCIO$")).first.hover()
    page.locator("#ctx li:not(.group)", has_text=re.compile(r"^Reset OCIO")).first.click()
    U.check(U.until(page, f"document.querySelector('#status').textContent === {json.dumps(said)}", 5000) and resets() == 2,
            "right-click > OCIO > Reset OCIO does the same")
    U.no_errors(errors, "after the two resets")
    page.close()
