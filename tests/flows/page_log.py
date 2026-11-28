"""The check of the log's export (tests/flows/README.md). The small button beside the log downloads
<plate or scene>_log_<YYYYMMDD_HHMM>.txt: the pack's version and build, the machine that ComfyUI reports, the page,
the plate, then the log with its times. Its title says what the file holds."""
import re


def run(browser, port, U):
    page = U.load(browser, port, accept_downloads=True)
    U.open_plate(page)
    with page.expect_download() as info:
        page.click("#log-export")
    got = info.value
    with open(got.path(), encoding="utf-8") as f:
        text = f.read()
    U.check(re.fullmatch(r"desk_log_\d{8}_\d{4}\.txt", got.suggested_filename) is not None, f"the file's name: {got.suggested_filename}")
    U.check(text.startswith("AInVFX Paint a plate ") and "\n  GPU 0: mock, " in text and "\nLog\n" in text and re.search(r"\n\S.*  Plate desk: opened in", text) is not None,
            f"the file holds the version, the machine, then the log with its times: {text[:160]!r}")
    U.check("It contains only the log, " in (page.get_attribute("#log-export", "title") or ""), "the button's title says what the file holds")
    page.close()
