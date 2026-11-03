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
        import faulthandler

        faulthandler.enable()  # un plantage Qt laisse au moins la pile Python dans le journal
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        args.remove("--selftest")
    from PySide6 import QtWidgets

    from .theme_qt import QSS
    from .window import MainWindow

    app = QtWidgets.QApplication(sys.argv)
    if os.environ.get("TRACKLAB_GC") != "auto":
        # Le ramasse-miettes automatique de Python peut se déclencher au beau milieu de la construction d'un objet Qt
        # (ou dans un thread) et détruire d'autres objets Qt à ce moment : plantage aléatoire. On le lance donc nous-mêmes,
        # depuis le fil de l'interface, entre deux événements.
        import gc

        from PySide6 import QtCore

        gc.disable()
        app._gc_timer = QtCore.QTimer()
        app._gc_timer.setInterval(1000)
        app._gc_timer.timeout.connect(lambda: gc.collect())
        app._gc_timer.start()
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    win = MainWindow()
    if selftest:
        return run_selftest(app, win, args)
    win.show()
    if args:
        win.core.load(args[0])
    return app.exec()


def say(m):
    """print robuste : la console Windows (cp1252) ne sait pas afficher tous les caractères."""
    print(str(m).encode("cp1252", "replace").decode("cp1252"), flush=True)


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


