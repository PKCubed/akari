from fixtures import FIXTURES
from fixture import by_name, DMX
from dmx_out import send

rig = by_name(FIXTURES)

rig["FOH 1"].set_color(255, 0, 0)
rig["FOH 1"].set_dimmer(255)
rig["Back 2"].set_color(0, 0, 255)
rig["Side L"].set_dimmer(200)

send(DMX)