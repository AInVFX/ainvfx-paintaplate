"""SDR to HDR on a plate with no edit (logic.plateAlone). On desk.mp4,
whose format holds nothing above 1.0, Finish > SDR to HDR turns it on and starts nothing: Generate starts it. The Render
panel shows one step, SDR to HDR, with no Edited first frame row, and the job takes the plate itself, with the plate's size for
HDR Match. Once it is done, the player shows its EXR frames at full precision, and Export downloads them as they are:
half-float EXR frames at the plate's size, with the models behind them in the models' list. Turned off, the plate has nothing to
export; turned on again, the result shows at once."""
import json
import os
import sys
import tempfile
import zipfile
import zip_rows  # noqa: E402


def frame_size(path):  # (height, width) of an EXR frame, read by the pack's own reader
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    import plateio
    return plateio.read_float(path).shape[:2]


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    posted = []
    page.on("request", lambda req: posted.append(req.post_data) if req.method == "POST" and req.url.endswith("/prompt") else None)
    U.open_plate(page)
    rows = lambda: page.eval_on_selector_all("#stages li .name", "els => els.map((e) => e.textContent)") if page.is_visible("#stages") else []  # noqa: E731
    U.check(page.is_disabled("#generate") and page.is_disabled("#export-btn") and not rows(),
            "a plate with no edit: Generate and Export wait, and the Render panel shows no step")
    page.click("#finish-btn")
    page.click("#finish-hdr")
    page.click("#finish-hdr-yes")
    page.keyboard.press("Escape")
    status = page.text_content("#status") or ""
    U.check(status.startswith("Finish: SDR to HDR on. Generate runs it on the plate: about ") and status.endswith(" s."),
            f"the status line says what starts it, with its time: {status!r}")
    live = U.until(page, "!document.querySelector('#generate').disabled && !document.querySelector('#export-btn').disabled", 5000)
    U.check(live and rows() == ["SDR to HDR"], f"Generate and Export are live, and the Render panel shows one step: {rows()}, "
            f"Generate {'live' if page.is_enabled('#generate') else 'off'}, Export {'live' if page.is_enabled('#export-btn') else 'off'}")
    page.wait_for_timeout(1000)
    U.check(not any("SDR to HDR: about" in t for t in U.log_lines(page)), "turning it on starts nothing: Generate does")
    page.click("#generate")
    U.wait_log(page, "[...document.querySelectorAll('#log li span')].some((e) => /Render v\\d+: SDR to HDR: done in/.test(e.textContent))",
               120000, "SDR to HDR on the plate")
    jobs = [json.loads(b)["prompt"] for b in posted if b and '"PaintAPlate_HDRMatch"' in b]
    nodes = list(jobs[-1].values()) if jobs else []
    load = next((n["inputs"] for n in nodes if n["class_type"] == "PaintAPlate_LoadPlate"), {})
    match = next((n["inputs"] for n in nodes if n["class_type"] == "PaintAPlate_HDRMatch"), {})
    U.check(len(jobs) == 1 and load.get("path") == "plates/desk.mp4" and {"plate", "mask", "hdr"} <= set(match),
            f"one job, on the plate itself, with the plate's size for HDR Match: {len(jobs)} job, {load.get('path')}, {sorted(match)}")
    U.check(rows() == ["SDR to HDR"] and page.query_selector("#stages li.done") is not None and page.is_disabled("#generate"),
            f"its one step is done, and Generate has nothing left to start: {page.text_content('#stages')!r}")
    U.check(U.until(page, "document.querySelector('canvas[data-precision]')?.dataset.precision === 'float'", 60000),
            "the player shows the result's EXR frames at full precision")
    page.click("#export-btn")
    hidden = page.evaluate("['shot', 'layer', 'matte', 'composite'].every((k) => document.querySelector(`#x-${k}`).closest('label').hidden)")
    ticks, note = [k for k in ("plate", "full", "hdr") if page.is_checked(f"#x-{k}")], page.text_content("#x-note") or ""
    U.check(hidden and ticks == ["plate", "hdr"] and note.startswith("The plate in HDR"),
            f"the Export dialog offers the plate, and opens on the plate in HDR: {ticks}, {note!r}")
    with page.expect_download(timeout=60000) as dl:
        page.click("#x-go")
    z = zipfile.ZipFile(dl.value.path())
    names = z.namelist()
    exrs = sorted(zip_rows.files(names, "plate_hdr", (".exr",)))
    listed = "".join(z.read(n).decode() for n in zip_rows.files(names, "models"))
    with tempfile.TemporaryDirectory() as tmp:
        size = frame_size(z.extract(exrs[0], tmp)) if exrs else None
    U.check(len(exrs) == 49 and size == (704, 1280) and "LTX" in listed,
            f"the zip holds the 49 EXR frames at the plate's size, 1280 x 704, and the models behind them: {len(exrs)} frames, {size}, {names[:2]}")
    status = page.text_content("#status") or ""
    said = U.log_lines(page)
    U.check(status.startswith("Download: ") and status.endswith(".zip.") and any(t.startswith("Download: ") and "  Plate, HDR." in t for t in said) and any(
        t.startswith("Export: done, in ComfyUI's output folder.") and "49 half-float EXR frames in ACES2065-1" in t for t in said),
        f"the status line names the zip, and the log what Export wrote and the row the zip holds: {status!r}")
    page.click("#finish-btn")
    page.click("#finish-hdr")
    U.check(not rows() and page.is_disabled("#export-btn") and page.is_disabled("#generate"), "turned off, the plate has no step and nothing to export")
    page.click("#finish-hdr")
    page.click("#finish-hdr-yes")
    page.keyboard.press("Escape")
    U.check(rows() == ["SDR to HDR"] and page.query_selector("#stages li.done") is not None and page.is_disabled("#generate"),
            "turned on again, its result shows at once, with nothing to generate")
    U.check(not errors, f"no console errors: {errors}")
    page.close()
