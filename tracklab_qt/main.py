"""Point d'entrée TrackLab (Qt).  python -m tracklab_qt.main  [--selftest fichier.trk dossier_sortie]"""

import base64
import os
import statistics
import sys
import time


def install_crash_log():
    """Journal des plantages : %LOCALAPPDATA%/TrackLab/crash.log (pile Python même si Qt plante, exceptions non gérées)."""
    import faulthandler
    import threading
    import time
    import traceback

    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "TrackLab")
    try:
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "crash.log")
        if os.path.exists(path) and os.path.getsize(path) > 500_000:
            os.replace(path, path + ".old")
        f = open(path, "a", buffering=1, encoding="utf-8")
        f.write(f"\n===== démarrage {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
        faulthandler.enable(file=f, all_threads=True)
        keep = f
    except Exception:
        return None

    def log(kind, et, ev, tb):
        try:
            keep.write(f"\n--- {kind} {time.strftime('%H:%M:%S')} ---\n" + "".join(traceback.format_exception(et, ev, tb)))
        except Exception:
            pass

    def hook(et, ev, tb):
        log("exception", et, ev, tb)
        sys.__excepthook__(et, ev, tb)

    sys.excepthook = hook
    threading.excepthook = lambda a: log("thread " + str(a.thread), a.exc_type, a.exc_value, a.exc_traceback)
    return path


def main():
    args = sys.argv[1:]
    if "--selftest" not in args:
        install_crash_log()
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
    elif os.environ.get("TRACKLAB_NO_DEMO") != "1":
        # sans fichier demandé, l'appli s'ouvre sur la session RaceBox de démonstration
        from PySide6 import QtCore

        from .resources import demo_path

        demo = demo_path()
        if demo:
            QtCore.QTimer.singleShot(200, lambda: win.core.load(demo))
    return app.exec()


def say(m):
    """print robuste : la console Windows (cp1252) ne sait pas afficher tous les caractères."""
    print(str(m).encode("cp1252", "replace").decode("cp1252"), flush=True)


def pump(app, secs):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def emit_image(name, pixmap, width=1100, quality=None):
    """Affiche une capture d'écran dans le journal (JPEG en base64) pour pouvoir la consulter sans téléchargement."""
    from PySide6 import QtCore

    pix = pixmap.scaledToWidth(width, QtCore.Qt.SmoothTransformation)
    ba = QtCore.QByteArray()
    buf = QtCore.QBuffer(ba)
    buf.open(QtCore.QIODevice.WriteOnly)
    pix.save(buf, "JPG", quality or (72 if width <= 1100 else 82))
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


def demo_test(app, win):
    """Session RaceBox de démonstration : sélection par défaut, liste CAN épurée, tour affiché, zoom du circuit
    (suivi du point en lecture, déplacement), comparaison de deux fichiers."""
    from PySide6 import QtCore
    from PySide6.QtTest import QTest

    from .resources import demo_path

    core, g = win.core, win.graph
    demo = demo_path()
    assert demo, "session de démonstration introuvable"
    core.load(demo)
    pump(app, 2.0)
    core.show_page("graph")
    pump(app, 1.0)
    names = sorted(k[1] for k in core.sel)
    say(f"démo : courbes par défaut = {names}")
    assert set(names) == {"Angle", "G longitudinal", "G latéral (calculé)", "GPS Vitesse"}, names
    can = [k for t, lst in core.signal_groups() for k, _l, _ok in lst if core.signal_type(k) == "CAN moto"]
    say(f"démo : signaux CAN proposés = {len(can)}")
    assert not can, "des signaux CAN sans valeur sont encore proposés"
    core.seek(0.4)
    pump(app, 0.6)
    g.update_lap()
    info = core.lap_at(core.cursor_ms())
    say(f"démo : tour en cours = {info}, lignes du bandeau = {len(g.laps.rows())}")
    assert info and info[0] >= 1 and g.laps.rows() and g.laps.height() >= 24
    emit_image("demo_courbes", win.grab())
    m = g.map
    m.store.enabled = os.environ.get("TRACKLAB_NO_TILES") != "1"
    c0 = (m.zoom, m.center)
    m.set_zoom(5.0)
    pump(app, 1.5)
    assert m.zoom > 4.9 and m.center is not None, "zoom du circuit sans effet"
    emit_image("demo_circuit_zoom", m.grab())
    rng = m._lap_range(m._pts_ms, "")
    say(f"démo : circuit, tour en cours = points {rng} sur {len(m._pts)}")
    assert rng and (rng[1] - rng[0]) < len(m._pts) * 0.5, "le circuit trace tous les tours"
    before = m.center
    QTest.mousePress(m, QtCore.Qt.LeftButton, pos=QtCore.QPoint(m.width() // 2, m.height() // 2))
    QTest.mouseMove(m, QtCore.QPoint(m.width() // 2 + 60, m.height() // 2 + 40))
    QTest.mouseRelease(m, QtCore.Qt.LeftButton, pos=QtCore.QPoint(m.width() // 2 + 60, m.height() // 2 + 40))
    pump(app, 0.3)
    say(f"démo : déplacement du circuit {before} -> {m.center}")
    assert m.center != before, "le glisser ne déplace pas le circuit"
    # lecture : le point reste au centre, le zoom est conservé
    core.speed.set(8.0)
    core.seek(0.3)
    pump(app, 0.3)
    core.play()
    pump(app, 2.0)
    pos = m.position()
    assert m.zoom > 4.9, "le zoom n'est pas conservé en lecture"
    assert abs(m.center[0] - pos[0]) < 5e-4 and abs(m.center[1] - pos[1]) < 5e-4, (m.center, pos)
    emit_image("demo_circuit_lecture", m.grab())
    core.pause()
    m.reset_view()
    assert m.zoom == 1.0
    # comparaison
    core.load_compare(demo)
    pump(app, 2.5)
    assert core.compare_name and core.track_b, "comparaison non chargée"
    nb = [k for k in core.sel if k[1].endswith(" [B]")]
    assert len(nb) >= 3, nb
    core.seek(0.5)
    pump(app, 0.8)
    g.update_lap()
    assert len(g.laps.rows()) == 2 and core.lap_at(core.cursor_ms(), " [B]")
    # même couleur pour une voie A et sa jumelle B, y compris ajoutée à la main
    ka = next(k for k in core.sel if k[1] == "Angle")
    kb = next(k for k in core.sel if k[1] == "Angle [B]")
    assert core.color_of(ka) == core.color_of(kb)
    say(f"démo : comparaison temps, {len(core.track_b)} points B")
    emit_image("demo_comparaison", win.grab())
    core.set_compare_mode("gps")
    pump(app, 3.0)
    assert core.compare_mode == "gps" and core.track_b
    core.seek(0.5)
    pump(app, 0.8)
    pa, pb = m.position(), m.position_b()
    say(f"démo : comparaison GPS, A {pa} B {pb}")
    assert abs(pa[0] - pb[0]) < 5e-5 and abs(pa[1] - pb[1]) < 5e-5, "les deux points ne sont pas au même endroit"
    emit_image("demo_comparaison_gps", win.grab())
    core.end_compare()
    pump(app, 1.5)
    assert not core.compare_name and not [k for k in core.sel if k[1].endswith(" [B]")]
    # ---- page Analyse : tours, virages, écart, G-G, marqueurs, voie calculée, exports, circuit coloré
    import tempfile

    from .analyse_qt import add_math_channel

    an_page = win.analyse
    core.show_page("analyse")
    pump(app, 1.0)
    an_page.refresh(force=True)
    pump(app, 0.5)
    assert len(an_page.items) >= 4, f"tours trouvés : {len(an_page.items)}"
    assert an_page.t_laps.rowCount() >= 5
    say(f"analyse : {len(an_page.items)} tours, {an_page.l_best.text()}")
    assert "Meilleur tour 2:03" in an_page.l_best.text(), an_page.l_best.text()
    assert an_page.t_corn.rowCount() >= 5, "virages non détectés"
    assert an_page.cv_delta.getData()[0] is not None and len(an_page.cv_delta.getData()[0]) > 10, "écart de temps vide"
    assert len(an_page.sc_ref.data) > 100, "diagramme G-G vide"
    emit_image("analyse_tours", win.grab())
    for i in range(an_page.tabs.count()):
        an_page.tabs.setCurrentIndex(i)
        pump(app, 0.4)
        emit_image(f"analyse_onglet{i}", win.grab(), width=900)
    an_page.tabs.setCurrentIndex(1)
    pump(app, 0.3)
    r_ = an_page.p_over.getPlotItem().vb.sceneBoundingRect()
    an_page.on_hover(QtCore.QPointF(r_.center().x(), r_.center().y()), an_page.p_over)
    assert an_page.hv_over.isVisible() and "Réf" in an_page.l_hover.text(), an_page.l_hover.text()
    emit_image("analyse_survol", win.grab(), width=900)
    core.markers = [{"ms": 60000.0, "text": "Freinage tardif"}]
    an_page.fill_marks()
    win.graph.marks.refresh()
    assert an_page.t_marks.rowCount() == 1
    key = add_math_channel(core, "Vitesse m/s", "m/s", "[GPS Vitesse] / 3.6")
    assert key in core.full_t and key in core.sel and len(core.full_t[key]) > 100
    try:
        add_math_channel(core, "Pirate", "", "__import__('os').system('x')")
        raise AssertionError("formule dangereuse acceptée")
    except ValueError:
        pass
    outdir = tempfile.mkdtemp()
    for name, fn in (("tours.csv", an_page.export_laps), ("virages.csv", an_page.export_corners),
                     ("courbes.csv", an_page.export_curves), ("courbes.png", an_page.export_png), ("rapport.pdf", an_page.export_pdf)):
        path = os.path.join(outdir, name)
        an_page._ask = lambda *_a, _p=path: _p
        fn()
        assert os.path.exists(path) and os.path.getsize(path) > 200, f"export {name} absent"
    say("analyse : exports CSV / PNG / PDF créés")
    core.show_page("graph")
    pump(app, 0.8)
    g.set_view(100.0, 160.0)
    pump(app, 0.5)
    r_ = g.plots[0].vb.sceneBoundingRect()
    g.on_hover(QtCore.QPointF(r_.center().x(), r_.center().y()))
    assert g._pool_hover[0].isVisible() and "GPS Vitesse" in g.l_hover.text(), g.l_hover.text()
    say("survol : " + g.l_hover.text()[:160])
    emit_image("courbes_survol", win.grab(), width=1000)
    g.hover_off()
    win.graph.cmb_color.setCurrentIndex(1)
    win.graph.map.set_color_mode("speed")
    pump(app, 0.8)
    assert win.graph.map.color_values() is not None
    emit_image("demo_circuit_vitesse", win.grab())
    win.graph.map.set_color_mode(None)
    say("analyse : OK")
    # pas à pas au clavier (vraies touches envoyées à la fenêtre)
    core.pause()
    core.seek(0.3)
    pump(app, 0.5)
    t0 = core.cursor_ms()
    QTest.keyClick(win, QtCore.Qt.Key_Right)
    pump(app, 0.3)
    t1 = core.cursor_ms()
    QTest.keyClick(win, QtCore.Qt.Key_Right, QtCore.Qt.ShiftModifier)
    pump(app, 0.3)
    t2 = core.cursor_ms()
    QTest.keyClick(win, QtCore.Qt.Key_Left)
    pump(app, 0.3)
    t3 = core.cursor_ms()
    say(f"démo : pas à pas {t0:.0f} -> {t1:.0f} -> {t2:.0f} -> {t3:.0f} ms")
    assert t1 > t0 and t2 > t1 and t3 < t2, "les flèches n'avancent pas trame par trame"
    # noms A/B dans l'afficheur et boutons du bandeau
    assert core.key_open.isVisible() and core.key_open_b.isVisible()
    assert not hasattr(g, "b_openA")
    # courbes empilées : poignée entre deux courbes
    core.stack.set(True)
    pump(app, 1.0)
    if len(g.plots) >= 2:
        h_before = [p.sceneBoundingRect().height() for p in g.plots]
        vp = g.gl.viewport()
        e = g._row_edges()
        ymid = (e[0][1] + e[1][0]) / 2.0
        pos = g.gl.mapFromScene(QtCore.QPointF(60.0, ymid))
        assert g._handle_at(pos) == 0, "poignée introuvable"
        QTest.mousePress(vp, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, pos)
        QTest.mouseMove(vp, QtCore.QPoint(pos.x(), pos.y() + 40))
        QTest.mouseRelease(vp, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, QtCore.QPoint(pos.x(), pos.y() + 40))
        pump(app, 0.5)
        h_after = [p.sceneBoundingRect().height() for p in g.plots]
        say(f"démo : hauteurs {[round(x) for x in h_before[:2]]} -> {[round(x) for x in h_after[:2]]}")
        assert h_after[0] > h_before[0] + 20 and h_after[1] < h_before[1] - 20, "la poignée ne redimensionne pas"
    core.stack.set(False)
    pump(app, 0.5)
    say(f"démo : OK (zoom initial {c0})")


def emit_file(name, path):
    """Envoie un fichier binaire dans le journal (base64), comme les captures d'écran."""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    print(f"@@VID {name} {len(b64)}", flush=True)
    for i in range(0, len(b64), 3000):
        print("@@ " + b64[i:i + 3000], flush=True)
    print("@@END", flush=True)


def video_frames(app, win, sim):
    """Clips fluides (30 images/s) pour la vidéo (TRACKLAB_VIDEO_FRAMES=1) : l'état de l'appli est avancé image par image,
    sans dépendre de la vitesse de la machine, puis chaque clip est encodé en H.264 et envoyé dans le journal."""
    import csv
    import datetime
    import math
    import subprocess

    import imageio_ffmpeg

    from PySide6 import QtCore, QtGui

    from .resources import demo_path

    core, g = win.core, win.graph
    win.resize(1600, 960)
    win.show()
    pump(app, 0.5)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    CW, CH = 1440, 864

    def clip(name, seconds, step):
        """step(i, n) règle l'état de l'appli pour l'image i ; l'image est ensuite capturée et encodée."""
        n = int(seconds * 30)
        path = f"clip_{name}.mp4"
        ff = subprocess.Popen([ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{CW}x{CH}", "-r", "30",
                               "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", path],
                              stdin=subprocess.PIPE)
        for i in range(n):
            step(i, n)
            pump(app, 0.045)
            im = win.grab().toImage().scaled(CW, CH, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
            im = im.convertToFormat(QtGui.QImage.Format_RGB888)
            ff.stdin.write(bytes(im.constBits())[: CW * CH * 3])
        ff.stdin.close()
        ff.wait()
        emit_file(name, path)
        print(f"clip {name} : {n} images", flush=True)

    # --- télémétrie : les compteurs suivent les données
    core.load(sim)
    pump(app, 1.5)
    core.show_page("tele")
    clip("tele", 8, lambda i, n: core.seek(0.22 + 0.34 * i / n))
    # --- trames
    core.show_page("frames")
    win.frames.ed["Afficher les ID (hex)"].setText("100")
    pump(app, 0.5)
    clip("trames", 5, lambda i, n: core.seek(0.30 + 0.06 * i / n))
    win.frames.reset_filters()
    # --- courbes : une session qui tourne, circuit zoomé qui suit le point
    demo = demo_path()
    core.load(demo)
    pump(app, 2.0)
    core.show_page("graph")
    total = core.frames[-1][0]
    g.map.store.enabled = os.environ.get("TRACKLAB_NO_TILES") != "1"
    m = g.map
    core.seek(320000.0 / total)
    pump(app, 3.0)
    m.set_zoom(4.0)

    def play(t0, rate, seconds):
        def step(i, n):
            t = t0 + rate * i / 30.0
            core.seek(t * 1000.0 / total)
            g.set_view(t - 22, t + 8)
            m.center = m._clamp(m.position())
            m._refresh()
        return step

    clip("courbes", 10, play(320.0, 3.0, 10))
    # --- redimensionnement des panneaux
    m.reset_view()
    core.seek(0.40)
    g.set_view(core.cursor_ms() / 1000 - 25, core.cursor_ms() / 1000 + 25)
    pump(app, 1.0)
    sp, ls = g.split.sizes(), g.lsplit.sizes()
    T, TL = sum(sp), sum(ls)

    def resize(i, n):
        u = 0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1))
        a, c_ = int(sp[0] + 190 * u), int(sp[2] + 100 * u)
        g.split.setSizes([a, T - a - c_, c_])
        b = int(ls[0] + 200 * u)
        g.lsplit.setSizes([b, TL - b])

    clip("resize", 6, resize)
    g.split.setSizes(sp)
    g.lsplit.setSizes(ls)
    # --- comparaison : session B fictive (démo ralentie de 4 %)
    rows = list(csv.reader(open(demo, encoding="utf-8")))
    head, body = rows[0], rows[1:]
    ti, si = head.index("Time"), head.index("Speed")
    t0 = datetime.datetime.fromisoformat(body[0][ti].replace("Z", "+00:00"))
    out = [head]
    for r in body:
        t = datetime.datetime.fromisoformat(r[ti].replace("Z", "+00:00"))
        t2 = t0 + (t - t0) * 1.04
        r = list(r)
        r[ti] = t2.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t2.microsecond // 1000:03d}Z"
        r[si] = f"{float(r[si]) / 1.04 * (0.97 if int(r[head.index('Lap')]) == 3 else 1):.2f}"
        out.append(r)
    pb = os.path.join(os.path.dirname(sim) or ".", "session_B.csv")
    with open(pb, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(out)
    for mode, key, secs in (("time", "cmpt", 8), ("gps", "cmpg", 6)):
        if mode == "time":
            core.load_compare(pb, "time")
        else:
            core.set_compare_mode("gps")
        pump(app, 3.0)
        total = core.frames[-1][0]
        m.set_zoom(3.0)
        clip(key, secs, play(330.0, 3.0, secs))
    print("VIDEO FRAMES OK", flush=True)


def video_shots(app, win, sim):
    """Captures haute définition pour la vidéo de présentation (TRACKLAB_VIDEO_SHOTS=1)."""
    import csv
    import datetime

    from PySide6 import QtCore

    from .resources import demo_path

    core, g = win.core, win.graph
    win.resize(1600, 960)
    win.show()
    W = 1600

    def shot(name, widget=None):
        pump(app, 0.9)
        emit_image(name, (widget or win).grab(), W)

    # --- télémétrie et trames : capture CAN simulée
    core.load(sim)
    pump(app, 1.5)
    core.show_page("tele")
    core.seek(0.45)
    shot("v_tele")
    core.show_page("frames")
    core.seek(0.45)
    pump(app, 0.8)
    shot("v_trames")
    win.frames.ed["Afficher les ID (hex)"].setText("100")
    pump(app, 0.8)
    shot("v_trames_filtre")
    win.frames.reset_filters()
    core.show_page("esp")
    shot("v_param")
    # --- session de démonstration seule
    demo = demo_path()
    core.load(demo)
    pump(app, 2.0)
    core.show_page("graph")
    core.seek(0.40)
    g.map.store.enabled = os.environ.get("TRACKLAB_NO_TILES") != "1"
    pump(app, 5.0)
    shot("v_courbes")
    g.set_view(core.cursor_ms() / 1000 - 25, core.cursor_ms() / 1000 + 25)
    g.map.set_zoom(4.0)
    pump(app, 4.0)
    shot("v_courbes_zoom")
    # --- gestion des signaux : on ajoute des courbes, mode empilé
    for k in [k for k in core.full_t if k[1] in ("Altitude", "GyroZ")]:
        core.toggle_curve(k)
    pump(app, 0.8)
    shot("v_liste")
    core.stack.set(True)
    g.build()
    shot("v_empilees")
    for k in [k for k in core.full_t if k[1] in ("Altitude", "GyroZ")]:
        core.toggle_curve(k)
    core.stack.set(False)
    g.build()
    g.map.reset_view()
    # --- 2e session : la démo ralentie de 3 % (session B fictive, pour illustrer)
    rows = list(csv.reader(open(demo, encoding="utf-8")))
    head, body = rows[0], rows[1:]
    ti, si = head.index("Time"), head.index("Speed")
    t0 = datetime.datetime.fromisoformat(body[0][ti].replace("Z", "+00:00"))
    out = [head]
    for r in body:
        t = datetime.datetime.fromisoformat(r[ti].replace("Z", "+00:00"))
        t2 = t0 + (t - t0) * 1.04
        r = list(r)
        r[ti] = t2.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t2.microsecond // 1000:03d}Z"
        r[si] = f"{float(r[si]) / 1.04 * (0.97 if int(r[head.index('Lap')]) == 3 else 1):.2f}"
        out.append(r)
    pb = os.path.join(os.path.dirname(sim) or ".", "session_B.csv")
    with open(pb, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(out)
    core.load_compare(pb, "time")
    pump(app, 3.0)
    core.seek(0.45)
    g.set_view(core.cursor_ms() / 1000 - 40, core.cursor_ms() / 1000 + 40)
    pump(app, 1.0)
    shot("v_cmp_temps")
    core.set_compare_mode("gps")
    pump(app, 3.0)
    core.seek(0.45)
    g.set_view(core.cursor_ms() / 1000 - 40, core.cursor_ms() / 1000 + 40)
    g.map.set_zoom(3.0)
    pump(app, 3.0)
    shot("v_cmp_gps")
    print("VIDEO SHOTS OK", flush=True)


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
    if os.environ.get("TRACKLAB_VIDEO_FRAMES"):
        video_frames(app, win, path)
        return 0
    if os.environ.get("TRACKLAB_VIDEO_SHOTS"):
        video_shots(app, win, path)
        return 0
    if os.environ.get("TRACKLAB_DEMO_ONLY"):
        demo_test(app, win)
        print("DEMO OK", flush=True)
        return 0
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
    demo_test(app, win)
    live_test(app, win)
    print("OK : TrackLab Qt", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
