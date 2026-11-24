"""Test looks, used by `viz.py --demo` and `send_test.py`."""
import colorsys
import math

LOOKS = {                       # name prefix -> (r, g, b, dim)
    "FOH":  (1.0, 0.85, 0.65, 0.80),
    "Back": (0.25, 0.45, 1.0, 0.90),
    "Side": (1.0, 1.0, 1.0, 0.60),
    "Cyc":  (0.9, 0.2, 0.6, 0.55),
}


def frame(fixtures, t, pattern="cycle"):
    """Return {universe: bytearray(512)} for pattern at time t (seconds)."""
    out = {}
    n = max(len(fixtures), 1)
    for i, f in enumerate(fixtures):
        buf = out.setdefault(f.universe, bytearray(512))
        if pattern == "look":
            r, g, b, d = next((v for k, v in LOOKS.items() if f.name.startswith(k)),
                              (1, 1, 1, 0.5))
            f.write(buf, (r, g, b), d)
        elif pattern == "chase":
            d = max(0.0, math.sin(t * 2.5 - i * 0.9)) ** 2
            f.write(buf, (1.0, 0.9, 0.7), d)
        else:  # cycle: slow hue drift with a travelling swell
            r, g, b = colorsys.hsv_to_rgb((t * 0.04 + i / n) % 1.0, 0.85, 1.0)
            d = 0.65 + 0.35 * math.sin(t * 0.9 - i * 0.7)
            f.write(buf, (r, g, b), d)
    return out
