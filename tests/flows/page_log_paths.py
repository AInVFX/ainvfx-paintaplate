"""The log's export holds no path of the person's machine. After Save scene, the status line and the Log panel give the
scene file's full path. The downloaded log gives it by its last two parts when the server gives no folder, as this
mock's, and from ComfyUI's folder when /paintaplate/version gives one."""
import re

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
ABSOLUTE = re.compile(r"(^|[\s\"'«(=])(/|[A-Za-z]:[\\/]|\\\\)\w", re.M)


def exported(page):
    with page.expect_download() as info:
        page.click("#log-export")
    with open(info.value.path(), encoding="utf-8") as f:
        return f.read()


def absolute_in(text):
    found = ABSOLUTE.search(text)
    return text[max(0, found.start() - 60):found.end() + 60] if found else ""


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors, accept_downloads=True)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    page.click("#save-btn")
    U.check(U.poll(page, lambda: " saved: " in page.text_content("#status"), 10), f"Save scene saves the scene: {page.text_content('#status')!r}")
    status = page.text_content("#status")
    m = re.search(r"Scene (\S+) saved: (\S+)\.(?:\s|$)", status)  # then what to do, on the status line only
    U.check(m is not None and ABSOLUTE.search(" " + m[2]) is not None and m[2].endswith(f"/output/paintaplate/scenes/{m[1]}.paintaplate.json"),
            f"the status line gives the scene file's full path: {status!r}")
    U.check(f"Scene {m[1]} saved: {m[2]}." in page.text_content("#log"), "the Log panel holds the same fact, full path included")

    text = exported(page)
    U.check(f" Scene {m[1]} saved: scenes/{m[1]}.paintaplate.json.\n" in text, "with no folder from the server, the exported log names the scene file by its last two parts")
    U.check(not absolute_in(text), f"the exported log holds no absolute path: {absolute_in(text)!r}")

    folder = m[2][: m[2].rindex("/output/")]

    def with_folder(route):  # /paintaplate/version as a ComfyUI whose folder holds this mock's output folder
        answer = route.fetch()
        route.fulfill(response=answer, json={**answer.json(), "folder": folder})

    page.route("**/paintaplate/version", with_folder)
    text = exported(page)
    U.check(f" Scene {m[1]} saved: output/paintaplate/scenes/{m[1]}.paintaplate.json.\n" in text,
            "with ComfyUI's folder from the server, the exported log names the scene file from that folder")
    U.check(not absolute_in(text), f"the exported log holds no absolute path: {absolute_in(text)!r}")
    U.no_errors(errors, "after Save scene and two exports of the log")
    page.close()
