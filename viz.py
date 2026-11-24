#!/usr/bin/env python3
"""lightviz: 3D wash-light visualizer driven by Art-Net / sACN.

    python viz.py                     # listen for Art-Net + sACN, rig from fixtures.py
    python viz.py --demo              # animate the rig without any network input
    python viz.py --scale 0.5         # render at half resolution (slower GPUs)
    python viz.py --headless out.png --demo look   # render one frame to a PNG

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
BLIT = """
#version 330 core
uniform sampler2D uTex;
uniform vec2 uSize;
out vec4 c;
void main() { c = texture(uTex, gl_FragCoord.xy / uSize); }
"""

VIEWS = {   # yaw, pitch, distance, target
    1: (0.10, 0.34, 14.5, (0.0, 1.5, -0.3)),     # balcony, centre (default)
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
    def __init__(self, ctx, size, scale=1.0, steps=48):
        self.ctx, self.scale, self.steps = ctx, scale, steps
        src = (HERE / "scene.frag").read_text()
        self.scene = ctx.program(vertex_shader=VERT, fragment_shader=src)
        self.blit = ctx.program(vertex_shader=VERT, fragment_shader=BLIT)
        self.vao_scene = ctx.vertex_array(self.scene, [])
        self.vao_blit = ctx.vertex_array(self.blit, [])
        self.tex = self.fbo = None
        self.frame = 0
        self.resize(size)

    def resize(self, size):
        w = max(16, int(size[0] * self.scale))
        h = max(16, int(size[1] * self.scale))
        if self.tex is not None:
            self.tex.release()
            self.fbo.release()
        self.tex = self.ctx.texture((w, h), 4)
        self.tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.fbo = self.ctx.framebuffer([self.tex])

    def _set(self, name, value):
        if name in self.scene:
            self.scene[name].value = value

    def _set_array(self, name, arr):
        if name in self.scene:
            self.scene[name].write(np.ascontiguousarray(arr, dtype="f4").tobytes())

    def draw(self, target, size, cam, rig, dmx, state, t):
        fx = rig.fixtures
        n = len(fx)
        pos = np.zeros((MAX_FIXTURES, 3)); dr = np.zeros((MAX_FIXTURES, 3))
        col = np.zeros((MAX_FIXTURES, 3)); cone = np.ones((MAX_FIXTURES, 2))
        for i, f in enumerate(fx):
            pos[i], dr[i], cone[i] = f.pos, f.aim(), f.cone()
            col[i] = f.rgb(dmx.get(f.universe))
        s = rig.settings
        cp, right, up, fwd = cam.basis()
        self._set("uRes", self.fbo.size)
        self._set("uTime", t)
        self._set("uCamPos", tuple(cp)); self._set("uRight", tuple(right))
        self._set("uUp", tuple(up)); self._set("uFwd", tuple(fwd))
        self._set("uTanHalf", math.tan(math.radians(45.0) / 2))
        self._set("uCount", n)
        self._set_array("uLPos", pos); self._set_array("uLDir", dr)
        self._set_array("uLCol", col); self._set_array("uLCone", cone)
        self._set("uHaze", state["haze"])
        self._set("uHazeG", float(s.get("HAZE_ANISOTROPY", 0.35)))
        self._set("uPerson", tuple(s.get("PERSON", (0.0, 0.0, 0.8))))
        self._set("uAmbient", float(s.get("AMBIENT", 0.012)))
        self._set("uExposure", float(s.get("EXPOSURE", 1.0)))
        self._set("uVolSteps", int(self.steps))
        self._set("uHazeShadows", 1 if state["shadows"] else 0)
        self._set("uFrame", self.frame)
        self.frame += 1

        self.fbo.use()
        self.vao_scene.render(moderngl.TRIANGLES, vertices=3)
        target.use()
        target.viewport = (0, 0, size[0], size[1])
        self.tex.use(0)
        self.blit["uTex"].value = 0
        self.blit["uSize"].value = (float(size[0]), float(size[1]))
        self.vao_blit.render(moderngl.TRIANGLES, vertices=3)


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
    size = parse_size(args.size)
    out_tex = ctx.texture(size, 3)
    out = ctx.framebuffer([out_tex])
    rend = Renderer(ctx, size, args.scale, args.steps)
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
    rend.draw(out, size, cam, rig, dmx, state, 10.0)
    data = out.read(components=3)
    from PIL import Image
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
    rend = Renderer(ctx, size, args.scale, args.steps)
    cam = Camera(args.view)
    state = {"haze": rig.settings.get("HAZE", 0.1), "shadows": True}
    clock, t0 = pygame.time.Clock(), time.monotonic()
    last_title, last_counts, fps = 0.0, dict(dmx.counts), 0.0
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
        if rend.fbo.size != (max(16, int(size[0] * args.scale)), max(16, int(size[1] * args.scale))):
            rend.resize(size)
        now = time.monotonic() - t0
        if rig.poll():
            state["haze"] = rig.settings.get("HAZE", 0.1)
        if args.demo:
            apply_demo(rig, dmx, args.demo, now)
        rend.draw(ctx.screen, size, cam, rig, dmx, state, now)
        pygame.display.flip()
        clock.tick(args.fps)

        if now - last_title > 0.5:
            dt = now - last_title
            ar = (dmx.counts["artnet"] - last_counts["artnet"]) / dt
            sc = (dmx.counts["sacn"] - last_counts["sacn"]) / dt
            last_counts, last_title = dict(dmx.counts), now
            src = "DEMO" if args.demo else f"Art-Net {ar:3.0f}/s  sACN {sc:3.0f}/s"
            pygame.display.set_caption(
                f"lightviz | {len(rig.fixtures)} fixtures | {src} | haze {state['haze']:.2f}"
                f"{'' if state['shadows'] else ' (no haze shadows)'} | {clock.get_fps():.0f} fps")
    pygame.quit()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--rig", default=str(HERE / "fixtures.py"), help="rig file (default fixtures.py)")
    ap.add_argument("--demo", nargs="?", const="cycle", metavar="PATTERN",
                    help="self-driven levels: cycle | look | chase")
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--scale", type=float, default=1.0, help="render scale, e.g. 0.5")
    ap.add_argument("--steps", type=int, default=48, help="haze samples per pixel")
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--view", type=int, default=1, choices=sorted(VIEWS))
    ap.add_argument("--no-artnet", action="store_true")
    ap.add_argument("--no-sacn", action="store_true")
    ap.add_argument("--headless", metavar="PNG", help="render one frame to PNG and exit")
    ap.add_argument("--wait", type=float, default=1.0, help="headless: seconds to listen first")
    ap.add_argument("--t", type=float, help="headless demo: fixed pattern time")
    args = ap.parse_args()

    dmx = DMXInput(artnet=not args.no_artnet, sacn=not args.no_sacn)
    dmx.start()
    rig = Rig(args.rig, dmx)
    (run_headless if args.headless else run_window)(args, dmx, rig)


if __name__ == "__main__":
    main()
