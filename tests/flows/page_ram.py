"""The page workstream's check of the RAM-short rule (tests/flows/README.md). A card of 24 GB or more keeps its models
loaded. At a change of model family the page reads the free RAM in ComfyUI's /system_stats, and it frees ComfyUI's memory
only when that is less than the next job's frames can take (logic.framesNeed). The log's line names that reason. The mock
ComfyUI takes the free RAM at /mock/card, and /mock/events lists each /free the page posted."""
import re

CARD = {"vram": 32e9, "ram": 256e9}  # a 32 GB card: the medium profile, which keeps its models loaded
ROOM, SHORT = 200e9, 1e9  # bytes of free RAM: far over and far under what the frames of the 1280 x 704 plate can take, whatever logic.RAM_COPIES is
LOGGED = "(start) => [...document.querySelectorAll('#log li span')].some((e) => e.textContent.startsWith(start))"
OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
TRACKED = re.compile(r"^matte [0-9a-f]{8}: done in ")  # the line of the tracking job that follows the preview shot
FREED = "ComfyUI's memory freed first"
WHY = re.compile(r"^[a-z]+: ComfyUI's memory freed first: 1 GB of RAM are free, and this job's frames can take \d+ GB$")


def edit(browser, port, U, free, words, pts):
    """A paint edit on the 32 GB card with `free` bytes of RAM free, through its preview shot and the tracking job after it.
    Returns the log's lines up to the tracking job's, and how many times the page asked ComfyUI to free its memory."""
    U.mock_route(port, "/mock/card", {**CARD, "ram_free": free})  # before the page loads: every job of this edit meets the same free RAM
    asked = lambda: sum(e[0] == "free" for e in U.mock_route(port, "/mock/events"))  # noqa: E731
    before = asked()
    page = U.load(browser, port)
    U.check(U.until(page, LOGGED, 20000, "Memory profile medium:"),
            f"a 32 GB card takes the medium profile, which keeps its models loaded ({round(free / 2 ** 30)} GB of RAM free)")
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    page.evaluate(U.WATCH)
    page.keyboard.press("p")
    U.paint_once(page, words, pts)
    page.keyboard.press("Enter")
    U.wait_log(page, "window.__lines.some((t) => /^matte [0-9a-f]{8}: done in /.test(t))", 120000, "the line of the tracking job that follows the preview shot")
    lines, frees = page.evaluate("window.__lines"), asked() - before
    page.close()
    return lines[:next(i for i, t in enumerate(lines) if TRACKED.match(t)) + 1], frees


def run(browser, port, U):
    lines, frees = edit(browser, port, U, ROOM, "a lantern", [(0.3, 0.5), (0.34, 0.56)])
    ran = [t.split(" ")[0] for t in lines if re.match(r"^[a-z]+ [0-9a-f]{8}: done in ", t)]
    said = [t for t in lines if FREED in t]
    U.check("shot" in ran and "matte" in ran and not said and frees == 0,
            f"with room in RAM for the job's frames, a change of model family frees nothing: the jobs {ran} ran, the log's free lines are {said}, and /free was posted {frees} times")

    lines, frees = edit(browser, port, U, SHORT, "a red kite", [(0.6, 0.4), (0.64, 0.46)])
    said = [t for t in lines if FREED in t]
    freed = [t.split(":")[0] for t in said]
    at = lambda start: next((i for i, t in enumerate(lines) if t.startswith(start)), -1)  # noqa: E731
    U.check(freed.count("shot") == 1 and freed.count("matte") == 1 and frees >= len(said)
            and 0 <= at(f"shot: {FREED}") < at("shot ") < at(f"matte: {FREED}") < at("matte "),
            f"with RAM short, the page frees ComfyUI's memory at a change of model family, once before the preview shot and once before its tracking job: freed before {freed}, /free posted {frees} times")
    U.check(all(WHY.match(t) for t in said),
            f"the log's line names the reason that applied, the free RAM against what the job's frames can take: {said}")
