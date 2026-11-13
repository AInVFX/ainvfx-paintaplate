"""The check of the job index across builds (tests/flows/README.md; the render workstream's in wave 5). A job made before
with the same inputs is taken from the job index, not run again. The key holds the server's build, a hash of what computes
made when ComfyUI starts (routes.build_parts), in place of the pack's version: a result made by other code never comes back,
each build finds its own results again, and a new version number alone changes nothing. The mock answers another build or
version on request (/mock/version) and drops its WebSockets, as a ComfyUI restarted on other code would: a page left open
reads the build again when it connects again, asks for a reload, and keeps no job index until then."""
import time

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
TAKEN = "ingest: made before with the same inputs, taken from the job index"
ASKED = "ComfyUI restarted with other code or model files"


def run(browser, port, U):
    ingests = lambda: sum("spec" in p["outputs"] for p in U.mock_route(port, "/mock/posts"))  # noqa: E731
    start = U.mock_route(port, "/paintaplate/version")  # {"version", "build"}
    first, other = start["build"], f"{int(time.time()):016x}"  # `other`: a build no index has seen

    def opened(keep=False):  # a new page with the test plate open: whether its ingest came from the job index
        page = U.load(browser, port)
        U.open_path(page, "plates/desk.mp4")
        page.wait_for_function(OPEN, timeout=60000)
        taken = any(TAKEN in line for line in U.log_lines(page))
        return page if keep else page.close() or taken

    opened()  # the index holds this build's ingest from here on
    made = ingests()
    U.check(opened() and ingests() == made, f"build {first[:8]} again: the ingest is taken from the job index, and nothing is posted")
    U.mock_route(port, "/mock/version", {"build": other})
    U.check(not opened() and ingests() == made + 1, "another build of the same version (a branch, a local edit, a new model file): "
            "the result does not come back, and the ingest runs again")
    U.check(opened() and ingests() == made + 1, "the other build again: it takes its own result from the index")
    U.mock_route(port, "/mock/version", {"build": first})
    U.check(opened() and ingests() == made + 1, f"back on {first[:8]}: its own result is still in the index, and nothing is posted")
    U.mock_route(port, "/mock/version", {"version": "0.0.1"})
    U.check(opened() and ingests() == made + 1, "a new version number on the same build: nothing that computes changed, the result comes back")
    U.mock_route(port, "/mock/version", {"version": start["version"]})
    page = opened(keep=True)  # left open while ComfyUI restarts on other code
    U.mock_route(port, "/mock/version", {"build": other})
    page.wait_for_function(f"[...document.querySelectorAll('#log li span')].some((e) => e.textContent.startsWith({ASKED!r}))", timeout=20000)
    U.check("Reload this page" in page.text_content("#status") and sum(ASKED in t for t in U.log_lines(page)) == 1,
            "a page left open while ComfyUI restarts on another build asks for a reload, once")
    page.close()
    U.mock_route(port, "/mock/version", {"build": first})
