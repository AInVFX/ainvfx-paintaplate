// The colour inspector, as OpenRV's (src/lib/app/mu_rvui/inspector.mu at 0bd9675, read 2 Nov 2026): F5 shows it, as
// toggleColorInspector in rvui.mu; Shift+click samples, Shift+drag averages, the box drags the point with it. RV lists the pixel in the image's own pixels (Native Pixel), its values as "%f", and
// the average of the pixels sampled with Shift held. RV shows either the source colour or the final colour; this
// inspector shows both: the source values at full precision and native size, read on the server from the file on show
// (/paintaplate/pixel), and the values drawn on screen, as 0 to 1 like RV's framebuffer read. Pure functions, tested in
// tests/js/inspector.test.mjs.

export const INSPECT_SIZE = 1; // pixels a side read around the pointer; RV reads one

// The plate pixel under a point of the view, from its position as fractions of the drawn frame. The origin is the top
// left, as RV's Native Pixel of a file whose rows run top down (EXR, video).
export function sourcePixel(fx, fy, width, height) {
  const inside = fx >= 0 && fx < 1 && fy >= 0 && fy < 1;
  const clamp = (v, n) => Math.min(n - 1, Math.max(0, Math.floor(v * n)));
  return { x: clamp(fx, width), y: clamp(fy, height), inside };
}

// The file on show: a shot's EXR frames when it has them, else its movie (an output file named by ComfyUI's view URL),
// else the plate.
export function sourcePath(shot, plate) {
  if (shot?.frames) return shot.frames;
  if (shot?.url) {
    const q = new URL(shot.url, "http://x").searchParams, name = q.get("filename");
    if (name) return `${q.get("type") === "input" ? "input" : "output"}:${[q.get("subfolder"), name].filter(Boolean).join("/")}`;
  }
  return plate;
}

export const formatValue = (v) => (Number.isFinite(v) ? v.toFixed(6) : "nan"); // RV's "%f"

export function addSample(avg, value) { // RV's running average while Shift is held
  return avg ? { sum: avg.sum.map((s, i) => s + value[i]), n: avg.n + 1 } : { sum: [...value], n: 1 };
}

// Where the box goes: beside the point, below and to the right, flipped to stay inside the viewport
export function boxPlace(x, y, w, h, vw, vh, gap = 14) {
  const bx = x + gap + w <= vw ? x + gap : Math.max(0, x - gap - w);
  const by = y + gap + h <= vh ? y + gap : Math.max(0, y - gap - h);
  return [Math.round(bx), Math.round(by)];
}

// The rows the inspector shows, top to bottom.
export function inspectorRows({ x, y, inside = true, frame, value, final, average, error, width, height }) {
  const rows = [["Native Pixel", inside ? `${x}, ${y}` : "outside the frame"], ["Frame", String(frame)]];
  if (width) rows.push(["Size", `${width} x ${height}`]);
  if (error) return [...rows, ["Error", error]];
  const rgb = (label, v) => [[label, ""], ...["Red", "Green", "Blue", "Alpha"].slice(0, v.length).map((n, i) => [n, formatValue(v[i])])];
  if (value) rows.push(...rgb("Source Color", value));
  if (final) rows.push(...rgb("Final Color", final));
  if (average?.n > 1) rows.push(...rgb(`Average of ${average.n}`, average.sum.map((s) => s / average.n)));
  return rows;
}
