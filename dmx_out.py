"""Send DMX as sACN (E1.31) or Art-Net.  Standard library only.

    from dmx_out import send
    send(DMX)                       # sACN to the visualizer on this computer
"""
import socket
import struct
import uuid

ACN_ID = b"ASC-E1.17\x00\x00\x00"
_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
_cid = uuid.uuid4().bytes
_seq = 0


def build_artnet(universe, data, seq):
    """universe = Art-Net port-address (0-based)."""
    return (b"Art-Net\x00" + struct.pack("<H", 0x5000) + bytes([0, 14, seq, 0])
            + struct.pack("<BB", universe & 0xFF, (universe >> 8) & 0x7F)
            + struct.pack(">H", 512) + bytes(data).ljust(512, b"\0")[:512])


def build_sacn(universe, data, seq, cid, name=b"lightviz", priority=100):
    data = bytes(data).ljust(512, b"\0")[:512]
    pkt = struct.pack(">HH", 0x0010, 0x0000) + ACN_ID                       # preamble
    pkt += struct.pack(">HI", 0x7000 | 622, 4) + cid                        # root layer
    pkt += struct.pack(">HI", 0x7000 | 600, 2) + name.ljust(64, b"\0")     # framing layer
    pkt += bytes([priority]) + struct.pack(">H", 0) + bytes([seq, 0]) + struct.pack(">H", universe)
    pkt += struct.pack(">H", 0x7000 | 523) + bytes([2, 0xA1])               # DMP layer
    pkt += struct.pack(">HHH", 0, 1, 513) + b"\0" + data
    return pkt


def send(universes, host="127.0.0.1"):
    """Send {universe: 512 bytes} once as sACN.  Real lights need this ~40x a second."""
    global _seq
    for u, buf in universes.items():
        _sock.sendto(build_sacn(u, buf, _seq, _cid), (host, 5568))
    _seq = (_seq + 1) % 256