"""The page workstream's check of the job index across versions of the pack (tests/flows/README.md). A job made before
with the same inputs is taken from the job index, not run again. The pack's version is part of the key: after an update,
a result made by the version before never comes back as the new version's, and each version finds its own results again.
The mock answers another version on request (/mock/version), as a ComfyUI restarted after an update of the pack would."""
import time

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
TAKEN = "ingest: made before with the same inputs, taken from the job index"


def run(browser, port, U):
    ingests = lambda: sum("spec" in p["outputs"] for p in U.mock_route(port, "/mock/posts"))  # noqa: E731

    def opened():  # a new page with the test plate open: the version it shows, and whether its ingest came from the job index
        page = U.load(browser, port)
        U.open_path(page, "plates/desk.mp4")
        page.wait_for_function(OPEN, timeout=60000)
        lines = page.eval_on_selector_all("#log li span", "els => els.map((e) => e.textContent)")
        version = page.text_content("#version")
        page.close()
        return version, any(TAKEN in line for line in lines)

    first, _ = opened()  # the index holds this version's ingest from here on
    made = ingests()
    same, taken = opened()
    U.check(same == first and taken and ingests() == made, f"version {first} again: the ingest is taken from the job index, and nothing is posted")
    update = f"0.0.{int(time.time())}"  # a version no index has seen
    U.mock_route(port, "/mock/version", {"version": update})
    other, taken = opened()
    U.check(other == update and not taken and ingests() == made + 1,
            f"another version of the pack ({other}): the result of {first} does not come back, and the ingest runs again ({ingests() - made} posted)")
    again, taken = opened()
    U.check(again == update and taken and ingests() == made + 1, f"{update} again: it takes its own result from the index")
    U.mock_route(port, "/mock/version", {"version": first})
    back, taken = opened()
    U.check(back == first and taken and ingests() == made + 1, f"back on {first}: its own result is still in the index, and nothing is posted")
