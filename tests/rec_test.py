"""Test du protocole d'enregistrement : fichier .trk, liste et téléchargement (sans interface graphique)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracklab.protocol import ID_FILE_CTL, ID_FILE_DATA, ID_FILE_LIST, TRK_MAGIC, parse_trk, xor_sum  # noqa: E402


def record(t, cid, data):
    r = t.to_bytes(4, "little") + cid.to_bytes(2, "little") + bytes([len(data)]) + data.ljust(8, b"\0")
    return r + bytes([xor_sum(r)])


def main():
    body = record(0, 0x123, b"\1\2\3") + record(10, 0x7F8, b"\0" * 6) + record(20, 0x100, bytes(range(8)))
    bad = bytearray(record(30, 0x200, b"\x09"))
    bad[3] ^= 0xFF  # enregistrement corrompu : ignoré
    data = TRK_MAGIC + bytes(12) + body + bytes(bad)
    frames = parse_trk(data)
    assert [(t, c) for t, c, _ in frames] == [(0, 0x123), (10, 0x7F8), (20, 0x100)], frames
    assert frames[0][2] == b"\1\2\3" and frames[2][2] == bytes(range(8))
    try:
        parse_trk(b"XXXX" + bytes(40))
    except ValueError:
        pass
    else:
        raise AssertionError("un fichier sans « TRK1 » doit être refusé")
    print("OK : fichier .trk")


if __name__ == "__main__":
    main()
