"""The page workstream's check of a stop that lands between two jobs (tests/flows/README.md). A render step uploads its
images, then posts its job. A stop cancels the jobs that exist, and the step that still uploads has none. The mock holds
that upload open (/mock/slow), Stop is pressed, then the upload goes on (/mock/release): the step ends there, no job is
posted until Enter, and Enter goes on from that step."""
import re

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
TRACKED = "window.__lines.some((t) => /^matte [0-9a-f]{8}: done in /.test(t))"


def run(browser, port, U):
    posts = lambda: [p["outputs"] for p in U.mock_route(port, "/mock/posts")]  # noqa: E731
    page = U.load(browser, port)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    page.evaluate(U.WATCH)
    U.mock_route(port, "/mock/hold", {"slot": "hero", "seconds": 4})  # the preview shot lasts 4 s at any --speed: time to arm the upload that follows it
    page.keyboard.press("p")
    U.paint_once(page, "a lantern", [(0.3, 0.5), (0.34, 0.56)])
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Shot, preview (about"), 60000, "start of the preview shot")
    U.mock_route(port, "/mock/slow", {"seconds": 120, "times": 1})  # the next upload is the tracking step's: it waits for /mock/release
    held = lambda: any(e[0] == "slow upload" for e in U.mock_route(port, "/mock/events"))  # noqa: E731
    U.check(U.poll(page, held, 60) and not any(re.match(r"^matte [0-9a-f?]{1,8}: ", t) for t in page.evaluate("window.__lines")),
            "the tracking step waits for its upload, which the mock holds: it has posted no job yet")

    page.click("#stop")
    U.wait_log(page, U.added_line("Stopped: what finished is kept"), 10000, "line of the stop")
    before = posts()
    U.check(not page.is_hidden("#stop"), "under the stop the step still waits for its upload, and Stop stays on show")
    U.mock_route(port, "/mock/release", {})
    U.poll(page, lambda: page.is_hidden("#stop") or posts() != before, 30)  # the step has ended, or a job came
    U.check(page.is_hidden("#stop") and posts() == before,
            f"a stop that lands while a render step uploads its images ends the step, and no job is posted until Enter: posted since the stop: {posts()[len(before):]}")

    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("Enter")
    U.wait_log(page, TRACKED, 120000, "line of the tracking job after Enter")
    U.check(len(posts()) > len(before), f"Enter goes on from the step that stopped: the tracking job is posted and ends ({posts()[len(before):][:1]})")
    page.close()
