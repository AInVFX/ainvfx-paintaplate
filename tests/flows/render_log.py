"""The render workstream's page checks for the log (tests/flows/README.md). The log says each fact once: the memory profile
is one entry, a job writes one line when it ends, and a blank plate writes no line of its own. On a card under 24 GB every
LTX pass still asks for its live previews. The mock ComfyUI takes the card's size at /mock/card and lists the posts at
/mock/posts."""
import json
import re
import urllib.request

PROFILE = ("Memory profile: small (16 GB of VRAM, 61 GB of RAM).\n  Models load one at a time and LTX works in 256 px tiles, so each step takes longer "
           "than on a larger card.")
DONE = r"done in [\d.]+ s \(\d+ nodes?(, \d+ from ComfyUI's cache)?(, \d+ previews?)?\)\."
JOB = re.compile(rf"^[a-z]+ [0-9a-f]{{8}}: {DONE}$")  # the one line of a job that ended
LINE = re.compile(rf"^[a-z]+ [0-9a-f?]{{1,8}}: ({DONE}|started after [\d.]+ s in ComfyUI's queue( \(.+\))?|stopped after [\d.]+ s.* \(\d+ nodes?.*\))$")  # every line a job may write
GONE = ("posted as", "ComfyUI started it", " is running", "preview(s) received", "nodes from ComfyUI's cache", "Blank plate:", "A blank plate is open",
        "Fluid shot: paint", "less than 24 GB")
SHOT = r"window.__lines.some((t) => /^shot [0-9a-f]{8}: done in [\d.]+ s \(\d+ nodes?, (\d+ from ComfyUI's cache, )?\d+ previews?\)\.$/.test(t))"
LOGGED = "(start) => [...document.querySelectorAll('#log li span')].some((e) => e.textContent.startsWith(start))"


def mock(port, path, body=None):  # a route of the mock ComfyUI: a GET, or a POST of `body`
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as r:
        return json.load(r)


def run(browser, port, U):
    address = f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html"
    mock(port, "/mock/card", {"vram": 17.2e9, "ram": 65.5e9})  # what a 16 GB card in a 64 GB machine reports: the reference laptop
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(address)  # the blank plate opens at start
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    for start in ("Memory profile", "ingest "):
        page.wait_for_function(LOGGED, arg=start, timeout=20000)
    log = page.eval_on_selector_all("#log li span", "els => els.map((e) => e.textContent)")
    profile = [t for t in log if "Memory profile" in t]
    U.check(profile == [PROFILE], f"the memory profile is one entry: the card in GB (bytes / 2**30), then what the page does on it: {profile}")
    ingest = [t for t in log if t.startswith("ingest")]
    U.check(len(ingest) == 1 and JOB.match(ingest[0]) is not None, f"a job writes one line, when it ends: {ingest}")
    old = [t for t in log if any(g in t for g in GONE)]
    U.check(not old, f"no line for a post, a start or a node that runs, and none of its own for the blank plate: {old}")
    posts = [p["outputs"] for p in mock(port, "/mock/posts")]
    U.check(len(posts) == 1, f"a card under 24 GB: no model loads at page open, so the blank plate's ingest is the only post: {posts}")
    page.close()

    before = len(mock(port, "/mock/posts"))
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(address + "?blank=0")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden", timeout=60000)
    page.evaluate(U.WATCH)
    page.keyboard.press("p")
    U.paint_once(page, "a lantern", [(0.3, 0.5), (0.34, 0.56)])
    page.keyboard.press("Enter")
    U.wait_log(page, SHOT, 120000, "the preview shot's line, with the previews the page received")
    ltx = [p["live"] for p in mock(port, "/mock/posts")[before:] if p["live"] is not None]
    U.check(len(ltx) >= 1 and all(every == 2 for every in ltx), f"a card under 24 GB: every LTX pass asks for its live previews, every other step: {ltx}")
    jobs = [t for t in page.evaluate("window.__lines") if re.match(r"^[a-z]+ [0-9a-f?]{1,8}: ", t)]
    done = [t.split(":")[0] for t in jobs if ": done in" in t]
    U.check(len(done) >= 3 and len(set(done)) == len(done) and all(LINE.match(t) for t in jobs),
            f"through an edit and its preview shot, a job that ended wrote one line: {jobs}")

    # One family of models in memory at a time on a card under 24 GB: ComfyUI's memory is freed before the shot, whose
    # models are not the edit's, and again before the tracking job that follows it
    U.wait_log(page, r"window.__lines.some((t) => /^matte [0-9a-f]{8}: done in /.test(t))", 120000, "the line of the tracking job that follows the preview shot")
    lines = page.evaluate("window.__lines")
    freed = [t.split(":")[0].removeprefix("Memory freed before ") for t in lines if t.startswith("Memory freed before ")]
    at = lambda start: next((i for i, t in enumerate(lines) if t.startswith(start)), -1)  # noqa: E731
    U.check(freed.count("shot") == 1 and freed.count("matte") == 1 and 0 <= at("Memory freed before shot:") < at("shot ") < at("Memory freed before matte:") < at("matte "),
            f"a card under 24 GB holds one family of models at a time: memory freed before {freed}")
    page.close()
