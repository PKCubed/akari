#!/usr/bin/env python3
"""lightviz: 3D wash-light visualizer driven by Art-Net / sACN.

    python viz.py                     # listen for Art-Net + sACN, rig from fixtures.py
    python viz.py --demo              # animate the rig without any network input
    python viz.py --scale 0.75        # render at 75% resolution (slower GPUs)
    python viz.py --bench             # measure frame time on this machine
    python viz.py --headless out.png --demo look   # render one frame to a PNG

Resolution drops automatically to hold 30 fps (--target-fps); the title bar
shows the current fps and resolution.

Mouse: left-drag orbit | right/middle-drag pan | wheel zoom
Keys:  1-5 camera presets | UP/DOWN haze | S haze shadows | R reload | ESC quit
"""
import argparse
import math
import os
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import moderngl

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import patterns                                   # noqa: E402
from dmx_in import DMXInput                       # noqa: E402
from fixture import MAX_FIXTURES, load_rig        # noqa: E402

VERT = """
#version 330 core
void main() {
    vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
"""
SHADERS = HERE / "shaders"


def shader_src(name):
    return (SHADERS / "common.glsl").read_text() + "\n" + (SHADERS / name).read_text()


def make_noise(n=64, seed=7):
    """Tileable 3D haze-density texture: low-pass filtered white noise (FFT => wraps)."""
    rng = np.random.default_rng(seed)
    F = np.fft.fftn(rng.random((n, n, n)))
    k = np.fft.fftfreq(n)
    k2 = k[:, None, None] ** 2 + k[None, :, None] ** 2 + k[None, None, :] ** 2

    def band(sigma):
        v = np.real(np.fft.ifftn(F * np.exp(-2.0 * (np.pi * sigma) ** 2 * k2)))
        return (v - v.mean()) / v.std()

    v = 0.7 * band(5.0) + 0.3 * band(2.0)
    lo, hi = np.percentile(v, (1, 99))
    return (np.clip((v - lo) / (hi - lo), 0, 1) * 255).astype("u1")


VIEWS = {   # yaw, pitch, distance, target
    1: (0.0, 0.08, 14.5, (0.0, 3, -0.3)),        # balcony, centre (default)
    2: (0.55, 0.38, 15.0, (0.0, 1.6, -0.5)),     # three-quarter from the balcony
    3: (1.45, 0.12, 15.0, (0.0, 2.2, -0.5)),     # from stage-right side
    4: (0.00, 1.35, 16.0, (0.0, 0.0, -0.5)),     # top-down plan view
    5: (0.00, 0.07, 9.5, (0.0, 2.0, -0.2)),      # house centre, level with the stage
}


class Camera:
    def __init__(self, view=1):
        self.preset(view)

    def preset(self, v):
        self.yaw, self.pitch, self.dist, t = VIEWS[v]
        self.target = np.array(t, dtype="f8")

    def basis(self):
        cp = math.cos(self.pitch)
        pos = self.target + self.dist * np.array(
            [cp * math.sin(self.yaw), math.sin(self.pitch), cp * math.cos(self.yaw)])
        fwd = self.target - pos
        fwd /= np.linalg.norm(fwd)
        right = np.cross(fwd, [0.0, 1.0, 0.0])
        right /= np.linalg.norm(right)
        up = np.cross(right, fwd)
        return pos, right, up, fwd

    def orbit(self, dx, dy):
        self.yaw -= dx * 0.006
        self.pitch = max(-0.2, min(1.5, self.pitch + dy * 0.006))

    def pan(self, dx, dy):
        _, right, up, _ = self.basis()
        k = self.dist * 0.0012
        self.target += (-right * dx + up * dy) * k

    def zoom(self, d):
        self.dist = max(2.0, min(40.0, self.dist * (0.9 ** d)))


class Rig:
    """The fixtures.py file, hot-reloaded when it changes on disk."""

    def __init__(self, path, dmx):
        self.path, self.dmx = Path(path), dmx
        self.mtime = 0.0
        self.fixtures, self.settings = [], {}
        self.version = 0
        self.reload(first=True)

    def reload(self, first=False):
        try:
            self.mtime = self.path.stat().st_mtime
            fixtures, settings = load_rig(self.path)
        except Exception:
            print(f"[rig] error in {self.path.name}, keeping previous rig:")
            traceback.print_exc()
            if first:
                sys.exit(1)
            return False
        self.fixtures, self.settings = fixtures, settings
        self.dmx.artnet_offset = settings.get("ARTNET_UNIVERSE_OFFSET", 1)
        self.dmx.join_sacn({f.universe for f in fixtures})
        self.version += 1
        print(f"[rig] loaded {len(fixtures)} fixtures from {self.path.name}")
        return True

    def poll(self):
        try:
            if self.path.stat().st_mtime != self.mtime:
                time.sleep(0.05)               # let editors finish writing
                return self.reload()
        except OSError:
            pass
        return False


