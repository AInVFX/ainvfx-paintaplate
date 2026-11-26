"""Rule 2: the zip holds what rebuilds the composite. From the zip's own files, plate x (1 - matte) + layer x matte equals
the zip's composite within each format's tolerance, at each stage the export offers: full size, Upscale's set, SDR to HDR's set and
SDR to HDR's set upscaled, each in its folder (logic.setFolder: <run>/hdr, <run>/upscale/<size>/out, under hdr/ for the last). Each element is written as the export writes it: the
composite and the layer by Save Plate's writer (plateio.write_still for a sequence, plateio.VideoWriter for a movie, the
composite keeping the plate's own pixels where the matte shows 0, nothing kept at another size), and the matte as the
export workflow's Save Frames writes it, its format read from web/workflows/export.json. The plate is the source plate's
own files at full size, and Upscale's plate in its set. The zip is the route's (routes.zip_entries, build_zip), and its
files are read back as Load Plate reads them (plateio.read_float, plateio.decode_video).

Tolerances, on values from 0 to 1, over every pixel of every frame:
- a 16-bit PNG sequence: at most 2 of 65535, each element and the matte rounded to 16 bits;
- an 8-bit H.264 movie, whose export is ProRes 4444 XQ: at most 4 of 255, and 0.5 of 255 on average. The composite and the
  layer are encoded at 10 bits in 4:4:4, and the decoder fills in the plate's 4:2:0 colour samples another way than the
  writer's conversion does;
- SDR to HDR's set, and its set upscaled: half-float EXR frames in ACES2065-1, as SDR to HDR's steps write them (Save
  Frames) and as Save Plate writes an EXR set at another size. Their values go above 1.0, so the difference is read
  relative to max(1, the value): at most 2^-9, three half-float roundings of 11 bits each."""
import io
import json
import os
import shutil
import sys
import unittest
import zipfile

import numpy as np

from _env import ROOT

sys.path.insert(0, ROOT)
import mathops  # noqa: E402
import plateio  # noqa: E402
from scipy import ndimage  # noqa: E402
from test_export_source import load_routes  # noqa: E402

av = plateio.av
H, W, N, FPS = 72, 128, 4, 24


def matte_format() -> str:
    """The export's matte format, as its workflow's Save Frames node asks for it (nodes.SaveFrames: « png » by default)."""
    with open(os.path.join(ROOT, "web", "workflows", "export.json"), encoding="utf-8") as f:
        for node in json.load(f).values():
            if node.get("class_type") == "PaintAPlate_SaveFrames" and node.get("_meta", {}).get("output") == "matte":
                return node.get("inputs", {}).get("format", "png")
    raise AssertionError("the export workflow writes no matte")


def matte_png(m: np.ndarray, fmt: str) -> np.ndarray:  # as Save Frames writes a frame (nodes.SaveFrames: png16 rounds, png truncates)
    grey = np.repeat(np.clip(m, 0, 1)[..., None], 3, -1)
    return np.round(grey * 65535.0).astype(np.uint16) if fmt == "png16" else plateio.core_uint8(grey)


