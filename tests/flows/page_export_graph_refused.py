"""Export with « ComfyUI graph » ticked on a ComfyUI that does not write the graph, as after an update of the pack with no
restart of ComfyUI: the zip downloads with the other files, the log says so once as a warning, and the status line adds
what to do."""
import zipfile
import zip_rows  # noqa: E402

FACT = "Warning: the ComfyUI graph was not written. The zip holds the other files."
TODO = "Restart ComfyUI after an update of Paint a plate, then export again."


def run(browser, port, U):
    page = U.load(browser, port)
    page.route("**/paintaplate/graph?*", lambda route: route.fulfill(status=405, body="405: Method Not Allowed"))  # a ComfyUI that runs the pack's older routes
    U.open_plate(page)
    page.click('.tools [data-tool="paint"]')
    U.paint_once(page, "a lantern", [(0.3, 0.5), (0.36, 0.5)]); page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    page.click("#export-btn"); page.check("#x-graph"); page.check("#x-matte")
    with page.expect_download(timeout=180000) as dl:
        page.click("#x-go")
    names = zipfile.ZipFile(dl.value.path()).namelist()
    U.check(not zip_rows.files(names, "comfyui_graph") and zip_rows.composite(names) and zip_rows.files(names, "matte"),
            f"the zip downloads with the other files: {sorted({n.split('/')[0] for n in names})}")
    U.check(U.poll(page, lambda: FACT in U.log_lines(page)) and U.log_lines(page).count(FACT) == 1,
            f"the log says once that the graph was not written: {[t for t in U.log_lines(page) if 'graph' in t]}")
    U.check(page.eval_on_selector_all("#log li", "(els, fact) => els.filter((e) => e.querySelector('span').textContent === fact).map((e) => e.className)", FACT) == ["warn"],
            "as a warning, in amber")
    U.check(page.text_content("#status") == f"{FACT} {TODO}", f"the status line adds what to do: {page.text_content('#status')!r}")
    page.close()
