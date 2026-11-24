from akari.fixture import by_name, DMX
from akari.dmx_out import send
from fixtures import FIXTURES
import time

rig = by_name(FIXTURES)

r = 0

while True:
    r += 10
    if r > 255:
        r = 0
    rig["Spot 1"].set_color(r, 0, 0)
    send(DMX)
    time.sleep(0.05)
    