class Renderer:
    """Three passes: surfaces (render res) -> haze (lower res) -> composite (window res)."""

    def __init__(self, ctx, size, scale=1.0, haze_scale=0.5, samples=8):
        self.ctx, self.scale, self.haze_scale, self.samples = ctx, scale, haze_scale, samples
        self.surface = ctx.program(vertex_shader=VERT, fragment_shader=shader_src("surface.frag"))
        self.haze = ctx.program(vertex_shader=VERT, fragment_shader=shader_src("haze.frag"))
        self.comp = ctx.program(vertex_shader=VERT, fragment_shader=shader_src("composite.frag"))
        self.vaos = {p: ctx.vertex_array(p, []) for p in (self.surface, self.haze, self.comp)}
        self.noise = ctx.texture3d((64, 64, 64), 1, make_noise().tobytes())
        self.noise.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.noise.repeat_x = self.noise.repeat_y = self.noise.repeat_z = True
        self.targets = []
        self.frame = 0
        self.size = None
        self.resize(size)

    def set_scale(self, scale):
        if abs(scale - self.scale) > 1e-3:
            self.scale = scale
            self.size = None                         # force re-allocation on next draw

    def resize(self, size):
        if tuple(size) == self.size:
            return
        self.size = tuple(size)
        for t, f in self.targets:
            t.release(); f.release()
        sw, sh = max(16, int(size[0] * self.scale)), max(16, int(size[1] * self.scale))
        hw, hh = max(8, int(sw * self.haze_scale)), max(8, int(sh * self.haze_scale))
        self.targets = []
        for w, h in ((sw, sh), (hw, hh)):
            t = self.ctx.texture((w, h), 4, dtype="f2")
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t.repeat_x = t.repeat_y = False
            self.targets.append((t, self.ctx.framebuffer([t])))
        (self.surf_tex, self.surf_fbo), (self.haze_tex, self.haze_fbo) = self.targets

    @staticmethod
    def _set(prog, name, value):
        if name in prog:
            prog[name].value = value

    @staticmethod
    def _arr(prog, name, arr, dtype="f4"):
        if name in prog:
            prog[name].write(np.ascontiguousarray(arr, dtype=dtype).tobytes())

    def draw(self, target, size, cam, rig, dmx, state, t):
        self.resize(size)
        fx = rig.fixtures
        pos = np.zeros((MAX_FIXTURES, 3)); dr = np.zeros((MAX_FIXTURES, 3))
        col = np.zeros((MAX_FIXTURES, 3)); cone = np.ones((MAX_FIXTURES, 2))
        active = np.zeros(MAX_FIXTURES, dtype="i4")
        pers = np.zeros((MAX_FIXTURES, 4)); pers_d = np.zeros(MAX_FIXTURES)
        pc = np.array(rig.settings.get("PERSON", (0.0, 0.0, 0.8)), dtype="f8") + (0.0, 0.9, 0.0)
        n_active = 0
        for i, f in enumerate(fx):
            pos[i], dr[i], cone[i] = f.pos, f.aim(), f.cone()
            col[i] = f.rgb(dmx.get(f.universe))
            v = pc - pos[i]                          # person's bounding sphere seen from the light
            d = float(np.linalg.norm(v)) or 1e-6
            sin_r = min(1.0, 1.1 / d)
            pers[i, :3], pers[i, 3] = v / d, (-1.0 if sin_r >= 1.0 else math.sqrt(1 - sin_r ** 2))
            pers_d[i] = d
            if col[i].sum() > 0.002:                 # dark fixtures cost nothing
                active[n_active] = i
                n_active += 1
        s = rig.settings
        cp, right, up, fwd = cam.basis()
        common = {
            "uCamPos": tuple(cp), "uRight": tuple(right), "uUp": tuple(up), "uFwd": tuple(fwd),
            "uTanHalf": math.tan(math.radians(45.0) / 2), "uCount": len(fx),
            "uNumActive": n_active, "uPerson": tuple(s.get("PERSON", (0.0, 0.0, 0.8))),
            "uFrame": self.frame,
        }
        passes = (
            (self.surface, self.surf_fbo, {"uAmbient": float(s.get("AMBIENT", 0.012))}),
            (self.haze, self.haze_fbo, {
                "uTime": t, "uHaze": state["haze"],
                "uHazeG": float(s.get("HAZE_ANISOTROPY", 0.35)),
                "uSamples": int(self.samples), "uHazeShadows": 1 if state["shadows"] else 0,
                "uSurf": 0, "uNoise": 1}),
            (self.comp, target, {"uExposure": float(s.get("EXPOSURE", 1.0)),
                                 "uSurf": 0, "uHazeTex": 2}),
        )
        self.surf_tex.use(0)
        self.noise.use(1)
        self.haze_tex.use(2)
        for prog, fbo, extra in passes:
            fbo.use()
            if fbo is target:
                fbo.viewport = (0, 0, size[0], size[1])
                res = size
            else:
                res = fbo.size
            for k, v in {**common, **extra, "uRes": (float(res[0]), float(res[1]))}.items():
                self._set(prog, k, v)
            self._arr(prog, "uLPos", pos); self._arr(prog, "uLDir", dr)
            self._arr(prog, "uLCol", col); self._arr(prog, "uLCone", cone)
            self._arr(prog, "uActive", active, "i4")
            self._arr(prog, "uLPers", pers); self._arr(prog, "uLPersD", pers_d)
            self.vaos[prog].render(moderngl.TRIANGLES, vertices=3)
        self.frame += 1


