"""Save scene asks before it replaces. When a scene of the plate's name is saved already, the page offers a free name in
a field, with two buttons that say what they do: « Save as desk_2 » and « Yes, replace it ». The first button follows the
field, Esc saves nothing, and a name typed over another saved scene asks again."""
import json
import urllib.request

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
SAVED = "[...document.querySelectorAll('#log li span')].filter((e) => /^Scene \\S+ saved[.:]/.test(e.textContent)).map((e) => e.textContent)"
ASKED = "document.querySelector('#ask').open"


def scenes(page):  # the scenes saved on this ComfyUI, by name, with their times
    base = page.url.split("/extensions/")[0]
    return {s["name"]: s["mtime"] for s in json.loads(urllib.request.urlopen(f"{base}/paintaplate/scenes").read())}


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    U.save_scene(page)
    first = scenes(page)
    U.check(list(first) == ["desk"] and not page.evaluate(ASKED), f"the first save asks nothing: {list(first)}")

    page.click("#save-btn")
    page.wait_for_function(ASKED, timeout=10000)
    shown = [page.text_content("#ask-text"), page.input_value("#ask-field"), page.text_content("#ask-yes"), page.text_content("#ask-no")]
    U.check(shown == ["A scene named desk exists.", "desk_2", "Save as desk_2", "Yes, replace it"], f"a second save asks, with a free name: {shown}")
    page.fill("#ask-field", "desk take")
    U.check(page.text_content("#ask-yes") == "Save as desk_take", f"the first button follows the field: {page.text_content('#ask-yes')!r}")
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    U.check(scenes(page) == first, "Esc saves nothing")

    n = len(page.evaluate(SAVED))
    page.click("#save-btn")
    page.wait_for_function(ASKED, timeout=10000)
    page.click("#ask-yes")
    page.wait_for_function(f"{SAVED}.length > {n}", timeout=10000)
    now = scenes(page)
    U.check(sorted(now) == ["desk", "desk_2"] and now["desk"] == first["desk"], f"Save as desk_2 leaves desk as it was: {sorted(now)}")

    page.click("#save-btn")
    page.wait_for_function(ASKED, timeout=10000)
    U.check(page.input_value("#ask-field") == "desk_3", f"the next free name: {page.input_value('#ask-field')!r}")
    page.fill("#ask-field", "desk_2")
    page.click("#ask-yes")
    page.wait_for_function(f"{ASKED} && document.querySelector('#ask-text').textContent === 'A scene named desk_2 exists.'", timeout=10000)
    n = len(page.evaluate(SAVED))
    page.click("#ask-no")
    page.wait_for_function(f"{SAVED}.length > {n}", timeout=10000)
    U.check(page.evaluate(SAVED)[-1].startswith("Scene desk_2 saved") and sorted(scenes(page)) == ["desk", "desk_2"],
            "a name typed over another saved scene asks again, and Yes, replace it replaces it")
    U.no_errors(errors, "when Save scene asks")
    page.close()
