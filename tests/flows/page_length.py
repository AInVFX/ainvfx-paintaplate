"""A plate opens with up to LTX 2.5's 20 s at its frame rate, and no more frames than the machine's RAM holds (tests/flows/
README.md). The Open dialog says so before a longer plate opens; once open, the plate's line and the log name the frames
left out and why, and the status line shows the warning with the next step. A plate within 20 s opens whole, with no warning, whatever its length and frame rate. The Blank plate tab shows the
values its plate uses once a field is left, its note says which changed, its frames go up to 20 s at the rate chosen, and
the server refuses a frame rate or a length that the tab never offers."""
import json
import os
import sys

import av
import numpy as np

SHOWN = "document.querySelector('#open').open"


def plate(name, frames, fps, size=(64, 32)):  # a small movie in the mock ComfyUI's input folder: ui_mock.py runs each flow with --root <its folder>
    path = os.path.join(os.path.abspath(sys.argv[sys.argv.index("--root") + 1]), "input", "plates", name)
    with av.open(path, "w") as c:
        s = c.add_stream("libx264", rate=fps)
        s.width, s.height, s.pix_fmt = size[0], size[1], "yuv420p"
        for i in range(frames):
            for packet in s.encode(av.VideoFrame.from_ndarray(np.full((size[1], size[0], 3), i % 256, np.uint8), format="rgb24")):
                c.mux(packet)
        for packet in s.encode():
            c.mux(packet)
    return f"plates/{name}"