def gl_report(ctx):
    r = ctx.info.get("GL_RENDERER", "?")
    print(f"[gl] {r} | OpenGL {ctx.version_code / 100:.1f}")
    if any(w in r.lower() for w in ("llvmpipe", "softpipe", "software", "swrast")):
        print("[gl] WARNING: this is SOFTWARE rendering (the CPU), not your GPU. It will be slow.\n"
              "     Check your graphics driver; on a laptop with NVIDIA try:\n"
              "     __NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia python viz.py")


def apply_demo(rig, dmx, pattern, t):
    for u, buf in patterns.frame(rig.fixtures, t, pattern).items():
        dmx.set(u, bytes(buf))


def parse_size(s):
    w, h = s.lower().split("x")
    return int(w), int(h)


def run_headless(args, dmx, rig):
    ctx = None
    for backend in ("egl", None):
        try:
            ctx = (moderngl.create_standalone_context(backend=backend) if backend
                   else moderngl.create_standalone_context())
            break
        except Exception as e:
            print("[gl] standalone context failed:", backend, e)
    if ctx is None:
        sys.exit("no OpenGL context available")
    gl_report(ctx)
    size = parse_size(args.size)
    out_tex = ctx.texture(size, 3)
    out = ctx.framebuffer([out_tex])
    rend = Renderer(ctx, size, args.scale, args.haze_scale, args.samples)
    cam = Camera(args.view)
    state = {"haze": rig.settings.get("HAZE", 0.1), "shadows": True}
    t0 = time.monotonic()
    while True:
        now = time.monotonic() - t0
        if args.demo:
            apply_demo(rig, dmx, args.demo, args.t if args.t is not None else now)
        if now >= args.wait:
            break
        time.sleep(0.02)
    if args.bench:
        rend.draw(out, size, cam, rig, dmx, state, 0.0); ctx.finish()      # warm-up
        t1 = time.perf_counter()
        for i in range(args.bench):
            rend.draw(out, size, cam, rig, dmx, state, i / 30.0)
        ctx.finish()
        ms = (time.perf_counter() - t1) / args.bench * 1000
        print(f"[bench] {size[0]}x{size[1]} scale {args.scale} haze-scale {args.haze_scale} "
              f"samples {args.samples}: {ms:.1f} ms/frame = {1000 / ms:.0f} fps")
    rend.draw(out, size, cam, rig, dmx, state, 10.0)
    data = out.read(components=3)
    from PIL import Image
    if args.headless in ("/dev/null", "NUL"):
        return
    Image.frombytes("RGB", size, data).transpose(Image.FLIP_TOP_BOTTOM).save(args.headless)
    print("[headless] wrote", args.headless, "| packets:", dmx.counts)


