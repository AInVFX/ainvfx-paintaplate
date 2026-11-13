"""The pipeline workstream's page checks for memory and previews (tests/flows/README.md): the memory profile at page
open, and what each post asks ComfyUI for. The mock ComfyUI lists the posts at /mock/posts."""
import json
import urllib.request

READY = "document.querySelector('#status').textContent.startsWith('Ready')"
LOGGED = "(start) => [...document.querySelectorAll('#log li span')].some((e) => e.textContent.startsWith(start))"


def posts(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/mock/posts", timeout=5) as r:
        return json.load(r)


def posted(port, count, page, limit=30):  # the posts, once there are `count` of them: the page posts after it says Ready
    for _ in range(limit * 2):
        if len(posts(port)) >= count:
            break
        page.wait_for_timeout(500)
    return posts(port)


def logged(page, start):  # the log line that starts with `start`, once it is written: the page says Ready before /system_stats answers
    try:
        page.wait_for_function(LOGGED, arg=start, timeout=20000)
    except Exception:
        return ""
    return next(t for t in page.eval_on_selector_all("#log li span", "els => els.map((e) => e.textContent)") if t.startswith(start))


def run(browser, port, U):
    address = f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0"
    before = len(posts(port))
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(address + "&memory=small")  # a small card, asked for: the mock's card has 32 GB
    page.wait_for_function(READY, timeout=60000)
    line = logged(page, "Memory profile small:")
    U.check(line.startswith("Memory profile small: asked for") and "would choose medium" in line, f"the log names the memory profile and why: {line}")
    U.check(line.endswith("Models load one at a time and LTX works in 256 px tiles, so each step takes longer than on a larger card"),
            "a small card: the same line says what it means, in one sentence")
    page.wait_for_timeout(3000)
    U.check(len(posts(port)) == before, "a small card: no model loads at page open (no job is posted)")
    page.close()

    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(address)
    page.wait_for_function(READY, timeout=60000)
    U.check(logged(page, "Memory profile medium:") != "", "the mock's 32 GB card: the medium profile")
    warm = posted(port, before + 2, page)[before:]
    U.check(len(warm) == 2 and all(p["extra_data"] == {"preview_method": "none"} for p in warm),
            f"medium: the two edit models load at page open, and a warm-up asks for no preview: {warm}")
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden", timeout=60000)
    page.evaluate(U.WATCH)
    page.keyboard.press("p")
    U.paint_once(page, "a lantern", [(0.3, 0.5), (0.34, 0.56)])
    page.keyboard.press("Enter")
    U.wait_log(page, r"window.__lines.some((t) => /: done in [\d.]+ s \(.*\d+ previews?\)$/.test(t))", 120000, "the previews a job received, in its line of the log")
    asked = [p["extra_data"] for p in posts(port)[before + 2:] if "patch" in p["outputs"]]
    U.check({"preview_method": "latent2rgb"} in asked, f"a Klein pass asks ComfyUI for its step previews in its own post: {asked}")
    others = [p for p in posts(port)[before + 2:] if "patch" not in p["outputs"]]
    U.check(all(p["extra_data"] == {"preview_method": "none"} for p in others), "every other job asks for none")
    page.close()
