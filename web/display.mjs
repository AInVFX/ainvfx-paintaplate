// The viewer's colour on the GPU, as OpenRV chains its nodes when OCIO manages colour (ocio_source_setup.py): the file
// values to the config's scene-linear space (OCIOFile), the colour tools there (RVColor), then the look and the display and
// view (OCIOLook, OCIODisplay), then the channel shown as grey, picked from the display values: OCIODisplay floods a channel
// after its OCIO function (OCIOIPNode.cpp). OpenColorIO writes the two OCIO functions as GLSL ES 3.0 on the server
// (ocio.py), with their lookup tables, from the same GPU processor OpenRV asks for (OPTIMIZATION_DEFAULT). A program is
// made once per colour space and view: changing the plate's colour space, the display or the view swaps it, so it applies
// while the shot plays. Frames of an image sequence, and a paused video plate's source frame, arrive as RGB half floats
// (DeepFrames in frames.mjs), so values above 1.0 reach the shader; video frames and canvases are 8 bits.
// OpenRV read at 0bd9675 (main, 2 Nov 2026): src/lib/ip/IPBaseNodes/ColorIPNode.cpp, src/lib/ip/OCIONodes/OCIOIPNode.cpp,
// src/lib/ip/IPCore/glsl/ColorGamma.glsl and ColorMatrix.glsl.

// ---------- The plate's own size on the canvas (OpenRV shows a plate at its resolution; key 1 is 1:1) ----------
export function nativeSize(width, height, max) { // the canvas: the plate's size, at most `max` on the long side
  const k = Math.min(1, max / Math.max(width, height));
  return [Math.round(width * k), Math.round(height * k)];
}
// The zoom at which one canvas pixel covers one screen pixel: the frame fits at `fitWidth` CSS pixels
export const oneToOne = (canvasWidth, fitWidth, dpr = 1) => canvasWidth / (fitWidth * dpr);

// ---------- The colour tools, as RVColor (ColorIPNode.cpp): display only, the export never changes ----------
// RV builds one 4 x 4 matrix C, each tool multiplied on the left, so it acts after the ones before it: invert, exposure
// (2 to the stops), contrast ((1 + c) x - c / 2, about 0.5), hue (a rotation about the grey axis, sheared so that Rec. 709
// luma holds), saturation (Rec. 709 weights). Its shader applies gamma first (pow of max(x, 0) by 1 / gamma, only when
// gamma is not 1), then C: ColorMatrix(ColorGamma(source)). RV's invert matrix has (1, 1, 1, 0) as its last row, so after
// an invert the homogeneous coordinate holds r + g + b, and a later contrast scales its offset by it: kept, for the same
// values as RV.
export const DISPLAY = { exposure: 0, contrast: 0, gamma: 1, saturation: 1, hue: 0, channel: "rgb", invert: false };
export const PARAMS = { // the interactive edits: label, step for - and = and the wheel, change per pixel dragged, limits
  exposure: { label: "Exposure", step: 0.1, drag: 0.01, min: -10, max: 10 }, // stops: one per 100 px dragged
  contrast: { label: "Contrast", step: 0.05, drag: 0.005, min: -1, max: 4 }, // RV's color.contrast, 0 at rest
  gamma: { label: "Gamma", step: 0.05, drag: 0.005, min: 0.1, max: 8 },
  saturation: { label: "Saturation", step: 0.05, drag: 0.005, min: 0, max: 4 },
  hue: { label: "Hue", step: 5, drag: 0.5, min: -180, max: 180 }, // degrees; RV's color.hue holds radians
};
export const CHANNEL_NAMES = { rgb: "All channels", r: "Red", g: "Green", b: "Blue", l: "Luminance" };
export const clampParam = (name, v) => +Math.min(PARAMS[name].max, Math.max(PARAMS[name].min, v)).toFixed(3);
export const displayActive = (d) => Object.keys(DISPLAY).some((k) => d[k] !== DISPLAY[k]);