def run_window(args, dmx, rig):
    import pygame
    pygame.display.init()
    for k, v in ((pygame.GL_CONTEXT_MAJOR_VERSION, 3), (pygame.GL_CONTEXT_MINOR_VERSION, 3),
                 (pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE),
                 (pygame.GL_CONTEXT_FORWARD_COMPATIBLE_FLAG, 1)):
        pygame.display.gl_set_attribute(k, v)
    size = parse_size(args.size)
    flags = pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE
    try:
        pygame.display.set_mode(size, flags, vsync=1)
    except TypeError:
        pygame.display.set_mode(size, flags)
    ctx = moderngl.create_context()
    gl_report(ctx)
    rend = Renderer(ctx, size, args.scale, args.haze_scale, args.samples)
    cam = Camera(args.view)
    state = {"haze": rig.settings.get("HAZE", 0.1), "shadows": True}
    clock, t0 = pygame.time.Clock(), time.monotonic()
    last_title, last_counts = 0.0, dict(dmx.counts)
    max_scale = args.scale
    last_adjust, frames_since = 0.0, 0
    drag = None
    running = True
    while running:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    running = False
                elif e.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5):
                    cam.preset(e.key - pygame.K_0)
                elif e.key == pygame.K_r:
                    rig.reload(); state["haze"] = rig.settings.get("HAZE", 0.1)
                elif e.key == pygame.K_s:
                    state["shadows"] = not state["shadows"]
            elif e.type == pygame.MOUSEBUTTONDOWN:
                if e.button in (1, 2, 3):
                    drag = e.button
                elif e.button == 4:
                    cam.zoom(1)
                elif e.button == 5:
                    cam.zoom(-1)
            elif e.type == pygame.MOUSEBUTTONUP:
                drag = None
            elif e.type == pygame.MOUSEWHEEL:
                cam.zoom(e.y)
            elif e.type == pygame.MOUSEMOTION and drag:
                dx, dy = e.rel
                (cam.orbit if drag == 1 else cam.pan)(dx, dy)
        keys = pygame.key.get_pressed()
        if keys[pygame.K_UP]:
            state["haze"] = min(1.0, state["haze"] * 1.02 + 0.001)
        if keys[pygame.K_DOWN]:
            state["haze"] = max(0.0, state["haze"] / 1.02 - 0.001)

        size = pygame.display.get_window_size()
        now = time.monotonic() - t0
        if rig.poll():
            state["haze"] = rig.settings.get("HAZE", 0.1)
        if args.demo:
            apply_demo(rig, dmx, args.demo, now)
        rend.draw(ctx.screen, size, cam, rig, dmx, state, now)
        pygame.display.flip()
        clock.tick(args.fps)

        frames_since += 1
        if args.target_fps and now - last_adjust > 1.0:       # dynamic resolution
            fps_now = frames_since / (now - last_adjust)
            if fps_now < args.target_fps * 0.95 and rend.scale > 0.3:
                rend.set_scale(max(0.3, rend.scale * 0.85))
            elif fps_now > args.target_fps * 1.35 and rend.scale < max_scale:
                rend.set_scale(min(max_scale, rend.scale * 1.1))
            last_adjust, frames_since = now, 0

        if now - last_title > 0.5:
            dt = now - last_title
            ar = (dmx.counts["artnet"] - last_counts["artnet"]) / dt
            sc = (dmx.counts["sacn"] - last_counts["sacn"]) / dt
            last_counts, last_title = dict(dmx.counts), now
            src = "DEMO" if args.demo else f"Art-Net {ar:3.0f}/s  sACN {sc:3.0f}/s"
            pygame.display.set_caption(
                f"lightviz | {len(rig.fixtures)} fixtures | {src} | haze {state['haze']:.2f}"
                f"{'' if state['shadows'] else ' (no haze shadows)'} | {clock.get_fps():.0f} fps"
                f" | res {int(rend.scale * 100)}%")
    pygame.quit()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--rig", default=str(HERE / "fixtures.py"), help="rig file (default fixtures.py)")
    ap.add_argument("--demo", nargs="?", const="cycle", metavar="PATTERN",
                    help="self-driven levels: cycle | look | chase")
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="render scale, e.g. 0.75 (the maximum when --target-fps is on)")
    ap.add_argument("--haze-scale", type=float, default=0.5,
                    help="haze resolution relative to the render (default 0.5)")
    ap.add_argument("--samples", type=int, default=8, help="haze samples per beam (default 8)")
    ap.add_argument("--fps", type=int, default=60, help="frame-rate cap")
    ap.add_argument("--target-fps", type=float, default=30,
                    help="lower the resolution automatically to hold this (0 = off)")
    ap.add_argument("--view", type=int, default=1, choices=sorted(VIEWS))
    ap.add_argument("--no-artnet", action="store_true")
    ap.add_argument("--no-sacn", action="store_true")
    ap.add_argument("--headless", metavar="PNG", help="render one frame to PNG and exit")
    ap.add_argument("--wait", type=float, default=1.0, help="headless: seconds to listen first")
    ap.add_argument("--t", type=float, help="headless demo: fixed pattern time")
    ap.add_argument("--bench", type=int, nargs="?", const=30, metavar="N",
                    help="render N frames and report ms/frame (implies --headless)")
    args = ap.parse_args()

    if args.bench and not args.headless:
        args.headless = os.devnull if os.name != "nt" else "NUL"
        args.demo = args.demo or "look"
        args.wait = 0.0
    dmx = DMXInput(artnet=not args.no_artnet, sacn=not args.no_sacn)
    dmx.start()
    rig = Rig(args.rig, dmx)
    (run_headless if args.headless else run_window)(args, dmx, rig)


if __name__ == "__main__":
    main()
