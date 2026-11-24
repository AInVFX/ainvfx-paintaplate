"""Export's zip names every file after the plate, or after the scene once it is saved, and after its row in the dialog. A
movie plate with every row ticked gives its composite and its shot at the top, its matte's frames in matte/, its graph and
its models' list, all named desk_..., and no layer, in desk_v1.zip. A blank plate's scene saved as « smoke » names its fluid
shot's files smoke_..., in smoke_fluid_v1.zip."""
import zipfile

import zip_rows


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)  # plates/desk.mp4
    page.click('.tools [data-tool="paint"]')
    U.paint_once(page, "a lantern", [(0.3, 0.5), (0.36, 0.5)]); page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    page.click("#export-btn")
    for box in ("#x-matte", "#x-shot", "#x-graph"):
        page.check(box)
    with page.expect_download(timeout=180000) as dl:
        page.click("#x-go")
    names = zipfile.ZipFile(dl.value.path()).namelist()
    rows = {zip_rows.row_of(n) for n in names}
    U.check(dl.value.suggested_filename == "desk_v1.zip" and all(n.rsplit("/", 1)[-1].startswith("desk_") for n in names),
            f"the zip and every file in it start with the plate's name: {dl.value.suggested_filename}, {names[:3]}")
    U.check(rows == {"composite_full_size", "matte", "shot_full_size", "comfyui_graph", "models"} and "matte/desk_matte_00001_.png" in names
            and not any("layer" in n for n in names), f"each file takes its row's name, frames sit in their row's folder, and no layer: {sorted(rows)}")
    page.click("#open-btn"); page.click("#open [data-tab=blank]")  # a blank plate, saved as a scene
    page.fill("#b-frames", "17"); page.dispatch_event("#b-frames", "input")
    page.evaluate(U.WATCH)
    page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    U.paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("under the edits: the fluid shot v"), 240000, "the fluid shot")
    page.click("#save-btn")
    page.wait_for_selector("#ask-field", state="visible", timeout=10000)
    page.fill("#ask-field", "smoke"); page.click("#ask-yes")
    U.wait_log(page, U.added_line("Scene smoke saved"), 20000, "the save")
    page.click("#export-btn")
    with page.expect_download(timeout=180000) as dl:
        page.click("#x-go")
    names = zipfile.ZipFile(dl.value.path()).namelist()
    U.check(dl.value.suggested_filename == "smoke_fluid_v1.zip" and names and all(n.rsplit("/", 1)[-1].startswith("smoke_") for n in names)
            and zip_rows.files(names, "fluid_shot"), f"a saved scene names its export after itself: {dl.value.suggested_filename}, {names}")
    U.no_errors(errors, "after the two exports")
    page.close()