def run(browser, port, U):
    long, mid = plate("long_50fps.mp4", 1250, 50), plate("mid_30fps.mp4", 200, 30)
    page = U.load(browser, port)
    posted = []
    page.on("request", lambda req: posted.append(req.post_data or "") if req.method == "POST" and req.url.endswith("/prompt") else None)
    page.click("#open-btn"); page.click("#open [data-tab=files]")
    item = f"#browse .item[data-path='{long}']"
    U.check(U.poll(page, lambda: page.query_selector(item) is not None, 15), "the input folder lists the 1250-frame plate")
    page.click(item)
    U.check(U.poll(page, lambda: "1,250 frames at 50 fps" in page.text_content("#browse-info") and "Opens frames 1 to 1001: LTX 2.5 makes shots of up to 20 s, 1,001 frames at 50 fps." in page.text_content("#browse-info"), 10),
            f"before it opens, the dialog says how many frames open: {page.text_content('#browse-info')!r}")
    page.dblclick(item)
    U.check(U.until(page, "document.querySelector('#spec').textContent.includes('1,001 of 1,250 frames')", 60000),
            f"once open, the plate's line says 1,001 of its 1,250 frames: {page.text_content('#spec')!r}")
    loads = [n["inputs"] for b in posted if b for n in json.loads(b)["prompt"].values()
             if n.get("class_type") == "PaintAPlate_LoadPlate" and n["inputs"].get("path") == long]
    U.check(bool(loads) and loads[0].get("max_frames") == 1001, f"the plate's ingest asks Load Plate for 1001 frames: {[x.get('max_frames') for x in loads]}")
    U.check("Warning: plate long_50fps: 1,001 of its 1,250 frames opened.\n  Frames 1002 to 1250 are left out: LTX 2.5 makes shots of up to 20 s, 1,001 frames at 50 fps."
            in "\n".join(U.log_lines(page)), "the log names the frames left out, and why")
    U.check(U.poll(page, lambda: page.text_content("#status").startswith("Warning: plate long_50fps: 1,001 of its 1,250 frames opened. Describe the edit in the text prompt, paint on the frame, then Generate."), 5),
            f"the status line shows the warning, then the next step: {page.text_content('#status')!r}")
    U.open_path(page, mid)
    U.check(U.until(page, "document.querySelector('#spec').textContent.startsWith('mid_30fps') && document.querySelector('#spec').textContent.includes(', 200 frames,')", 60000),
            f"a plate within 20 s opens whole: {page.text_content('#spec')!r}")
    U.check(not [t for t in U.log_lines(page) if t.startswith("Warning: plate mid_30fps")], "a plate within 20 s opens with no warning, at 200 frames and 30 fps")
    broken = "plates/broken.mp4"  # bytes that are no movie: the server cannot read its size, rate or frames
    with open(os.path.join(os.path.abspath(sys.argv[sys.argv.index("--root") + 1]), "input", broken), "wb") as f:
        f.write(b"not a movie" * 100)
    before = len(posted)
    page.click("#open-btn"); page.click("#open [data-tab=files]")
    item = f"#browse .item[data-path='{broken}']"
    U.check(U.poll(page, lambda: page.query_selector(item) is not None, 15), "the input folder lists the broken file")
    page.dblclick(item)
    U.check(U.poll(page, lambda: page.text_content("#status").startswith("Error: "), 10), f"a file the server cannot read stops the open with its line: {page.text_content('#status')!r}")
    U.check(not [b for b in posted[before:] if broken in b], "and no job reads it: no frames open at a guessed rate")
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.fill("#b-width", "5000")
    U.check("Width set to 1920 px, the largest." in page.text_content("#b-note") and page.input_value("#b-width") == "5000",
            f"while the person types, the note says which value the plate takes: {page.text_content('#b-note')!r}")
    page.press("#b-width", "Tab")
    page.fill("#b-frames", "2000"); page.press("#b-frames", "Tab")
    U.check(page.input_value("#b-width") == "1920" and page.input_value("#b-frames") == "497" and "Frames set to 497, the most at 25 fps (20 s)." in page.text_content("#b-note"),
            f"a field left shows the value the plate uses, and the note says why: {page.input_value('#b-width')}, {page.input_value('#b-frames')}, {page.text_content('#b-note')!r}")
    page.select_option("#b-fps", "50"); page.fill("#b-frames", "2000"); page.press("#b-frames", "Tab")
    U.check(page.get_attribute("#b-frames", "max") == "1001" and page.input_value("#b-frames") == "1001",
            f"at 50 fps the frames go up to 20 s, 1001: max {page.get_attribute('#b-frames', 'max')}, field {page.input_value('#b-frames')}")
    page.click("#open menu button[value=cancel]")
    post = """(body) => fetch('/paintaplate/blank', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body) }).then(async (r) => [r.status, await r.text()])"""
    refused = page.evaluate(post, {"width": 256, "height": 256, "fps": 30, "frames": 9})
    U.check(refused == [400, "Blank plate: frame rate must be 24, 25 or 50 fps."], f"the server refuses a frame rate the tab never offers: {refused}")
    refused = page.evaluate(post, {"width": 256, "height": 256, "fps": 25, "frames": 505})
    U.check(refused == [400, "Blank plate: length must be 8k + 1 frames, from 9 to 497 at 25 fps."], f"and a length past 20 s at its rate: {refused}")
    page.close()
    # a 16 GB GPU with 16 GB of RAM: the plate opens with what this machine holds at its size, and every line says so
    wide = plate("wide_50fps.mp4", 1250, 50, (320, 180))
    U.mock_route(port, "/mock/card", {"vram": 17.2e9, "ram": 16 * 2 ** 30})
    page = U.load(browser, port)
    posted.clear()
    page.on("request", lambda req: posted.append(req.post_data or "") if req.method == "POST" and req.url.endswith("/prompt") else None)
    page.click("#open-btn"); page.click("#open [data-tab=files]")
    item = f"#browse .item[data-path='{wide}']"
    U.check(U.poll(page, lambda: page.query_selector(item) is not None, 15), "the input folder lists the 320 x 180 plate")
    page.click(item)
    why = "this machine's 16 GB of RAM holds 425 frames at 320 x 180 through every step"
    U.check(U.poll(page, lambda: f"Opens frames 1 to 425: {why}." in page.text_content("#browse-info"), 10),
            f"before it opens, the dialog says how many frames this machine holds: {page.text_content('#browse-info')!r}")
    page.dblclick(item)
    U.check(U.until(page, "document.querySelector('#spec').textContent.includes('425 of 1,250 frames')", 60000), f"the plate's line: {page.text_content('#spec')!r}")
    loads = [n["inputs"] for b in posted if b for n in json.loads(b)["prompt"].values()
             if n.get("class_type") == "PaintAPlate_LoadPlate" and n["inputs"].get("path") == wide]
    U.check(bool(loads) and loads[0].get("max_frames") == 425, f"Load Plate is asked for 425 frames: {[x.get('max_frames') for x in loads]}")
    U.check(f"Warning: plate wide_50fps: 425 of its 1,250 frames opened.\n  Frames 426 to 1250 are left out: {why}." in "\n".join(U.log_lines(page)),
            "the log names the frames left out, and the machine's RAM as the reason")
    page.close()
