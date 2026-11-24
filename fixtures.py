"""Your rig.  Edit and save while the visualizer is running: it reloads itself.

Coordinates are metres, origin = centre of the stage floor:
    +x = screen-right from the audience, +y = up, +z = toward the audience.
The stage deck is x -5..5, z -4..3; the back wall is at z = -4.5.
"""
from fixture import Patcher

# ---- environment ------------------------------------------------------
HAZE = 0.07                    # haze density, 0 = none
HAZE_ANISOTROPY = 0.35         # 0 = even glow, ->1 = bright when looking into a light
PERSON = (0.0, 0.0, 0.8)       # where the guy stands
AMBIENT = 0.012                # tiny "spill" so nothing is pure black
EXPOSURE = 1.0
ARTNET_UNIVERSE_OFFSET = 1     # Art-Net universe 0 -> our universe 1 (sACN 1)

# ---- rig ----------------------------------------------------------------
rig = Patcher(universe=1, start=1)        # fixtures get addressed in order

# Front light: four 4-ch (dim, r, g, b) washes on the FOH rail, aimed at the stage
for i, x in enumerate((-4.5, -1.5, 1.5, 4.5)):
    rig.add(f"FOH {i+1}", mode="dim_rgb",
            pos=(x, 5.5, 9.0), aim_at=(x * 0.45, 1.0, 0.8),
            beam_angle=34, gain=1.2)

# Backlight: four 3-ch RGB washes upstage of the actor, shining toward the house
for i, x in enumerate((-3.0, -1.0, 1.0, 3.0)):
    rig.add(f"Back {i+1}", mode="rgb",
            pos=(x, 6.2, -1.8), aim_at=(x * 0.6, 0.8, 1.6),
            beam_angle=30, gain=1.3)

# Side light from the booms: single-channel dimmers with a coloured gel
rig.add("Side L", mode="dim", color=(1.0, 0.55, 0.2),
        pos=(-6.0, 3.0, 0.8), aim_at=(0.0, 1.2, 0.8), beam_angle=28, gain=1.6)
rig.add("Side R", mode="dim", color=(0.25, 0.5, 1.0),
        pos=(6.0, 3.0, 0.8), aim_at=(0.0, 1.2, 0.8), beam_angle=28, gain=1.6)

# Ground-row washes grazing the back wall (pan/tilt style orientation)
for i, x in enumerate((-3.5, 0.0, 3.5)):
    rig.add(f"Cyc {i+1}", mode="rgb",
            pos=(x, 0.15, -3.6), direction=(0.0, 1.0, -0.18),
            beam_angle=70, softness=0.8, gain=1.0)

FIXTURES = rig.fixtures