export function formatParam(name, v) {
  if (name === "exposure") return `${v > 0 ? "+" : ""}${v.toFixed(1)} stop${Math.abs(v) === 1 ? "" : "s"}`;
  if (name === "contrast") return `${v > 0 ? "+" : ""}${v.toFixed(2)}`;
  return name === "hue" ? `${Math.round(v)}°` : v.toFixed(2);
}

export function displayLabel(d) { // the transport's reminder of what the viewer changes: "E +1.0 · γ 2.20 · Red"
  const parts = [];
  if (d.exposure) parts.push(`E ${d.exposure > 0 ? "+" : ""}${d.exposure.toFixed(1)}`);
  if (d.contrast) parts.push(`C ${formatParam("contrast", d.contrast)}`);
  if (d.gamma !== 1) parts.push(`γ ${d.gamma.toFixed(2)}`);
  if (d.saturation !== 1) parts.push(`Sat ${d.saturation.toFixed(2)}`);
  if (d.hue) parts.push(`Hue ${Math.round(d.hue)}°`);
  if (d.channel !== "rgb") parts.push(CHANNEL_NAMES[d.channel]);
  if (d.invert) parts.push("Inverted");
  return parts.join(" · ");
}

export const LUMA = [0.2126, 0.7152, 0.0722]; // Rec. 709, the first row of RV's Rec709FullRangeRGBToYUV8
const PICK = { r: [1, 0, 0], g: [0, 1, 0], b: [0, 0, 1], l: LUMA }; // OCIODisplay's flood rows
const ID4 = () => [0, 1, 2, 3].map((i) => [0, 1, 2, 3].map((j) => +(i === j)));
const mul = (A, B) => A.map((row) => B[0].map((_, j) => row.reduce((a, v, k) => a + v * B[k][j], 0)));
const embed = (m) => [[...m[0], 0], [...m[1], 0], [...m[2], 0], [0, 0, 0, 1]];
function rotation(axis, angle) { // Rodrigues, for column vectors (TwkMath's makeRotation)
  const n = Math.hypot(...axis), [x, y, z] = axis.map((v) => v / n), c = Math.cos(angle), s = Math.sin(angle), t = 1 - c;
  return embed([[t * x * x + c, t * x * y - s * z, t * x * z + s * y], [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
    [t * x * z - s * y, t * y * z + s * x, t * z * z + c]]);
}
const inverse = (R) => embed([0, 1, 2].map((i) => [0, 1, 2].map((j) => R[j][i]))); // a rotation's inverse is its transpose

export function hueMatrix(radians) { // iR * iZsh * Rz * Zsh * R, as ColorIPNode.cpp
  const R = rotation([1, -1, 0], Math.acos(1 / Math.sqrt(3))), l = mul(R, [[LUMA[0]], [LUMA[1]], [LUMA[2]], [0]]).map((r) => r[0]);
  const xz = l[0] / l[2], yz = l[1] / l[2];
  const Zsh = [[1, 0, 0, 0], [0, 1, 0, 0], [xz, yz, 1, 0], [0, 0, 0, 1]], iZsh = [[1, 0, 0, 0], [0, 1, 0, 0], [-xz, -yz, 1, 0], [0, 0, 0, 1]];
  return [inverse(R), iZsh, rotation([0, 0, 1], radians), Zsh, R].reduce((a, b) => mul(a, b));
}

export function colorMatrix({ exposure = 0, contrast = 0, saturation = 1, hue = 0, invert = false }) { // RV's C, 4 x 4
  let C = ID4();
  if (invert) C = mul([[-1, 0, 0, 1], [0, -1, 0, 1], [0, 0, -1, 1], [1, 1, 1, 0]], C);
  if (exposure) { const e = 2 ** exposure; C = mul(embed([[e, 0, 0], [0, e, 0], [0, 0, e]]), C); }
  if (contrast) { const s = 1 + contrast, o = -contrast / 2; C = mul([[s, 0, 0, o], [0, s, 0, o], [0, 0, s, o], [0, 0, 0, 1]], C); }
  if (hue) C = mul(hueMatrix((hue * Math.PI) / 180), C);
  if (saturation !== 1) {
    const s = saturation;
    C = mul(embed([0, 1, 2].map((i) => [0, 1, 2].map((j) => (1 - s) * LUMA[j] + (i === j ? s : 0)))), C);
  }
  return C;
}

// The shader's values. Before the display: gamma's exponent, then the colour matrix as its 3 x 3 part and its offset (the
// source's homogeneous coordinate is 1). After it: `pick`, the channel shown as grey, else the identity.
export function displayUniforms(d) {
  const { gamma = 1, channel = "rgb" } = d, C = colorMatrix(d), one = PICK[channel];
  return { exponent: gamma !== 1 ? 1 / gamma : 1, matrix: C.slice(0, 3).map((r) => r.slice(0, 3)), offset: C.slice(0, 3).map((r) => r[3]),
           pick: one ? [[...one], [...one], [...one]] : [[1, 0, 0], [0, 1, 0], [0, 0, 1]] };
}

const VERTEX = `#version 300 es
in vec2 corner;
out vec2 uv;
void main() { uv = vec2(corner.x + 1.0, 1.0 - corner.y) * 0.5; gl_Position = vec4(corner, 0.0, 1.0); }`;

const fragment = (fin, fout) => `#version 300 es
precision highp float;
precision highp sampler2D;
precision highp sampler3D;
in vec2 uv;
out vec4 color;
uniform sampler2D frame;
uniform float exponent;
uniform mat3 mixing, pick;
uniform vec3 offset;
${fin}
${fout}
void main() {
  vec3 c = ocioIn(vec4(texture(frame, uv).rgb, 1.0)).rgb;
  if (exponent != 1.0) c = pow(max(c, 0.0), vec3(exponent)); // ColorGamma, then ColorMatrix: RV's order
  c = mixing * c + offset;
  color = vec4(pick * ocioOut(vec4(c, 1.0)).rgb, 1.0);
}`;

const floats = (b64) => { const s = atob(b64), u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i); return new Float32Array(u.buffer); };

