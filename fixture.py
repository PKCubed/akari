"""Fixture definitions: the shared "what is plugged in where" model.

Used by the visualizer, and meant to be imported by your own code too.
It only needs the Python standard library.

Coordinates are metres.  Origin = centre of the stage floor.
    +x = stage-right as seen from the audience (screen-right)
    +y = up
    +z = toward the audience (downstage);  -z = upstage (the back wall)
"""
import importlib.util
import math
from dataclasses import dataclass

# Channel names the visualizer understands.  Any other name (strobe, macro,
# zoom, ...) is allowed: it is kept in the patch for your own code, and the
# visualizer ignores it.  "-" marks an unused channel.
VIZ_CHANNELS = ("dim", "r", "g", "b", "w")
ALIASES = {
    "intensity": "dim", "dimmer": "dim", "int": "dim", "i": "dim",
    "red": "r", "green": "g", "blue": "b", "white": "w",
    "": "-", "none": "-", "unused": "-",
}
# Shorthand layouts, so channels="dim_rgb" works as well as a tuple.
PRESETS = {
    "dim":      ("dim",),
    "rgb":      ("r", "g", "b"),
    "rgbw":     ("r", "g", "b", "w"),
    "dim_rgb":  ("dim", "r", "g", "b"),
    "dim_rgbw": ("dim", "r", "g", "b", "w"),
}
WHITE = (1.0, 0.95, 0.88)   # what the W emitter looks like

# What your code wants the lights to show: {universe: bytearray(512)}.
# set_color()/set_dimmer() write here; dmx_out.send(DMX) sends it.
DMX = {}

def _norm(v):
    m = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / m for c in v)


def _layout(name, spec):
    """Turn a preset name or a sequence of channel names into a clean tuple."""
    if isinstance(spec, str):
        if spec not in PRESETS:
            raise ValueError(f"{name}: unknown channel preset {spec!r}; use one of "
                             f"{sorted(PRESETS)} or a tuple such as ('dim', 'r', 'g', 'b')")
        return PRESETS[spec]
    try:
        raw = list(spec)
    except TypeError:
        raise TypeError(f"{name}: channels must be a preset name or a sequence of names") from None
    if not raw:
        raise ValueError(f"{name}: channels is empty")
    out = []
    for c in raw:
        key = "-" if c is None else str(c).strip().lower()
        out.append(ALIASES.get(key, key))
    for c in VIZ_CHANNELS:
        if out.count(c) > 1:
            raise ValueError(f"{name}: channel {c!r} appears {out.count(c)} times in {tuple(raw)}")
    return tuple(out)


@dataclass
class Wash:
    name: str
    address: int                      # DMX start address, 1-512
    universe: int = 1                 # sACN-style numbering (first universe = 1)
    channels: object = "rgb"          # preset name, or channel names in DMX order
    model: str = ""                   # free text, e.g. "Chauvet SlimPAR 56"
    pos: tuple = (0.0, 5.0, 0.0)
    # Orientation: give ONE of aim_at / direction / (pan, tilt)
    aim_at: tuple = None              # world point the beam centre hits
    direction: tuple = None           # world-space direction vector
    pan: float = 0.0                  # deg, 0 = toward upstage, + toward +x
    tilt: float = 0.0                 # deg from straight down (90 = horizontal)
    beam_angle: float = 40.0          # full cone angle in degrees (edge of beam)
    softness: float = 0.5             # 0 = hard edge ... 1 = fully feathered
    gain: float = 1.0                 # visualizer brightness multiplier
    color: tuple = (1.0, 1.0, 1.0)    # tint for fixtures with no colour channels (gel)
    curve: float = 1.0                # 1 = linear, 2 = square-law dimmer
    mode: object = None               # old name for `channels`, still accepted

    def __post_init__(self):
        n = self.name if isinstance(self.name, str) and self.name else repr(self.name)
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(f"fixture name must be a non-empty string, got {self.name!r}")
        if self.mode is not None:
            self.channels, self.mode = self.mode, None
        self.channels = _layout(n, self.channels)
        if not isinstance(self.universe, int) or not 1 <= self.universe <= 63999:
            raise ValueError(f"{n}: universe must be a whole number 1-63999, got {self.universe!r}")
        if not isinstance(self.address, int) or not 1 <= self.address <= 512:
            raise ValueError(f"{n}: address must be a whole number 1-512, got {self.address!r}")
        if self.end > 512:
            raise ValueError(f"{n}: {self.footprint} channels from address {self.address} "
                             f"would end at {self.end}, past 512")
        if len(self.pos) != 3:
            raise ValueError(f"{n}: pos must be (x, y, z)")
        if self.aim_at is not None and self.direction is not None:
            raise ValueError(f"{n}: give aim_at or direction, not both")
        self._rgb, self._dim = (255, 255, 255), 255

    # ---- control (values 0-255, written into DMX) ---------------------------
    def set(self, channel, value):
        """Set one channel by name:  f.set("strobe", 0)"""
        buf = DMX.setdefault(self.universe, bytearray(512))
        buf[self.addr(channel) - 1] = max(0, min(255, int(value)))

    def set_color(self, r, g, b):
        """Fixtures with no colour channels (gelled dimmers) ignore this."""
        self._rgb = (r, g, b)
        self._apply()

    def set_dimmer(self, value):
        """Uses the dim channel; on RGB-only fixtures it scales the colour."""
        self._dim = value
        self._apply()

    def _apply(self):
        k = 1.0 if "dim" in self.channels else self._dim / 255
        for ch, v in zip("rgb", self._rgb):
            if ch in self.channels:
                self.set(ch, v * k)
        if "dim" in self.channels:
            self.set("dim", self._dim)

    # ---- patch info (handy in your own code) ------------------------------
    @property
    def footprint(self):
        """Number of DMX channels the fixture uses."""
        return len(self.channels)

    @property
    def end(self):
        """Last DMX address the fixture uses."""
        return self.address + self.footprint - 1

    def has(self, channel):
        return ALIASES.get(channel, channel) in self.channels

    def addr(self, channel):
        """Absolute DMX address (1-512) of a named channel:  f.addr("r") -> 2"""
        c = ALIASES.get(channel, channel)
        if c not in self.channels:
            raise KeyError(f"{self.name} has no {channel!r} channel (it has {self.channels})")
        return self.address + self.channels.index(c)

    def channel_map(self):
        """{channel name: DMX address}, e.g. {'dim': 1, 'r': 2, 'g': 3, 'b': 4}"""
        out = {}
        for i, c in enumerate(self.channels):
            if c != "-":
                out.setdefault(c, self.address + i)
        return out

    # ---- used by the visualizer -------------------------------------------
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
            if ch in VIZ_CHANNELS and k < len(dmx):
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
        """Write a colour into a 512-byte bytearray (used by the test patterns).
        Channels other than dim/r/g/b are left untouched."""
        has_dim = "dim" in self.channels
        for i, ch in enumerate(self.channels):
            if ch == "dim":
                x = dim
            elif ch in ("r", "g", "b"):
                x = rgb["rgb".index(ch)] * (1.0 if has_dim else dim)
            else:
                continue
            buf[self.address - 1 + i] = int(round(max(0.0, min(1.0, x)) * 255))