def scene():
    """A plate, a layer and a soft matte: a disc whose edge falls off over 14 px, moving one pixel a frame."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    plates, layers, mattes = [], [], []
    for i in range(N):
        plate = np.stack([0.15 + 0.6 * xx / W, 0.2 + 0.5 * yy / H, 0.55 + 0.25 * np.sin((xx + 3 * i) / 7.0)], -1)
        layer = np.stack([0.9 - 0.5 * yy / H, 0.35 + 0.3 * np.cos((yy + xx) / 9.0), 0.2 + 0.4 * xx / W], -1)
        dist = np.hypot(xx - (W / 2 + i), yy - H / 2)
        plates.append(np.clip(plate, 0, 1)); layers.append(np.clip(layer, 0, 1)); mattes.append(np.clip((26.0 - dist) / 14.0, 0, 1))
    return plates, layers, np.stack(mattes).astype(np.float32)


class Rebuild(unittest.TestCase):
    def setUp(self):
        self.routes = load_routes()
        self.out = self.routes.folders.folder_paths.get_output_directory()
        self.run = os.path.join(self.out, f"paintaplate/rebuild{os.getpid()}/v1")
        os.makedirs(self.run, exist_ok=True)
        self.addCleanup(shutil.rmtree, os.path.dirname(self.run), True)

    def plate(self, kind):  # the source plate, and its frames as Load Plate reads them
        plates, _, _ = scene()
        if kind == "frames":
            folder = os.path.join(self.run, "src", "desk")
            os.makedirs(folder, exist_ok=True)
            paths = [os.path.join(folder, f"desk.{1001 + i}.png") for i in range(N)]
            plateio.write_pngs(lambda i: np.round(plates[i] * 65535).astype(np.uint16), paths, workers=1)
            return folder, [plateio.read_float(p) for p in paths]
        path = os.path.join(self.run, "src", "desk.mp4")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with av.open(path, "w") as out:
            st = out.add_stream("libx264", rate=FPS)
            st.width, st.height, st.pix_fmt = W, H, "yuv420p"
            cc = st.codec_context
            cc.color_primaries = cc.color_trc = cc.colorspace = 1
            cc.color_range = 1
            cc.options = {"crf": "18"}
            for i in range(N):
                f = av.VideoFrame.from_ndarray(np.round(plates[i] * 65535).astype(np.uint16), format="rgb48le")
                f = f.reformat(format="yuv420p", dst_colorspace=1, src_color_range=2, dst_color_range=1)
                f.pts = i
                for p in st.encode(f):
                    out.mux(p)
            for p in st.encode(None):
                out.mux(p)
        return path, list(np.asarray(plateio.decode_video(path, N, FPS)[0], np.float32)[:N])

    def page(self, path):  # the page's name for a file or a folder under the output folder
        return f"output:{os.path.relpath(path, self.out)}"

    def save_plate(self, spec, folder, frames, keep=None):  # Save Plate: a sequence by write_still, a movie by VideoWriter
        os.makedirs(folder, exist_ok=True)
        if spec["kind"] != "video":
            for i, f in enumerate(frames):
                plateio.write_still(spec, i, f, None, None if keep is None else keep[i], folder)
            return self.page(folder)
        writer = plateio.VideoWriter(spec, os.path.join(folder, os.path.basename(spec["source"])))
        source = plateio.SourceFrames(spec["source"], writer.pix_fmt) if keep is not None and writer.keeps else None
        for i, f in enumerate(frames):
            writer.write(f, keep=None if keep is None else keep[i], source=None if source is None else source.next())
        writer.close()
        if source:
            source.close()
        return self.page(writer.path)

    def save_exrs(self, folder, frames):  # Save Frames' exr: half-float frames in ACES2065-1, as SDR to HDR's steps write them
        os.makedirs(folder, exist_ok=True)
        plateio.write_exrs(lambda i: frames[i], [os.path.join(folder, f"f_{i + 1:05}_.exr") for i in range(len(frames))], workers=1, fps=FPS, chromaticities="AP0")
        return self.page(folder)

    def save_matte(self, folder, mattes, fmt):  # Save Frames
        os.makedirs(folder, exist_ok=True)
        plateio.write_pngs(lambda i: matte_png(mattes[i], fmt), [os.path.join(folder, f"matte_{i + 1:05}_.png") for i in range(len(mattes))], workers=1)
        return self.page(folder)

    def zipped(self, kind):
        """The zip of every element at full size and in Upscale's set, as Export downloads it with every tick on."""
        src, plate = self.plate(kind)
        _, layers, mattes = scene()
        spec, fmt = plateio.probe_plate(src), matte_format()
        comp = [mathops.composite(plate[i], layers[i], mattes[i]) for i in range(N)]
        rows = [("composite_full_size", self.save_plate(spec, os.path.join(self.run, "export"), comp, [plateio.untouched(m) for m in mattes])),
                ("layer_full_size", self.save_plate(spec, os.path.join(self.run, "layer"), layers)),
                ("matte", self.save_matte(os.path.join(self.run, "matte"), mattes, fmt))]
        big = plateio.at_size(spec, 2 * W, 2 * H)  # Upscale's set, at twice the size: its plate and layer as SeedVR2 would give them
        up = lambda frames: [np.repeat(np.repeat(f, 2, 0), 2, 1) for f in frames]  # noqa: E731
        written = [plateio.read_float(os.path.join(self.run, "matte", f"matte_{i + 1:05}_.png"))[..., 0] for i in range(N)]
        m_up = [np.clip(ndimage.zoom(m, 2, order=1), 0, 1) for m in written]  # the plate-size matte, resized with a bilinear filter
        p_up, l_up = up(plate), up(layers)
        c_up = [mathops.composite(p_up[i], l_up[i], m_up[i]) for i in range(N)]
        out = os.path.join(self.run, "upscale", f"{2 * W}x{2 * H}", "out")
        rows += [("plate_upscaled", self.save_plate(big, os.path.join(out, "plate"), p_up)), ("layer_upscaled", self.save_plate(big, os.path.join(out, "layer"), l_up)),
                 ("composite_upscaled", self.save_plate(big, os.path.join(out, "export"), c_up)), ("matte_upscaled", self.save_matte(os.path.join(out, "matte"), m_up, "png16"))]
        hdr = os.path.join(self.run, "hdr")  # SDR to HDR's set: its plate and layer through SDR to HDR, composed with the export's matte
        p_hdr, l_hdr = [np.asarray(f, np.float32)[..., :3] * 2.5 for f in plate], [np.asarray(f, np.float32) * 3.0 for f in layers]
        c_hdr = [mathops.composite(p_hdr[i], l_hdr[i], written[i]) for i in range(N)]
        rows += [("plate_hdr", self.save_exrs(os.path.join(hdr, "plate"), p_hdr)), ("layer_hdr", self.save_exrs(os.path.join(hdr, "layer"), l_hdr)),
                 ("composite_hdr", self.save_exrs(os.path.join(hdr, "comp"), c_hdr))]
        big_hdr = plateio.at_size(plateio.probe_plate(os.path.join(hdr, "plate")), 2 * W, 2 * H)  # Upscale on SDR to HDR's set, in its format
        ph_up, lh_up = up(p_hdr), up(l_hdr)
        ch_up = [mathops.composite(ph_up[i], lh_up[i], m_up[i]) for i in range(N)]
        hout = os.path.join(hdr, "upscale", f"{2 * W}x{2 * H}", "out")
        rows += [("plate_hdr_upscaled", self.save_plate(big_hdr, os.path.join(hout, "plate"), ph_up)), ("layer_hdr_upscaled", self.save_plate(big_hdr, os.path.join(hout, "layer"), lh_up)),
                 ("composite_hdr_upscaled", self.save_plate(big_hdr, os.path.join(hout, "comp"), ch_up))]
        files = self.routes.zip_entries(rows, "desk", "source_plate", self.routes.plate_files(src))
        return zipfile.ZipFile(io.BytesIO(open(self.routes.build_zip(self.run, "desk_v1", files, None, "desk"), "rb").read()))

    def read(self, z, row, into):  # one row of the zip, as Load Plate reads it: frames, or one movie
        import zip_rows
        names = zip_rows.files(z.namelist(), row)
        z.extractall(into, names)
        if len(names) == 1 and names[0].lower().endswith(tuple(plateio.VIDEO_EXTS)):
            return np.asarray(plateio.decode_video(os.path.join(into, names[0]), N, FPS)[0], np.float32)[:N]
        return np.stack([plateio.read_float(os.path.join(into, n)) for n in sorted(names)])

    def rebuilt(self, kind):
        """The largest and the mean difference between the zip's composite and the one its plate, layer and matte rebuild, by
        stage."""
        z, into, found = self.zipped(kind), os.path.join(self.run, "unzipped"), {}
        for stage, plate, layer, matte, comp in (("full size", "source_plate", "layer_full_size", "matte", "composite_full_size"),
                                                 ("upscaled", "plate_upscaled", "layer_upscaled", "matte_upscaled", "composite_upscaled"),
                                                 ("HDR", "plate_hdr", "layer_hdr", "matte", "composite_hdr"),  # the matte: one picture, the full size's
                                                 ("HDR, upscaled", "plate_hdr_upscaled", "layer_hdr_upscaled", "matte_upscaled", "composite_hdr_upscaled")):
            p, l, m, c = (self.read(z, row, into) for row in (plate, layer, matte, comp))
            m = m[..., :1]
            d = np.abs(p[..., :3] * (1 - m) + l[..., :3] * m - c[..., :3])
            found[stage] = (float(d.max()), float(d.mean()), float((d / np.maximum(1.0, np.abs(c[..., :3]))).max()))
        return found

    def test_a_plate_of_16_bit_frames_rebuilds_within_2_of_65535(self):
        found = self.rebuilt("frames")
        print("rebuild, 16-bit PNG frames:", {k: (round(a * 65535, 2), round(b * 65535, 3), f"{r:.2e}") for k, (a, b, r) in found.items()}, "of 65535")
        for stage, (most, _, relative) in found.items():
            self.assertLessEqual(relative, 2 ** -9, stage) if "HDR" in stage else self.assertLessEqual(most, 2 / 65535, stage)

    @unittest.skipIf(av is None or "libx264" not in av.codecs_available, "PyAV with libx264 is needed")
    def test_a_movie_plate_rebuilds_within_4_of_255(self):
        found = self.rebuilt("movie")
        print("rebuild, H.264 plate, ProRes 4444 XQ export:", {k: (round(a * 255, 2), round(b * 255, 3), f"{r:.2e}") for k, (a, b, r) in found.items()}, "of 255")
        for stage, (most, mean, relative) in found.items():
            if "HDR" in stage:
                self.assertLessEqual(relative, 2 ** -9, stage)
                continue
            self.assertLessEqual(most, 4 / 255, stage)
            self.assertLessEqual(mean, 0.5 / 255, stage)


if __name__ == "__main__":
    unittest.main()
