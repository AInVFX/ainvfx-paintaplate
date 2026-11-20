"""Preview: a new session opens on Latent preview. A choice holds for the session, through a reload, and a new tab of the
same browser opens on Latent preview again. A scene neither saves the choice nor changes it, even one that holds a value,
as older pages saved it."""
import json
import urllib.request


def run(browser, port, U):
    errors = []
    context = browser.new_context(viewport=U.VIEWPORT)  # one browser profile, so a new tab shares what the browser keeps

    def tab():  # a new tab: a new session, with no choice stored for it
        page = context.new_page()
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.goto(U.PAGE.format(port=port, query="?blank=0"))
        page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
        U.open_plate(page)
        return page

    page = tab()
    U.check(page.input_value("#preview-size") == "latent", f"a new session opens on Latent preview: {page.input_value('#preview-size')}")
    page.select_option("#preview-size", "4")
    page.reload()
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    U.open_plate(page)
    U.check(page.input_value("#preview-size") == "4", f"Quarter size holds through a reload, in the same session: {page.input_value('#preview-size')}")
    name, scene = U.save_scene(page)
    U.check("preview" not in scene, f"Save scene keeps no Preview choice: {sorted(scene)}")
    scene["preview"] = 2  # as an older page saved it
    base = page.url.split("/extensions/")[0]
    urllib.request.urlopen(urllib.request.Request(f"{base}/paintaplate/scenes/{name}", data=json.dumps(scene).encode(), headers={"Content-Type": "application/json"}), timeout=10)

    page = tab()
    U.check(page.input_value("#preview-size") == "latent", f"a new tab of the same browser opens on Latent preview: {page.input_value('#preview-size')}")
    U.open_scene(page, name)
    page.wait_for_function("[...document.querySelectorAll('#log li span')].some((e) => e.textContent.startsWith('Scene opened'))", timeout=60000)
    U.check(page.input_value("#preview-size") == "latent", f"a scene that holds a Preview value opens on the session's choice: {page.input_value('#preview-size')}")
    U.no_errors(errors, "in the two sessions")
    context.close()