# ---- whole-rig helpers ------------------------------------------------------
def check_patch(fixtures):
    """Raise ValueError if the rig has duplicate names or overlapping addresses.
    Two fixtures on exactly the same address with the same layout are allowed
    (that's a deliberate "mirror", like a two-fer).  Returns the list unchanged."""
    fixtures = list(fixtures)
    problems, seen = [], {}
    for f in fixtures:
        if not isinstance(f, Wash):
            raise TypeError(f"expected Wash, got {f!r}")
        if f.name in seen:
            problems.append(f"two fixtures are named {f.name!r}")
        seen[f.name] = f
    by_u = {}
    for f in fixtures:
        by_u.setdefault(f.universe, []).append(f)
    for u, fs in by_u.items():
        fs.sort(key=lambda f: f.address)
        for i, a in enumerate(fs):
            for b in fs[i + 1:]:
                if b.address > a.end:
                    break
                if b.address == a.address and b.channels == a.channels:
                    continue                                  # mirrored fixtures
                problems.append(f"{a.name} (U{u} {a.address}-{a.end}) overlaps "
                                f"{b.name} (U{u} {b.address}-{b.end})")
    if problems:
        raise ValueError("patch problems:\n  " + "\n  ".join(problems))
    return fixtures


def by_name(fixtures):
    """{name: fixture}, e.g. rig = by_name(FIXTURES); rig["FOH 1"].addr("r")"""
    return {f.name: f for f in fixtures}


SETTINGS = ("HAZE", "HAZE_ANISOTROPY", "PERSON", "AMBIENT", "EXPOSURE",
            "ARTNET_UNIVERSE_OFFSET")
MAX_FIXTURES = 32


def load_rig(path):
    """Execute the rig file fresh and return (fixtures, settings)."""
    spec = importlib.util.spec_from_file_location("rig_user", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fixtures = check_patch(mod.FIXTURES)
    if len(fixtures) > MAX_FIXTURES:
        raise ValueError(f"{len(fixtures)} fixtures; the visualizer supports {MAX_FIXTURES}")
    settings = {k: getattr(mod, k) for k in SETTINGS if hasattr(mod, k)}
    return fixtures, settings


def patch_table(fixtures):
    """Human-readable patch, for copying into a console.
    Channels in (brackets) are ones the visualizer ignores."""
    rows = [("Fixture", "Model", "Univ", "Addr", "Layout", "Note")]
    fs = sorted(fixtures, key=lambda f: (f.universe, f.address, f.name))
    first_at = {}
    for f in fs:
        key = (f.universe, f.address, f.channels)
        note = f"mirrors {first_at[key]}" if key in first_at else ""
        first_at.setdefault(key, f.name)
        layout = " ".join(c if c in VIZ_CHANNELS else f"({c})" for c in f.channels)
        rows.append((f.name, f.model, str(f.universe),
                     f"{f.address}-{f.end}" if f.end > f.address else str(f.address),
                     layout, note))
    w = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(c.ljust(w[i]) for i, c in enumerate(r)).rstrip() for r in rows]
    lines.insert(1, "  ".join("-" * x for x in w))
    return "\n".join(lines)
