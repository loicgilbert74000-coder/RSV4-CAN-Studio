"""Test « singe » : clics, glissements, molette, frappes et changements de page aléatoires sur toute l'application.

Chaque action est journalisée avant d'être exécutée : si l'application plante, la dernière ligne désigne la cause."""

import random
import time

from PySide6 import QtCore, QtGui, QtTest, QtWidgets

from .widgets_qt import DeckButton, DeckLcd, GearButton, NavTab, Qt

QPoint, QPointF = QtCore.QPoint, QtCore.QPointF


def _mouse(widget, kind, pos, button=Qt.LeftButton, buttons=Qt.LeftButton):
    ev = QtGui.QMouseEvent(kind, QPointF(pos), QPointF(widget.mapToGlobal(pos)), button, buttons, Qt.NoModifier)
    QtWidgets.QApplication.sendEvent(widget, ev)


def _drag(widget, a, b, steps=6):
    _mouse(widget, QtCore.QEvent.MouseButtonPress, a)
    for i in range(1, steps + 1):
        p = QPoint(int(a.x() + (b.x() - a.x()) * i / steps), int(a.y() + (b.y() - a.y()) * i / steps))
        _mouse(widget, QtCore.QEvent.MouseMove, p, Qt.NoButton, Qt.LeftButton)
    _mouse(widget, QtCore.QEvent.MouseButtonRelease, b, Qt.LeftButton, Qt.NoButton)


