"""Fixture model + rig loading.

Coordinates are metres.  Origin = centre of the stage floor.
    +x = stage-right as seen from the audience (screen-right)
    +y = up
    +z = toward the audience (downstage);  -z = upstage (the back wall)
"""
import importlib.util
import math
from dataclasses import dataclass

# Channel layouts.  A mode may also be a tuple of channel names; names other
# than dim/r/g/b/w are accepted and ignored (strobe, macro, ...).
MODES = {
    "dim":      ("dim",),
    "rgb":      ("r", "g", "b"),
    "rgbw":     ("r", "g", "b", "w"),
    "dim_rgb":  ("dim", "r", "g", "b"),
    "dim_rgbw": ("dim", "r", "g", "b", "w"),
}
WHITE = (1.0, 0.95, 0.88)   # what the W emitter looks like


def _norm(v):
    m = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / m for c in v)


@dataclass
class Wash:
    name: str
    universe: int
    address: int                      # 1-512
    mode: object = "rgb"
    pos: tuple = (0.0, 5.0, 0.0)
    # Orientation: give ONE of aim_at / direction / (pan, tilt)
    aim_at: tuple = None              # world point the beam centre hits
    direction: tuple = None           # world-space direction vector
    pan: float = 0.0                  # deg, 0 = toward upstage, + toward +x
    tilt: float = 0.0                 # deg from straight down (90 = horizontal)
    beam_angle: float = 40.0          # full cone angle in degrees (edge of beam)
    softness: float = 0.5             # 0 = hard edge ... 1 = fully feathered
    gain: float = 1.0                 # brightness multiplier
    color: tuple = (1.0, 1.0, 1.0)    # tint for fixtures with no colour channels
    curve: float = 1.0                # 1 = linear, 2 = square-law dimmer

    @property
    def channels(self):
        return MODES[self.mode] if isinstance(self.mode, str) else tuple(self.mode)

    @property
    def footprint(self):
        return len(self.channels)

    def aim(self):
        """Unit vector the beam points along."""
        if self.aim_at is not None:
            return _norm(tuple(a - p for a, p in zip(self.aim_at, self.pos)))
        if self.direction is not None:
            return _norm(self.direction)
        p, t = math.radians(self.pan), math.radians(self.tilt)
        return (math.sin(t) * math.sin(p), -math.cos(t), -math.sin(t) * math.cos(p))

    def cone(self):
        """(cos outer, cos inner) used by the shader's smoothstep."""
        outer = math.radians(self.beam_angle / 2.0)
        inner = outer * (1.0 - max(0.0, min(self.softness, 0.98)))
        return math.cos(outer), math.cos(inner)

    def rgb(self, dmx):
        """Linear RGB emitted for this universe's 512 bytes."""
        v = {}
        for i, ch in enumerate(self.channels):
            k = self.address - 1 + i
            if k < len(dmx):
                v[ch] = dmx[k] / 255.0
        dim = v.get("dim", 1.0)
        if any(c in v for c in "rgb"):
            base = (v.get("r", 0.0), v.get("g", 0.0), v.get("b", 0.0))
        else:
            base = self.color
        w = v.get("w", 0.0)
        out = []
        for c, wc in zip(base, WHITE):
            x = max(0.0, (c + w * wc) * dim)
            out.append((x ** self.curve) * self.gain)
        return tuple(out)

    def write(self, buf, rgb=(1.0, 1.0, 1.0), dim=1.0):
        """Write a colour into a 512-byte bytearray, whatever the mode is."""
        chs = self.channels
        has_dim = "dim" in chs
        for i, ch in enumerate(chs):
            k = self.address - 1 + i
            if ch == "dim":
                x = dim
            elif ch in "rgb" and len(ch) == 1:
                x = rgb["rgb".index(ch)] * (1.0 if has_dim else dim)
            else:
                x = 0.0
            buf[k] = int(round(max(0.0, min(1.0, x)) * 255))


class Patcher:
    """Auto-addressing helper:  rig.add("FOH 1", mode="dim_rgb", pos=..., ...)"""

    def __init__(self, universe=1, start=1):
        self.universe, self.next = universe, start
        self.fixtures = []

    def add(self, name, **kw):
        f = Wash(name=name, universe=self.universe, address=self.next, **kw)
        if self.next - 1 + f.footprint > 512:        # roll to the next universe
            self.universe, self.next = self.universe + 1, 1
            f.universe, f.address = self.universe, 1
        self.next = f.address + f.footprint
        self.fixtures.append(f)
        return f


SETTINGS = ("HAZE", "HAZE_ANISOTROPY", "PERSON", "AMBIENT", "EXPOSURE",
            "ARTNET_UNIVERSE_OFFSET")
MAX_FIXTURES = 32


def load_rig(path):
    """Execute the rig file fresh and return (fixtures, settings)."""
    spec = importlib.util.spec_from_file_location("rig_user", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fixtures = list(mod.FIXTURES)
    if len(fixtures) > MAX_FIXTURES:
        raise ValueError(f"{len(fixtures)} fixtures; the visualizer supports {MAX_FIXTURES}")
    for f in fixtures:
        if not isinstance(f, Wash):
            raise TypeError(f"FIXTURES contains {f!r}, expected Wash")
        if not 1 <= f.address <= 512 or f.address - 1 + f.footprint > 512:
            raise ValueError(f"{f.name}: address {f.address} (+{f.footprint}ch) out of range")
    settings = {k: getattr(mod, k) for k in SETTINGS if hasattr(mod, k)}
    return fixtures, settings
