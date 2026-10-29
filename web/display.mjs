// The viewer's colour on the GPU, after OpenRV. Each frame is decoded to linear light; then come exposure (times 2 to the
// stops) and contrast, one colour matrix for hue, saturation, the channel and invert, then gamma, then the display's sRGB
// encoding. OpenRV's ColorIPNode.cpp builds exposure, contrast, hue and saturation as matrices in that order (read 28 Oct
// 2026). Frames of an EXR or other image sequence arrive as RGB half floats (DeepFrames in frames.mjs), so values above 1.0
// reach the shader and lower exposure brings them back. Video frames and canvases are 8-bit sRGB: while the colour stays at
// its defaults they are drawn as they are, so playback pays nothing until a value moves.

import { displayActive, displayUniforms } from "./logic.mjs";

export const DECODED = new Set(["linear", "sRGB"]); // the colour spaces the shader decodes; a plate in another keeps the 8-bit preview

const VERTEX = `#version 300 es
in vec2 corner;
out vec2 uv;
void main() { uv = vec2(corner.x + 1.0, 1.0 - corner.y) * 0.5; gl_Position = vec4(corner, 0.0, 1.0); }`;

const FRAGMENT = `#version 300 es
precision highp float;
in vec2 uv;
out vec4 color;
uniform sampler2D frame;
uniform bool encoded;
uniform float slope, intercept, exponent;
uniform mat3 mixing;
uniform vec3 offset;
vec3 decode(vec3 c) { return mix(c / 12.92, pow((max(c, 0.0) + 0.055) / 1.055, vec3(2.4)), step(0.04045, c)); }
vec3 encode(vec3 c) { c = clamp(c, 0.0, 1.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c)); }
void main() {
  vec3 c = texture(frame, uv).rgb;
  if (encoded) c = decode(c);
  c = mixing * (c * slope + intercept) + offset;
  color = vec4(encode(pow(max(c, 0.0), vec3(exponent))), 1.0);
}`;

export class Display {
  constructor() {
    this.canvas = document.createElement("canvas");
    const gl = (this.gl = this.canvas.getContext("webgl2", { alpha: false, antialias: false, depth: false, premultipliedAlpha: false, preserveDrawingBuffer: true }));
    if (!gl) return;
    const program = gl.createProgram();
    for (const [type, text] of [[gl.VERTEX_SHADER, VERTEX], [gl.FRAGMENT_SHADER, FRAGMENT]]) {
      const s = gl.createShader(type);
      gl.shaderSource(s, text);
      gl.compileShader(s);
      gl.attachShader(program, s);
    }
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) { console.warn(gl.getProgramInfoLog(program)); this.gl = null; return; }
    gl.useProgram(program);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const corner = gl.getAttribLocation(program, "corner");
    gl.enableVertexAttribArray(corner);
    gl.vertexAttribPointer(corner, 2, gl.FLOAT, false, 0, 0);
    gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
    for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) {
      gl.texParameteri(gl.TEXTURE_2D, k, v);
    }
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
    this.at = Object.fromEntries(["encoded", "slope", "intercept", "exponent", "mixing", "offset"].map((n) => [n, gl.getUniformLocation(program, n)]));
  }

  get ready() { return !!this.gl; }

  // What to draw for `src` with the viewer's colour `d`: `src` itself (8-bit, colour at its defaults), else this canvas with
  // `src` through the shader. `src` is a video, an ImageBitmap, a canvas, or a full-precision frame { width, height, data }
  // of RGB half floats, whose colour space `space` is "linear" or "sRGB".
  image(src, d, space = "sRGB") {
    const exact = !!src?.data;
    if (!src || !this.gl || (!exact && !displayActive(d))) return src;
    const gl = this.gl, w = src.videoWidth || src.width, h = src.videoHeight || src.height;
    if (!w || !h) return src;
    if (this.canvas.width !== w || this.canvas.height !== h) [this.canvas.width, this.canvas.height] = [w, h];
    gl.viewport(0, 0, w, h);
    if (exact) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB16F, w, h, 0, gl.RGB, gl.HALF_FLOAT, src.data);
    else gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src);
    const u = displayUniforms(d), at = this.at;
    gl.uniform1i(at.encoded, exact && space === "linear" ? 0 : 1);
    gl.uniform1f(at.slope, u.slope);
    gl.uniform1f(at.intercept, u.intercept);
    gl.uniform1f(at.exponent, u.exponent);
    gl.uniformMatrix3fv(at.mixing, true, u.matrix.flat());
    gl.uniform3fv(at.offset, u.offset);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    return this.canvas;
  }
}
