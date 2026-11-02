"""Enregistrements Tracklab dans l'application : liste, téléchargement automatique, ouverture et suppression (ESP32 simulé)."""
import os
import sys
import tempfile
import time
from tkinter import messagebox

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracklab.protocol import ID_FILE_CTL, ID_FILE_DATA, ID_FILE_LIST, TRK_MAGIC, xor_sum


def record(t, cid, data):
    r = t.to_bytes(4, "little") + cid.to_bytes(2, "little") + bytes([len(data)]) + data.ljust(8, b"\0")
    return r + bytes([xor_sum(r)])


class Sock:
    def __init__(self):
        self.sent = []

    def sendall(self, b):
        self.sent.append(b.decode().strip())


def main():
    from tracklab.app import App

    app = App()
    app.root.update()
    app.REC_DIR = tempfile.mkdtemp()
    sock = Sock()
    app.wifi_sock = sock
    app.live = True
    app.esp = {"rec": False, "store": True, "sd": False, "rec_no": 0, "rec_bytes": 0, "free_mb": 1}
    payloads = {n: TRK_MAGIC + bytes(12) + b"".join(record(10 * i, 0x100 + i, bytes([n, i])) for i in range(30)) for n in (1, 2)}

    def feed_list(files):
        for n, size, cur in files:
            app.on_file_frame(ID_FILE_LIST, n.to_bytes(2, "little") + size.to_bytes(4, "little") + bytes([1 if cur else 0]))
        app.on_file_frame(ID_FILE_LIST, (0xFFFF).to_bytes(2, "little") + bytes(4) + bytes([0]))

    def serve(n):
        data = payloads[n]
        app.on_file_frame(ID_FILE_CTL, bytes([1]) + n.to_bytes(2, "little") + len(data).to_bytes(4, "little"))
        for i in range(0, len(data), 8):
            app.on_file_frame(ID_FILE_DATA, data[i:i + 8])
        app.on_file_frame(ID_FILE_CTL, bytes([2]) + n.to_bytes(2, "little") + (sum(data) & 0xFFFFFFFF).to_bytes(4, "little"))

    # la liste arrive : tout ce qui manque est demandé automatiquement, un fichier à la fois, sauf celui en cours
    feed_list([(1, len(payloads[1]), False), (2, len(payloads[2]), False), (3, 500, True)])
    assert sock.sent == ["GET 1"], sock.sent
    serve(1)
    assert sock.sent == ["GET 1", "GET 2"], sock.sent
    serve(2)
    assert sock.sent == ["GET 1", "GET 2"], sock.sent  # le 3 est en cours : pas demandé
    assert len(os.listdir(app.REC_DIR)) == 2
    entries = app.rec_entries()
    assert [e["n"] for e in entries] == [3, 2, 1] and entries[1]["local"] and not entries[0]["local"]
    # une seconde liste identique ne redéclenche rien
    sock.sent.clear()
    feed_list([(1, len(payloads[1]), False), (2, len(payloads[2]), False)])
    assert sock.sent == []
    # ouverture d'une copie
    opened = []
    app.open_recording = lambda p: opened.append(p)
    app.rec_open_entry(entries[2])
    assert opened and opened[0].endswith(".trk")
    # fenêtre Ouvrir > Tracklab
    app.open_tracklab_dialog()
    app.root.update()
    tree = app.rec_trees[-1]
    assert len(tree.get_children()) == 2, tree.get_children()
    # suppression : carte + copie PC
    messagebox.askyesno = lambda *a, **k: True
    n_before = len(os.listdir(app.REC_DIR))
    app.rec_delete_entry(app.rec_entries()[0])
    assert len(os.listdir(app.REC_DIR)) == n_before - 1
    assert "DEL 2" in sock.sent, sock.sent
    # platine : pendant un enregistrement, le nom du fichier utilisé est affiché
    app.esp.update(rec=True, rec_no=7, rec_bytes=2048)
    app.link_t = int(time.monotonic() * 1000)
    app.update_deck(0, 100, 5000, "ok")
    assert app.lcd.s["name"] == "Fichier 0007.trk" and app.lcd.s["rec"], app.lcd.s
    print("OK : enregistrements Tracklab")


if __name__ == "__main__":
    main()
