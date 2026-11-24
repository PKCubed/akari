#!/usr/bin/env python3
"""Send test DMX to the visualizer (or any Art-Net / sACN node).

    python akari/send_test.py                       # sACN, cycling colours
    python akari/send_test.py --proto artnet --pattern chase
    python akari/send_test.py --pattern look --seconds 3
"""
import argparse
import socket
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                               # the folder with main.py and fixtures.py
sys.path.insert(0, str(ROOT))
from akari import patterns                       # noqa: E402
from akari.dmx_out import build_artnet, build_sacn  # noqa: E402
from akari.fixture import load_rig               # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proto", choices=("sacn", "artnet"), default="sacn")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--multicast", action="store_true", help="sACN: send to the multicast group")
    ap.add_argument("--rig", default=str(ROOT / "fixtures.py"))
    ap.add_argument("--pattern", default="cycle", choices=("cycle", "look", "chase"))
    ap.add_argument("--seconds", type=float, default=0, help="0 = run until Ctrl-C")
    ap.add_argument("--rate", type=float, default=30.0)
    args = ap.parse_args()

    fixtures, settings = load_rig(args.rig)
    offset = settings.get("ARTNET_UNIVERSE_OFFSET", 1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
    cid, seq, t0 = uuid.uuid4().bytes, 0, time.monotonic()
    print(f"sending {args.pattern} over {args.proto} to {args.host} ({len(fixtures)} fixtures)")
    try:
        while True:
            t = time.monotonic() - t0
            for u, buf in patterns.frame(fixtures, t, args.pattern).items():
                if args.proto == "artnet":
                    sock.sendto(build_artnet(u - offset, buf, seq), (args.host, 6454))
                else:
                    host = f"239.255.{u >> 8}.{u & 255}" if args.multicast else args.host
                    sock.sendto(build_sacn(u, buf, seq, cid), (host, 5568))
            seq = (seq + 1) & 0xFF
            if args.seconds and t > args.seconds:
                break
            time.sleep(1.0 / args.rate)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
