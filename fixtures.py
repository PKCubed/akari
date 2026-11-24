"""Your rig.  Edit and save while the visualizer is running: it reloads itself.
Your own code can use it too:   from fixtures import FIXTURES

Coordinates are metres, origin = centre of the stage floor:
    +x = screen-right from the audience, +y = up, +z = toward the audience.
The stage deck is x -5..5, z -4..3; the back wall is at z = -4.5.
"""
from akari.fixture import Wash, check_patch

# ---- environment (visualizer only) -----------------------------------------
HAZE = 0.07                    # haze density, 0 = none
HAZE_ANISOTROPY = 0.35         # 0 = even glow, ->1 = bright when looking into a light
PERSON = (0.0, 0.0, 0.8)       # where the guy stands
AMBIENT = 0.012                # tiny "spill" so nothing is pure black
EXPOSURE = 1.0
ARTNET_UNIVERSE_OFFSET = 1     # Art-Net universe 0 -> our universe 1 (sACN 1)

# ---- channel layouts ---------------------------------------------------------
# A layout is the fixture's channel names in DMX order.  The visualizer uses
# dim, r, g, b, w.  Any other name (strobe, macro, zoom...) is kept for your own
# code and ignored by the visualizer.  "-" marks a channel that does nothing.
DIM_RGB = ("dim", "r", "g", "b")
RGB     = ("r", "g", "b")
DIMMER  = ("dim",)
# More examples:
#   GBR_PAR   = ("g", "b", "r")                                  # odd colour order
#   SLIMPAR_7 = ("dim", "r", "g", "b", "w", "strobe", "macro")   # 7-channel LED par
#   RGBW_FX   = ("r", "g", "b", "w", "-", "dim")                 # gap, dimmer last

# ---- rig -----------------------------------------------------------------------
# Every fixture states its own universe + start address.  Order here doesn't matter.
# Orientation: aim_at=(x, y, z) point, direction=(x, y, z) vector, or pan=/tilt= degrees.
FIXTURES = check_patch([
    # Front light: FOH rail, aimed at the stage
    Wash("Spot 1", universe=1, address=1,  channels=DIM_RGB, pos=(-4.5, 5.5, 9.0), aim_at=(-2.025, 1.0, 0.8), beam_angle=34, gain=1.2),
])
