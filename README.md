# lightviz

A small 3D visualizer for DMX lights. Fixtures are defined in plain Python
(`fixtures.py`); levels arrive over Art-Net or sACN. Edit and save `fixtures.py`
while it runs and the view reloads itself.

## Setup
    pip install -r requirements.txt     # moderngl, pygame, numpy, pillow

## Run
    python viz.py                # listen for Art-Net (UDP 6454) and sACN (UDP 5568)
    python viz.py --demo         # self-animating, no network needed
    python send_test.py          # in another terminal: sends sACN test data
    python send_test.py --proto artnet --pattern chase

## Performance
The resolution drops automatically to hold 30 fps (`--target-fps 30`, `0` turns it off);
the title bar shows the fps and current resolution. Needs OpenGL 3.3.

    python viz.py --bench        # prints your GPU and ms/frame at 1280x720

At startup it prints `[gl] <renderer>`. If that says **llvmpipe** you're on software
rendering (the CPU), not your GPU: install/fix the graphics driver. On a laptop with an
NVIDIA GPU: `__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia python viz.py`.

Quality knobs: `--scale` (max render resolution, default 1.0), `--haze-scale` (haze
resolution relative to the render, default 0.5), `--samples` (haze samples per beam,
default 8). Lights at zero cost nothing.

## Controls
Mouse: left-drag orbit, right/middle-drag pan, wheel zoom.
Keys: 1-5 camera presets, UP/DOWN haze density, S haze shadows on/off, R reload, ESC quit.

## Rig file (`fixtures.py`)
Metres; origin = centre of the stage floor; +x screen-right from the house,
+y up, +z toward the audience. Deck is x -5..5, z -4..3; back wall at z = -4.5.

    rig = Patcher(universe=1, start=1)          # auto-addressing
    rig.add("FOH 1", mode="dim_rgb", pos=(-4.5, 5.5, 9), aim_at=(-2, 1, 0.8), beam_angle=34)
    rig.add("Cyc 1", mode="rgb", pos=(0, 0.15, -3.6), direction=(0, 1, -0.2))
    rig.add("Boom", mode="dim", color=(1, .5, .2), pos=(6, 3, 1), pan=-90, tilt=60)
    FIXTURES = rig.fixtures

Orientation: give one of `aim_at=(x,y,z)`, `direction=(x,y,z)`, or `pan`/`tilt`
(degrees; tilt 0 = straight down, 90 = horizontal; pan 0 = toward upstage).
Modes: `dim`, `rgb`, `rgbw`, `dim_rgb`, `dim_rgbw`, or your own tuple such as
`("dim","r","g","b","strobe")`. Extras: `softness`, `gain`, `curve`, `color`.

Universe numbering: fixtures use sACN-style numbers (first = 1). Art-Net universe 0
maps to universe 1 (`ARTNET_UNIVERSE_OFFSET = 1`; set 0 if your console counts differently).

## Files
    viz.py        window, camera, renderer, reload  fixture.py   Wash model + rig loader
    shaders/      surface, haze, composite passes   dmx_in.py    Art-Net / sACN receivers
    fixtures.py   YOUR RIG                        patterns.py  test looks
    send_test.py  test DMX sender
