"""Point d'entrée TrackLab (Qt).  python -m tracklab_qt.main  [--selftest fichier.trk dossier_sortie]"""

import base64
import os
import statistics
import sys
import time


def main():
    args = sys.argv[1:]
    selftest = "--selftest" in args
    if selftest:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        args.remove("--selftest")
    from PySide6 import QtWidgets

    from .theme_qt import QSS
    from .window import MainWindow

    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    win = MainWindow()
    if selftest:
        return run_selftest(app, win, args)
    win.show()
    if args:
        win.core.load(args[0])
    return app.exec()


def pump(app, secs):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def emit_image(name, pixmap):
    """Affiche une capture d'écran dans le journal (JPEG en base64) pour pouvoir la consulter sans téléchargement."""
    from PySide6 import QtCore

    pix = pixmap.scaledToWidth(1100, QtCore.Qt.SmoothTransformation)
    ba = QtCore.QByteArray()
    buf = QtCore.QBuffer(ba)
    buf.open(QtCore.QIODevice.WriteOnly)
    pix.save(buf, "JPG", 72)
    b64 = base64.b64encode(bytes(ba)).decode()
    print(f"@@IMG {name} {len(b64)}", flush=True)
    for i in range(0, len(b64), 3000):
        print("@@ " + b64[i:i + 3000], flush=True)
    print("@@END", flush=True)


def live_test(app, win):
    """Connexion Wi-Fi à un faux ESP32 local : vérifie réception, décodage, états et courbes en direct."""
    import socket
    import struct
    import threading

    from tracklab.protocol import WIFI_MAGIC, xor_sum

    core = win.core
    frames = list(core.frames[:6000])
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def serve():
        conn, _a = srv.accept()
        t0 = time.time()
        for i, (t, cid, data) in enumerate(frames):
            body = struct.pack("<IIB", int(t) & 0xFFFFFFFF, cid, len(data)) + bytes(data).ljust(8, b"\0")
            conn.sendall(WIFI_MAGIC + body + bytes([xor_sum(body)]))
            if i % 40 == 39:
                time.sleep(max(0.0, (i / 1500.0) - (time.time() - t0)))
        time.sleep(1.0)
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    core.dlg.askokcancel = lambda *a, **k: True
    core.transport.set("Wi-Fi ESP32")
    core.host.set("127.0.0.1")
    core.tcp_port.set(str(port))
    core.connect()
    for page in ("tele", "graph"):
        core.show_page(page)
        pump(app, 2.0)
        emit_image("live_" + page, win.grab())
    print(f"direct : {core.ingested} trames reçues, {len(core.vals)} valeurs, live={core.live}, "
          f"état={core.status.get()!r}", flush=True)
    assert core.ingested > 500, "aucune trame reçue en direct"
    core.disconnect()
    pump(app, 0.3)


def run_selftest(app, win, args):
    path = args[0]
    core = win.core
    win.resize(1536, 960)
    win.show()
    pump(app, 0.5)
    t0 = time.time()
    core.load(path)
    pump(app, 1.0)
    print(f"chargé : {len(core.frames)} trames, {len(core.full_t)} signaux, {time.time() - t0:.1f} s", flush=True)
    assert core.frames and core.full_t
    for page in ("tele", "graph", "frames", "esp"):
        core.show_page(page)
        if page == "graph":
            core.seek(0.35)
        pump(app, 1.2)
        emit_image(page, win.grab())
    # chronométrages de la page Courbes
    core.show_page("graph")
    pump(app, 0.8)
    g = win.graph
    p = g.plots[0]

    def bench(label, fn, n=15):
        ts = []
        for i in range(n):
            fn(i)
            app.processEvents()
            t = time.perf_counter()
            g.gl.grab()
            ts.append((time.perf_counter() - t) * 1000)
        print(f"{label:<40} med {statistics.median(ts):6.1f} ms  max {max(ts):6.1f}", flush=True)

    lo, hi = g.bounds()
    bench("courbes : tout le fichier", lambda i: g.set_view(lo + i * 0.2, hi))
    bench("courbes : fenêtre 30 s, déplacement", lambda i: g.set_view(5 + i * 0.3, 35 + i * 0.3))
    bench("courbes : zoom molette", lambda i: g.set_view(10, 10 + 30 * (0.9 ** i)))
    core.stack.set(True)
    g.build()
    pump(app, 0.3)
    emit_image("graph_empilees", win.grab())
    # lecture : fluidité de la boucle d'affichage
    core.stack.set(False)
    g.build()
    g.set_view(0, 30)
    core.speed.set(4.0)
    core.seek(0.0)
    core.play()
    gaps, last = [], time.perf_counter()
    end = time.time() + 3
    while time.time() < end:
        app.processEvents()
        now = time.perf_counter()
        gaps.append((now - last) * 1000)
        last = now
        time.sleep(0.004)
    gaps.sort()
    print(f"lecture x4 : pas de boucle med {gaps[len(gaps) // 2]:.1f} ms · p95 {gaps[int(len(gaps) * .95)]:.1f} · "
          f"max {gaps[-1]:.1f} ({len(gaps)} pas) · curseur {core.cursor_ms() / 1000:.1f} s", flush=True)
    core.pause()
    live_test(app, win)
    print("OK : TrackLab Qt", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