export const viewKey = ({ config = "", display = "", view = "", look = "" }, space) => JSON.stringify([config, space, display, view, look]);

export class Display {
  // onready(): a program arrived, so the viewer draws again; onerror(message): OCIO refused a colour space or a view
  constructor({ onready = () => {}, onerror = () => {} } = {}) {
    Object.assign(this, { onready, onerror, programs: new Map(), view: null });
    this.canvas = document.createElement("canvas");
    const gl = (this.gl = this.canvas.getContext("webgl2", { alpha: false, antialias: false, depth: false, premultipliedAlpha: false, preserveDrawingBuffer: true }));
    if (!gl) return;
    this.linearFloats = !!gl.getExtension("OES_texture_float_linear"); // else filtered tables go in half floats
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    this.frame = this.texture(gl.TEXTURE_2D, false);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
  }

  get ready() { return !!this.gl; }

  texture(target, nearest) {
    const gl = this.gl, t = gl.createTexture(), f = nearest ? gl.NEAREST : gl.LINEAR;
    gl.bindTexture(target, t);
    for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, f], [gl.TEXTURE_MAG_FILTER, f], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE]])
      if (k !== gl.TEXTURE_WRAP_R || target === gl.TEXTURE_3D) gl.texParameteri(target, k, v);
    return t;
  }

  // The view every source goes through: { config, display, view, look }. A new one draws with programs made for it.
  setView(v) { this.view = { ...v }; }

  // The program for a source in `space`: made from the server's GLSL the first time, then kept. Null while it loads.
  program(space) {
    if (!this.gl || !this.view || !space) return null;
    const key = viewKey(this.view, space), have = this.programs.get(key);
    if (have) return have.ready ? have : null;
    const entry = { ready: false };
    this.programs.set(key, entry);
    const { config, display, view, look } = this.view;
    fetch(`/paintaplate/ocio/shader?${new URLSearchParams({ config, space, display, view, look: look ?? "" })}`).then(async (r) => {
      const s = await r.json();
      if (!r.ok) throw new Error(s.error ?? `OCIO shader: ${r.status}`);
      Object.assign(entry, this.compile(s), { identity: s.identity, ready: true });
      this.onready();
    }).catch((err) => { entry.failed = true; this.onerror(err.message); });
    return null;
  }

  compile(s) {
    const gl = this.gl, program = gl.createProgram();
    for (const [type, text] of [[gl.VERTEX_SHADER, VERTEX], [gl.FRAGMENT_SHADER, fragment(s.in.text, s.out.text)]]) {
      const sh = gl.createShader(type);
      gl.shaderSource(sh, text);
      gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(`OCIO shader: ${gl.getShaderInfoLog(sh)}`);
      gl.attachShader(program, sh);
    }
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(`OCIO shader: ${gl.getProgramInfoLog(program)}`);
    const tables = [...s.in.tables, ...s.out.tables].map((t, i) => {
      const unit = i + 1, three = t.kind === "3d", target = three ? gl.TEXTURE_3D : gl.TEXTURE_2D;
      gl.activeTexture(gl.TEXTURE0 + unit);
      const tex = this.texture(target, t.nearest), half = !t.nearest && !this.linearFloats; // filtered 32-bit floats need an extension
      const [fmt, inner] = t.channels === 1 ? [gl.RED, half ? gl.R16F : gl.R32F] : [gl.RGB, half ? gl.RGB16F : gl.RGB32F];
      if (three) gl.texImage3D(target, 0, inner, t.size, t.size, t.size, 0, fmt, gl.FLOAT, floats(t.data));
      else gl.texImage2D(target, 0, inner, t.width, t.height, 0, fmt, gl.FLOAT, floats(t.data));
      return { unit, target, tex, at: gl.getUniformLocation(program, t.sampler) };
    });
    gl.activeTexture(gl.TEXTURE0);
    const at = Object.fromEntries(["frame", "exponent", "mixing", "offset", "pick", "corner"].map((n) =>
      [n, n === "corner" ? gl.getAttribLocation(program, n) : gl.getUniformLocation(program, n)]));
    return { program, at, tables };
  }

  // What to draw for `src`, whose values are in colour space `space`, with the viewer's colour `d`: `src` itself when the
  // chain changes nothing (an 8-bit frame at the defaults through an identity view), else this canvas with `src` through
  // the program. `src` is a video, an ImageBitmap, a canvas, or a full-precision frame { width, height, data } of RGB half
  // floats. Null while the program loads, or for a full-precision frame without WebGL2: the caller draws its 8-bit copy.
  image(src, d, space) {
    const exact = !!src?.data;
    if (!src) return src;
    const p = this.program(space);
    if (!p) return exact ? null : src;
    if (!exact && p.identity && !displayActive(d)) return src;
    const gl = this.gl, w = src.videoWidth || src.width, h = src.videoHeight || src.height;
    if (!w || !h) return exact ? null : src;
    if (this.canvas.width !== w || this.canvas.height !== h) [this.canvas.width, this.canvas.height] = [w, h];
    gl.viewport(0, 0, w, h);
    gl.useProgram(p.program);
    gl.enableVertexAttribArray(p.at.corner);
    gl.vertexAttribPointer(p.at.corner, 2, gl.FLOAT, false, 0, 0);
    for (const t of p.tables) { gl.activeTexture(gl.TEXTURE0 + t.unit); gl.bindTexture(t.target, t.tex); gl.uniform1i(t.at, t.unit); }
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.frame);
    gl.uniform1i(p.at.frame, 0);
    if (exact) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB16F, w, h, 0, gl.RGB, gl.HALF_FLOAT, src.data);
    else gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src);
    const u = displayUniforms(d);
    gl.uniform1f(p.at.exponent, u.exponent);
    gl.uniformMatrix3fv(p.at.mixing, true, u.matrix.flat());
    gl.uniform3fv(p.at.offset, u.offset);
    gl.uniformMatrix3fv(p.at.pick, true, u.pick.flat());
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    return this.canvas;
  }
}