def ui_test(app, win):
    """Boîtes de dialogue, filtres, clic sur les courbes, aller-retour du paramétrage : rien ne doit lever d'exception."""
    from tracklab.espconfig import validate_cfg

    core = win.core
    win.open_connection_dialog()
    pump(app, 0.3)
    emit_image("dlg_connexion", win.conn_dlg.grab())
    win.conn_dlg.close()
    win.open_settings()
    pump(app, 0.3)
    emit_image("dlg_parametres", win._settings.grab())
    win._settings.close()
    win.open_choice()
    pump(app, 0.3)
    emit_image("dlg_ouvrir", win.open_dlg.grab())
    win.close_dialogs()
    cfg = core.cfg_from_vars()
    validate_cfg(cfg)
    core.cfg_to_vars(cfg)
    assert core.cfg_from_vars() == cfg, "paramétrage : aller-retour différent"
    core.show_page("frames")
    pump(app, 0.2)
    win.frames.ed["Afficher les ID (hex)"].setText("100")
    pump(app, 0.6)
    n1 = win.frames.model.rowCount()
    ids = {r[2] for r in win.frames.model.rows}
    print(f"filtre ID 100 : {n1} lignes, ids={sorted(ids)}", flush=True)
    assert ids <= {0x100}, "filtre d'ID inefficace"
    win.frames.reset_filters()
    pump(app, 0.6)
    core.show_page("graph")
    pump(app, 0.5)
    g = win.graph
    g.seek_to(20.0)
    pump(app, 0.3)
    print(f"clic sur les courbes : curseur à {core.cursor_ms() / 1000:.1f} s (attendu 20,0)", flush=True)
    assert abs(core.cursor_ms() / 1000 - 20.0) < 1.0
    first = g.selected()[1]
    core.ref_key = first
    g.refresh_ref()
    core.toggle_curve(g.selected()[0])
    pump(app, 0.5)
    print(f"retrait d'une courbe : {len(g.selected())} courbes restantes", flush=True)
    core.on_model("cbr1000rr_r_2021")
    pump(app, 0.5)
    core.on_model("rsv4")
    pump(app, 0.5)
    print("interface : dialogues, filtres, clics, modèles OK", flush=True)


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
    from . import monkey
    core.show_page("graph")
    monkey.run(app, win, pump, int(os.environ.get("TRACKLAB_MONKEY", "400")) // 2, seed=7, log=say)
    core.disconnect()
    pump(app, 0.3)


def first_open_test(app, win, path, page):
    """Après le chargement, la page Courbes doit montrer des courbes visibles sur tout le fichier (la page `page`
    est affichée au moment de l'ouverture)."""
    core, g = win.core, win.graph
    core.dlg.showwarning = lambda *a, **k: None
    # on repart d'un état vierge : aucun fichier chargé, aucune courbe
    core.show_page(page)
    pump(app, 0.5)
    core.load(path)
    pump(app, 1.5)
    core.show_page("graph")
    pump(app, 1.5)
    a, b = g.view_range()
    info = []
    for k, cv in g.curves.items():
        x, y = cv.getData()
        info.append((k, 0 if x is None else len(x), cv.isVisible()))
    say(f"première ouverture ({page}) : vue {a:.1f}…{b:.1f} s, {len(g.curves)} courbes, détail {info}")
    emit_image("premiere_ouverture_" + page, win.grab())
    vb = g.plots[0].vb
    img = g.gl.grab().toImage()
    bg = img.pixelColor(img.width() // 2, 4).rgb()
    w0, h0 = img.width(), img.height()
    drawn = sum(1 for x in range(int(w0 * .15), int(w0 * .95), 7) for y in range(10, h0 - 40, 7) if img.pixelColor(x, y).rgb() != bg)
    say(f"  zone des courbes : {vb.width():.0f}x{vb.height():.0f} px, {drawn} points non vides sur la grille")
    ci = g.gl.ci.geometry()
    say(f"  gl {g.gl.width()}x{g.gl.height()} viewport {g.gl.viewport().width()}x{g.gl.viewport().height()} "
        f"scroll {g.scroll.viewport().width()}x{g.scroll.viewport().height()} ci {ci.width():.0f}x{ci.height():.0f} "
        f"plots visibles {[p.isVisible() for p in g._pool_plots[:3]]} page visible {g.isVisible()} "
        f"plot0 {g.plots[0].geometry().width():.0f}x{g.plots[0].geometry().height():.0f}")
    assert vb.width() > 200 and vb.height() > 100, "zone des courbes de taille nulle"
    assert drawn > 150, "la zone des courbes est vide à l'écran"
    assert g.curves, "aucune courbe tracée après l'ouverture"
    assert all(n > 2 and vis for _k, n, vis in info), "courbe vide ou masquée"
    assert b - a > 60, "la vue n'englobe pas le fichier"


def stress_signals(app, win):
    """Sélectionne chaque signal (un par un, puis par lots) en superposé et en empilé : aucun ne doit faire planter."""
    core, g = win.core, win.graph
    core.show_page("graph")
    pump(app, 0.3)
    keys = [it[0] for _t, items in core.signal_groups() for it in items]
    before = list(core.sel)
    for k in list(core.sel):
        core.toggle_curve(k)
    pump(app, 0.2)
    n = 0
    for stacked in (False, True):
        core.stack.set(stacked)
        pump(app, 0.2)
        for k in keys:
            t, v = g.arrays(k)
            print(f"  stress {'empilé' if stacked else 'superposé'} {k!r} n={len(t)} "
                  f"min={float(v.min()) if len(v) else None} max={float(v.max()) if len(v) else None}", flush=True)
            core.toggle_curve(k)
            pump(app, 0.04)
            core.toggle_curve(k)
            pump(app, 0.02)
            n += 1
        for i in range(0, len(keys), 7):  # lots de 7 signaux
            batch = keys[i:i + 7]
            for k in batch:
                core.toggle_curve(k)
            pump(app, 0.1)
            for k in batch:
                core.toggle_curve(k)
            pump(app, 0.05)
    core.stack.set(False)
    for k in before:  # on rend la sélection d'origine
        core.toggle_curve(k)
    pump(app, 0.2)
    print(f"signaux : {n} sélections une à une + lots, superposé et empilé, sans plantage", flush=True)


def circuit_test(app, win):
    """Circuit : tracé complet dès l'ouverture, point qui suit le curseur, fond satellite si le réseau répond."""
    core, g = win.core, win.graph
    g.map.store.enabled = os.environ.get("TRACKLAB_NO_TILES") != "1"
    core.show_page("graph")
    win.resize(1536, 960)
    core.seek(0.2)
    pump(app, 5.0)
    pts = g.map.points()
    print(f"circuit : {len(pts)} points GPS tracés d'emblée, fond satellite : {len(g.map.store.mem)} tuiles, "
          f"échecs {sum(g.map.store.failed.values())}", flush=True)
    assert len(pts) > 50, "circuit non tracé à l'ouverture"
    a = g.map.position()
    core.seek(0.7)
    pump(app, 0.5)
    b = g.map.position()
    assert a != b, "le point ne suit pas le curseur"
    emit_image("circuit", g.map.grab())
    emit_image("graph_circuit", win.grab())
    core.show_page("tele")
    pump(app, 1.0)
    emit_image("compteurs", win.grab())
    core.show_page("graph")
    pump(app, 0.3)


def run_selftest(app, win, args):
    path = args[0]
    core = win.core
    win.resize(1536, 960)
    win.show()
    pump(app, 0.5)
    if os.environ.get("TRACKLAB_FIRST_OPEN"):
        first_open_test(app, win, path, os.environ["TRACKLAB_FIRST_OPEN"])
        return 0
    t0 = time.time()
    core.load(path)
    pump(app, 1.0)
    print(f"chargé : {len(core.frames)} trames, {len(core.full_t)} signaux, {time.time() - t0:.1f} s", flush=True)
    assert core.frames and core.full_t
    if os.environ.get("TRACKLAB_STRESS_ONLY"):
        for i in range(int(os.environ["TRACKLAB_STRESS_ONLY"])):
            stress_signals(app, win)
        print("STRESS OK", flush=True)
        return 0
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
    stress_signals(app, win)
    circuit_test(app, win)
    ui_test(app, win)
    from . import monkey
    win.show_page = getattr(win, "show_page", None)
    monkey.run(app, win, pump, int(os.environ.get("TRACKLAB_MONKEY", "400")), seed=1, log=say)
    core.stack.set(False)
    live_test(app, win)
    print("OK : TrackLab Qt", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
