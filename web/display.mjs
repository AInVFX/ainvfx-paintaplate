// The viewer's colour on the GPU, as OpenRV chains its nodes when OCIO manages colour (ocio_source_setup): the file values
// to the config's scene-linear space (OCIOFile), the colour tools there (RVColor: exposure and contrast, one matrix for hue,
// saturation and invert, then gamma; ColorIPNode.cpp, read 28 Oct 2026), then the look and the display and view
// (OCIOLook, OCIODisplay), then the channel shown as grey, picked from the display values: OCIODisplay floods a channel
// after its OCIO function (OCIOIPNode.cpp, read 29 Oct 2026). OpenColorIO writes the two OCIO functions as GLSL ES 3.0 on
// the server (ocio.py), with
// their lookup tables. A program is made once per colour space and view: changing the plate's colour space, the display
// or the view swaps it, so it applies while the shot plays. Frames of an image sequence arrive as RGB half floats
// (DeepFrames in frames.mjs), so values above 1.0 reach the shader; video frames and canvases are 8 bits.

import { displayActive, displayUniforms } from "./logic.mjs";

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
uniform float slope, intercept, exponent;
uniform mat3 mixing, pick;
uniform vec3 offset;
${fin}
${fout}
void main() {
  vec3 c = ocioIn(vec4(texture(frame, uv).rgb, 1.0)).rgb;
  c = mixing * (c * slope + intercept) + offset;
  if (exponent != 1.0) c = pow(max(c, 0.0), vec3(exponent));
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
    const at = Object.fromEntries(["frame", "slope", "intercept", "exponent", "mixing", "offset", "pick", "corner"].map((n) =>
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
    gl.uniform1f(p.at.slope, u.slope);
    gl.uniform1f(p.at.intercept, u.intercept);
    gl.uniform1f(p.at.exponent, u.exponent);
    gl.uniformMatrix3fv(p.at.mixing, true, u.matrix.flat());
    gl.uniform3fv(p.at.offset, u.offset);
    gl.uniformMatrix3fv(p.at.pick, true, u.pick.flat());
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    return this.canvas;
  }
}