def _wheel(widget, pos, delta):
    ev = QtGui.QWheelEvent(QPointF(pos), QPointF(widget.mapToGlobal(pos)), QPoint(0, 0), QPoint(0, delta),
                           Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QtWidgets.QApplication.sendEvent(widget, ev)


def _rand_pos(rnd, w):
    return QPoint(rnd.randint(2, max(3, w.width() - 3)), rnd.randint(2, max(3, w.height() - 3)))


def run(app, win, pump, steps, seed=1, log=print):
    rnd = random.Random(seed)
    core = win.core
    g = win.graph
    # aucune boîte de dialogue bloquante pendant le test
    for name in ("showinfo", "showwarning", "showerror"):
        setattr(core.dlg, name, lambda *a, **k: None)
    for name in ("askokcancel", "askyesno"):
        setattr(core.dlg, name, lambda *a, **k: True)
    core.dlg.askopenfilename = lambda *a, **k: ""
    core.dlg.asksaveasfilename = lambda *a, **k: ""
    core.dlg.askdirectory = lambda *a, **k: ""
    QtWidgets.QDialog.exec = lambda self, *a: 0
    n_done = 0

    def clickables():
        out = []
        for w in win.findChildren(QtWidgets.QWidget):
            if not w.isVisible() or w.width() < 6 or w.height() < 6 or not w.isEnabled():
                continue
            if isinstance(w, (QtWidgets.QAbstractButton, NavTab, DeckButton, GearButton)):
                out.append(w)
        return out

    def act_legend():
        rows = list(g._rows.values())
        if not rows or not g.isVisible():
            return "légende : rien"
        row = rnd.choice(rows)
        if rnd.random() < 0.7:
            log(f"  légende ✕ {row.key}")
            QtTest.QTest.mouseClick(row.x, Qt.LeftButton)
        else:
            log(f"  légende ligne {row.key}")
            QtTest.QTest.mouseClick(row, Qt.LeftButton, Qt.NoModifier, QPoint(8, 8))
        return None

    def act_list():
        if not g.isVisible() or not g.list.items:
            return "liste : rien"
        key = rnd.choice(list(g.list.items))
        child = g.list.items[key][0]
        top = child.parent()
        if top is not None and not top.isExpanded():
            top.setExpanded(True)
        g.list.scrollToItem(child)
        rect = g.list.visualItemRect(child)
        log(f"  liste {key}")
        QtTest.QTest.mouseClick(g.list.viewport(), Qt.LeftButton, Qt.NoModifier, rect.center())
        return None

    def act_stack():
        b = rnd.choice([g.b_over, g.b_stack])
        log(f"  mode {b.text()}")
        QtTest.QTest.mouseClick(b, Qt.LeftButton)

    def act_plot():
        if not g.isVisible():
            return "courbes : rien"
        vp = g.gl.viewport()
        kind = rnd.choice(["clic", "glisser", "molette", "double", "curseur"])
        a, b = _rand_pos(rnd, vp), _rand_pos(rnd, vp)
        log(f"  courbes {kind} {a.x()},{a.y()} -> {b.x()},{b.y()}")
        if kind == "clic":
            QtTest.QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, a)
        elif kind == "glisser":
            _drag(vp, a, b)
        elif kind == "molette":
            _wheel(vp, a, rnd.choice([-240, -120, 120, 240]))
        elif kind == "double":
            QtTest.QTest.mouseDClick(vp, Qt.LeftButton, Qt.NoModifier, a)
        else:  # saisir la ligne du curseur
            if g.plots:
                x = g.plots[0].vb.mapViewToScene(QPointF(g.cursor_s(), 0)).x()
                pa = g.gl.mapFromScene(QPointF(x, a.y()))
                _drag(vp, pa, QPoint(pa.x() + rnd.randint(-120, 120), pa.y()))
        return None

    def act_splitter():
        sp = rnd.choice([g.split, g.lsplit])
        if not g.isVisible() or sp.count() < 2:
            return "volet : rien"
        h = sp.handle(rnd.randint(1, sp.count() - 1))
        c = QPoint(h.width() // 2, h.height() // 2)
        d = rnd.randint(-160, 160)
        log(f"  volet {d:+d}")
        _drag(h, c, QPoint(c.x() + d, c.y()) if sp.orientation() == Qt.Horizontal else QPoint(c.x(), c.y() + d))
        return None

    def act_generic():
        cl = clickables()
        if not cl:
            return "clic : rien"
        w = rnd.choice(cl)
        txt = getattr(w, "text", None)
        txt = txt() if callable(txt) else (txt or getattr(w, "label", "") or getattr(w, "caption", ""))
        log(f"  clic {type(w).__name__} {txt!r}")
        QtTest.QTest.mouseClick(w, Qt.LeftButton)
        return None

    def act_nav():
        tabs = [w for w in win.findChildren(NavTab) if w.isVisible()]
        if not tabs:
            return "onglet : rien"
        t = rnd.choice(tabs)
        log(f"  onglet {t.key}")
        QtTest.QTest.mouseClick(t, Qt.LeftButton)
        return None

    def act_deck():
        lcds = [w for w in win.findChildren(DeckLcd) if w.isVisible()]
        what = rnd.choice(["play", "pause", "seek", "vitesse", "lcd"])
        log(f"  platine {what}")
        if what == "play":
            core.play()
        elif what == "pause":
            core.pause()
        elif what == "seek":
            core.seek(rnd.random())
        elif what == "vitesse":
            core.speed.set(rnd.choice([0.5, 1.0, 2.0, 4.0]))
        elif lcds:
            w = lcds[0]
            QtTest.QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, _rand_pos(rnd, w))

    def act_type():
        edits = [w for w in win.findChildren(QtWidgets.QLineEdit) if w.isVisible() and not w.isReadOnly()]
        if not edits:
            return "saisie : rien"
        e = rnd.choice(edits)
        txt = rnd.choice(["1", "100", "2a0-2ff", "zz", "", "10,20", "-", "0x1"])
        log(f"  saisie {txt!r}")
        e.setFocus()
        e.selectAll()
        QtTest.QTest.keyClicks(e, txt)
        return None

    def act_other_views():
        # tableau des trames, grille de tuiles, jauges : clics et molette
        cands = [w for w in win.findChildren(QtWidgets.QAbstractScrollArea) if w.isVisible() and w.viewport().width() > 20]
        if not cands:
            return "vue : rien"
        w = rnd.choice(cands)
        vp = w.viewport()
        p = _rand_pos(rnd, vp)
        log(f"  vue {type(w).__name__} {p.x()},{p.y()}")
        if rnd.random() < 0.5:
            QtTest.QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, p)
        else:
            _wheel(vp, p, rnd.choice([-240, 240]))
        return None

    actions = ([act_legend] * 7 + [act_list] * 6 + [act_stack] * 2 + [act_plot] * 6 + [act_splitter] * 1 + [act_generic] * 4
               + [act_nav] * 2 + [act_deck] * 3 + [act_type] * 1 + [act_other_views] * 2)
    t0 = time.time()
    for i in range(steps):
        act = rnd.choice(actions)
        log(f"m{seed}.{i} {act.__name__}")
        try:
            act()
        except RuntimeError as e:  # objet Qt déjà détruit côté test : on le note et on continue
            log(f"  (ignoré : {e})")
        pump(app, rnd.choice([0.0, 0.01, 0.03, 0.08]))
        n_done += 1
        if i % 40 == 39:
            core.show_page(rnd.choice(["tele", "graph", "graph", "frames", "esp"]))
            pump(app, 0.1)
        if i % 90 == 89 and hasattr(win, "close_dialogs"):
            win.close_dialogs()
    log(f"singe (graine {seed}) : {n_done} actions en {time.time() - t0:.0f} s, aucun plantage")
