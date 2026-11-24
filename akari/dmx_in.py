"""Dependency-free Art-Net and sACN (E1.31) DMX receivers.

Each protocol runs in a daemon thread and writes into a shared store of
512-byte universes.  Internal universe numbers follow the sACN convention
(first universe = 1).  Art-Net numbers are shifted by `artnet_offset`
(default 1, so Art-Net universe 0 -> universe 1, matching what most
consoles do when you "patch universe 1" on both protocols).
"""
import socket
import struct
import threading
import time

ARTNET_PORT = 6454
SACN_PORT = 5568
ACN_ID = b"ASC-E1.17\x00\x00\x00"


def parse_artnet(pkt):
    """Return (artnet_universe, data) for an ArtDmx packet, else None."""
    if len(pkt) < 18 or pkt[:8] != b"Art-Net\x00":
        return None
    if (pkt[8] | (pkt[9] << 8)) != 0x5000:  # OpDmx, little-endian
        return None
    universe = (pkt[15] << 8) | pkt[14]  # Net << 8 | SubUni
    length = (pkt[16] << 8) | pkt[17]
    return universe, pkt[18:18 + length]


def parse_sacn(pkt):
    """Return (universe, data) for an E1.31 data packet, else None."""
    if len(pkt) < 126 or pkt[4:16] != ACN_ID:
        return None
    if struct.unpack_from(">I", pkt, 18)[0] != 4:   # root vector: data
        return None
    if struct.unpack_from(">I", pkt, 40)[0] != 2:   # framing vector: data
        return None
    universe = struct.unpack_from(">H", pkt, 113)[0]
    count = struct.unpack_from(">H", pkt, 123)[0]   # includes start code
    if pkt[125] != 0:                               # only DMX start code 0
        return None
    return universe, pkt[126:125 + count]


def _udp_socket(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    s.bind(("", port))
    s.settimeout(0.25)
    return s


class DMXInput:
    def __init__(self, artnet=True, sacn=True, artnet_offset=1):
        self.use_artnet = artnet
        self.use_sacn = sacn
        self.artnet_offset = artnet_offset
        self.counts = {"artnet": 0, "sacn": 0}
        self.last_rx = {}            # universe -> time.monotonic()
        self._u = {}                 # universe -> bytes(512)
        self._stop = threading.Event()
        self._sacn_sock = None
        self._joined = set()

    # ---- public API -------------------------------------------------
    def start(self):
        if self.use_artnet:
            self._spawn("artnet", ARTNET_PORT, self._on_artnet)
        if self.use_sacn:
            self._sacn_sock = self._spawn("sacn", SACN_PORT, self._on_sacn)

    def stop(self):
        self._stop.set()

    def get(self, universe):
        return self._u.get(universe, bytes(512))

    def set(self, universe, data):
        """Inject data directly (used by --demo)."""
        self._store(universe, data)

    def join_sacn(self, universes):
        """Join the sACN multicast groups for these universes (idempotent)."""
        s = self._sacn_sock
        if s is None:
            return
        for u in set(universes) - self._joined:
            group = "239.255.%d.%d" % (u >> 8, u & 0xFF)
            try:
                mreq = socket.inet_aton(group) + socket.inet_aton("0.0.0.0")
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            except OSError as e:
                print(f"[dmx] could not join multicast {group}: {e}")
            self._joined.add(u)

    # ---- internals --------------------------------------------------
    def _store(self, universe, data):
        buf = bytearray(512)
        n = min(len(data), 512)
        buf[:n] = data[:n]
        self._u[universe] = bytes(buf)
        self.last_rx[universe] = time.monotonic()

    def _on_artnet(self, pkt):
        r = parse_artnet(pkt)
        if r:
            self._store(r[0] + self.artnet_offset, r[1])
            self.counts["artnet"] += 1

    def _on_sacn(self, pkt):
        r = parse_sacn(pkt)
        if r:
            self._store(r[0], r[1])
            self.counts["sacn"] += 1

    def _spawn(self, name, port, handler):
        try:
            sock = _udp_socket(port)
        except OSError as e:
            print(f"[dmx] cannot listen for {name} on UDP {port}: {e}")
            return None

        def loop():
            while not self._stop.is_set():
                try:
                    pkt, _ = sock.recvfrom(1500)
                except socket.timeout:
                    continue
                except OSError:
                    break
                handler(pkt)

        threading.Thread(target=loop, name=f"dmx-{name}", daemon=True).start()
        print(f"[dmx] listening for {name} on UDP {port}")
        return sock
