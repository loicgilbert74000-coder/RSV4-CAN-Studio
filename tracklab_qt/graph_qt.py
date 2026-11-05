"""Page Courbes (Qt + pyqtgraph) : superposées ou empilées, zoom à la molette, déplacement, curseur de lecture."""

import bisect
import math
import time

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from tracklab.config import WINDOWS
from tracklab.theme import BG, BORDER, CARD, CARD2, CYAN, GREEN, HOVER, MUTED, ORANGE, SUB, TEXT, YELLOW
from tracklab.util import fmt_val

from .satmap import ATTRIBUTION, MAX_TILES, MAX_Z, TileStore, choose_zoom, world_ll, world_px, world_px_np
from .widgets_qt import Card, GroupedSignalList, Label, Qt, font, painter, qc

def painter_on(pm):
    q = QtGui.QPainter(pm)
    q.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing | QtGui.QPainter.SmoothPixmapTransform)
    return q


POOL = 16  # tracés construits une fois pour toutes à l'ouverture (en créer plus tard faisait planter pyqtgraph)
SPLIT_QSS = (f"QSplitter::handle{{background:{BORDER};}}"
             f"QSplitter::handle:horizontal{{image:none;margin:0 3px;border-radius:2px;}}"
             f"QSplitter::handle:vertical{{margin:3px 0;border-radius:2px;}}"
             f"QSplitter::handle:hover{{background:{CYAN};}}"
             f"QSplitter::handle:pressed{{background:{CYAN};}}")
PEN_W = 1  # trait fin : le rendu logiciel de Qt est ~40 fois plus lent avec des traits épais


class TimeAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            m, s = divmod(max(0.0, v), 60)
            out.append(f"{int(m):02d}:{s:04.1f}" if spacing < 1 else f"{int(m):02d}:{int(s):02d}")
        return out


class RefAxis(pg.AxisItem):
    """Axe de gauche en mode superposé : les courbes sont normalisées (0..1), l'axe affiche l'échelle réelle de la
    courbe de référence."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.ref = None  # (lo, hi, [graduations réelles])

    def set_ref(self, ref, color):
        self.ref = ref
        self.setPen(qc(color or MUTED))
        self.setTextPen(qc(color or SUB))
        self.picture = None
        self.update()

    def tickValues(self, minVal, maxVal, size):
        if not self.ref:
            return super().tickValues(minVal, maxVal, size)  # mode empilé : graduations ordinaires
        lo, hi, ticks = self.ref
        span = (hi - lo) or 1.0
        return [(1.0, [(t - lo) / span for t in ticks])]

    def tickStrings(self, values, scale, spacing):
        if not self.ref:
            return super().tickStrings(values, scale, spacing)
        lo, hi, _t = self.ref
        return [f"{lo + v * (hi - lo):g}" for v in values]


class CircuitMap(QtWidgets.QWidget):
    """Circuit GPS sur fond satellite : tracé complet dès l'ouverture, point qui suit le curseur, zoom à la molette,
    déplacement en glissant, double-clic pour tout voir. Zoomé, la carte suit le point pendant la lecture."""

    MAXZOOM_STEP = 1.25

    def __init__(self, core):
        super().__init__()
        self.core = core
        self.store = TileStore(self)
        self.store.changed.connect(self._tiles_changed)
        self._base = None
        self._base_key = None
        self._geo = None  # (z, k, ox, oy) du dernier dessin
        self._shown = None
        self._last_geo = 0.0
        self._pts, self._pts_key, self._pts_t, self._pts_ms = None, None, 0.0, None
        self._ptsb, self._ptsb_ms, self._ptsb_key = [], None, None
        self._fit = None  # (clé, z0, k0, bbox, XA, YA, XB, YB) : emprise complète, pixels du monde au niveau z0
        self.zoom = 1.0
        self.center = None  # (lat, lon) du centre quand on est zoomé
        self._drag = None
        self._last_cursor = None
        self._file_key = None
        self.setMinimumHeight(110)
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Molette : zoom · glisser : déplacer · double-clic : tout voir")

    def _tiles_changed(self):
        self._base_key = None
        self.update()

    # ---------------------------------------------------------------- données
    def _file_mode(self):
        c = self.core
        return bool(not c.live and c.frames and c.track_full)

    def points(self):
        c = self.core
        file_mode = self._file_mode()
        key = (id(c.track_full), len(c.track_full), bool(file_mode), None if file_mode else len(c.track))
        now = time.monotonic()
        if key != self._pts_key and not (not file_mode and self._pts is not None and now - self._pts_t < 0.6):
            if file_mode:
                rows = [(t, la, lo) for t, la, lo in c.track_full if abs(la) > 1e-6 or abs(lo) > 1e-6]
                self._pts = [(la, lo) for _t, la, lo in rows]
                self._pts_ms = np.asarray([r[0] for r in rows], dtype=np.float64)
            else:
                self._pts = [q for q in list(c.track) if abs(q[0]) > 1e-6 or abs(q[1]) > 1e-6]
                self._pts_ms = None
            self._pts_key, self._pts_t = key, now
        return self._pts or []

    def points_b(self):
        c = self.core
        tb = getattr(c, "track_b", None)
        if not tb or not self._file_mode():
            self._ptsb, self._ptsb_ms, self._ptsb_key = [], None, None
            return []
        if self._ptsb_key != id(tb):
            rows = [(t, la, lo) for t, la, lo in tb if abs(la) > 1e-6 or abs(lo) > 1e-6]
            self._ptsb = [(la, lo) for _t, la, lo in rows]
            self._ptsb_ms = np.asarray([r[0] for r in rows], dtype=np.float64)
            self._ptsb_key = id(tb)
        return self._ptsb

    def _lap_range(self, ms_arr, suffix):
        """(début, fin) des indices du tracé pour le tour en cours ; None = tout le tracé (pas de tours dans le fichier)."""
        c = self.core
        if ms_arr is None:
            return None
        tab = c.lap_table(suffix)
        if not tab or not tab[0]:
            return None
        starts, _nums, _top = tab
        cur = c.cursor_ms()
        i = bisect.bisect_right(starts, cur) - 1
        t0 = starts[i] if i >= 0 else -1.0
        t1 = starts[i + 1] if i + 1 < len(starts) else float("inf")
        a = int(np.searchsorted(ms_arr, t0, side="left"))
        b = int(np.searchsorted(ms_arr, t1, side="left"))
        return max(0, a - 1), min(len(ms_arr), b + 1)

    def _interp(self, track, ts, t):
        i = bisect.bisect_right(ts, t)
        if i <= 0:
            return track[0][1], track[0][2]
        if i >= len(ts):
            return track[-1][1], track[-1][2]
        a, b = track[i - 1], track[i]
        f = (t - a[0]) / ((b[0] - a[0]) or 1)
        return a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f

    def position(self):
        c = self.core
        if self._file_mode():
            return self._interp(c.track_full, c.track_full_t, c.cursor_ms())
        return (c.track[-1][0], c.track[-1][1]) if c.track else None

    def position_b(self):
        c = self.core
        if getattr(c, "track_b", None) and self._file_mode():
            return self._interp(c.track_b, c.track_b_t, c.cursor_ms())
        return None

    # ---------------------------------------------------------------- vue : zoom, déplacement
    def _top(self):
        return 26, 14

    def _fit_info(self, pts, ptsb, w, h):
        """Emprise complète (A + B) : niveau de zoom z0 et échelle k0 pour tout voir ; pixels du monde des points."""
        top, pad = self._top()
        key = (id(self._pts), len(pts), len(ptsb), w, h, pts[-1] if pts else None)
        if self._fit and self._fit[0] == key:
            return self._fit
        allp = pts + ptsb
        lats, lons = [q[0] for q in allp], [q[1] for q in allp]
        la0, la1, lo0, lo1 = min(lats), max(lats), min(lons), max(lons)
        aw, ah = w - 2 * pad, h - top - pad
        z0 = choose_zoom(la0, la1, lo0, lo1, max(aw, 40), max(ah, 40))
        x0, y1 = world_px(la0, lo0, z0)
        x1, y0 = world_px(la1, lo1, z0)
        k0 = min(aw / max(x1 - x0, 1.0), ah / max(y1 - y0, 1.0))
        a = np.asarray(pts, dtype=np.float64)
        XA, YA = world_px_np(a[:, 0], a[:, 1], z0)
        if ptsb:
            b = np.asarray(ptsb, dtype=np.float64)
            XB, YB = world_px_np(b[:, 0], b[:, 1], z0)
        else:
            XB = YB = None
        self._fit = (key, z0, k0, (la0, la1, lo0, lo1), XA, YA, XB, YB)
        return self._fit

    def _zk(self, z0, k0, zoom):
        """Niveau de tuiles z et échelle k (pixels écran par pixel de tuile) pour un facteur de zoom."""
        dz = max(0, int(math.floor(math.log2(max(zoom, 1.0)) + 0.5)))
        z = min(MAX_Z, z0 + dz)
        return z, k0 * zoom / 2 ** (z - z0)

    def zoom_max(self):
        f = self._fit
        return 2.0 ** (MAX_Z - f[1] + 1) if f else 1.0

    def _geometry(self, pts, ptsb, w, h):
        _k, z0, k0, bbox, *_ = self._fit_info(pts, ptsb, w, h)
        top, pad = self._top()
        aw, ah = w - 2 * pad, h - top - pad
        z, k = self._zk(z0, k0, self.zoom)
        if self.zoom <= 1.0001 or self.center is None:
            x0, y1 = world_px(bbox[0], bbox[2], z)
            x1, y0 = world_px(bbox[1], bbox[3], z)
            cxw, cyw = (x0 + x1) / 2, (y0 + y1) / 2
        else:
            cxw, cyw = world_px(self.center[0], self.center[1], z)
        return z, k, w / 2 - cxw * k, top + ah / 2 - cyw * k + pad / 2

    def _centre_of(self, geo, w, h):
        """(lat, lon) du centre de la zone dessinée pour la géométrie donnée."""
        z, k, ox, oy = geo
        top, pad = self._top()
        ah = h - top - pad
        return world_ll((w / 2 - ox) / k, (top + ah / 2 + pad / 2 - oy) / k, z)

    def _ll_at(self, geo, sx, sy):
        z, k, ox, oy = geo
        return world_ll((sx - ox) / k, (sy - oy) / k, z)

    def set_zoom(self, zoom, sx=None, sy=None):
        """Change le zoom en gardant fixe le point de la carte situé sous (sx, sy) (centre par défaut)."""
        pts = self.points()
        if len(pts) < 2 or not self._geo:
            return
        w, h = self.width(), self.height()
        ptsb = self.points_b()
        geo = self._geometry(pts, ptsb, w, h)
        top, pad = self._top()
        if sx is None:
            sx, sy = w / 2, top + (h - top - pad) / 2 + pad / 2
        la, lo = self._ll_at(geo, sx, sy)
        zoom = max(1.0, min(self.zoom_max(), zoom))
        if zoom <= 1.0001:
            self.reset_view()
            return
        _k, z0, k0, *_ = self._fit
        z, k = self._zk(z0, k0, zoom)
        xw, yw = world_px(la, lo, z)
        ah = h - top - pad
        cx = xw - (sx - w / 2) / k
        cy = yw - (sy - (top + ah / 2 + pad / 2)) / k
        self.zoom = zoom
        self.center = self._clamp(world_ll(cx, cy, z))
        self._refresh()

    def _clamp(self, c):
        if not self._fit:
            return c
        la0, la1, lo0, lo1 = self._fit[3]
        mh, mw = (la1 - la0) * 0.1, (lo1 - lo0) * 0.1
        return max(la0 - mh, min(la1 + mh, c[0])), max(lo0 - mw, min(lo1 + mw, c[1]))

    def reset_view(self):
        self.zoom, self.center = 1.0, None
        self._refresh()

    def _refresh(self):
        self._base_key = None
        self._shown = None
        self.update()

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if not steps or len(self.points()) < 2:
            return
        p = e.position()
        self.set_zoom(self.zoom * self.MAXZOOM_STEP ** steps, p.x(), p.y())
        e.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._geo and len(self.points()) >= 2:
            c = self._centre_of(self._geo, self.width(), self.height())
            self._drag = (e.position().x(), e.position().y(), c, self._geo)
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if not self._drag or self.zoom <= 1.0001:
            return
        sx, sy, c0, geo = self._drag
        z, k, _ox, _oy = geo
        xc, yc = world_px(c0[0], c0[1], z)
        self.center = self._clamp(world_ll(xc - (e.position().x() - sx) / k, yc - (e.position().y() - sy) / k, z))
        self._refresh()

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, e):
        self.reset_view()

    def _follow(self):
        """Zoomé : la carte garde le point dans la vue (centré pendant la lecture)."""
        if self.zoom <= 1.0001 or self._drag or not self._geo:
            return
        pos = self.position()
        if not pos:
            return
        c = self.core
        if c.playing or c.live:
            self.center = self._clamp(pos)
            return
        cur = c.cursor_ms()
        moved = cur != self._last_cursor
        self._last_cursor = cur
        if not moved:  # à l'arrêt, on ne reprend pas la main sur un déplacement fait à la souris
            return
        pt = self._xy(self._geo, *pos)
        w, h = self.width(), self.height()
        if not (w * 0.15 < pt.x() < w * 0.85 and h * 0.2 < pt.y() < h * 0.85):
            self.center = self._clamp(pos)
            self._base_key = None

    def tick(self):
        c = self.core
        if id(c.track_full) != self._file_key:  # nouveau fichier : la vue repart sur le circuit entier
            self._file_key = id(c.track_full)
            self.zoom, self.center = 1.0, None
        if self.zoom > 1.0001:
            before = self.center
            self._follow()
            if self.center != before:
                self._base_key = None
        pos = self.position()
        st = (pos, self.position_b(), len(c.track), len(c.track_full), c.live, self.width(), self.height(), self.zoom, self.center)
        if st != self._shown:
            self._shown = st
            self.update()

    # ---------------------------------------------------------------- dessin
    def _xy(self, geo, la, lo):
        z, k, ox, oy = geo
        x, y = world_px(la, lo, z)
        return QtCore.QPointF(ox + x * k, oy + y * k)

    COLOR_MODES = (("Tracé uni", None), ("Couleur : vitesse", "speed"), ("Couleur : freinage / accélération", "long"),
                   ("Couleur : angle", "angle"))
    color_mode = None

    def set_color_mode(self, mode):
        self.color_mode = mode
        self._col_key = None
        self.update()

    def color_values(self):
        """Valeur colorée pour chaque point du tracé A (alignée sur points()), normalisée en [0, 1] ; None si indisponible."""
        c = self.core
        if not self.color_mode or self._pts_ms is None:
            return None
        key = (self.color_mode, id(c.full_t), len(self._pts_ms))
        if getattr(self, "_col_key", None) == key:
            return self._col_vals
        from .analyse_qt import core_get

        name = {"speed": "GPS Vitesse", "long": "G longitudinal", "angle": "Angle"}[self.color_mode]
        r = core_get(c)(name) or (core_get(c)(name + " (calculé)") if name != "GPS Vitesse" else None)
        vals = None
        if r is not None and len(r[0]) > 3:
            v = np.interp(self._pts_ms, r[0], np.nan_to_num(r[1]))
            if self.color_mode == "speed":
                lo, hi = float(np.percentile(v, 2)), float(np.percentile(v, 98))
                vals = (v - lo) / ((hi - lo) or 1.0)
            elif self.color_mode == "long":
                m = float(np.percentile(np.abs(v), 98)) or 1.0
                vals = 0.5 + 0.5 * np.clip(v / m, -1, 1)  # 0 = gros freinage, 1 = forte accélération
            else:
                m = float(np.percentile(np.abs(v), 98)) or 1.0
                vals = np.clip(np.abs(v) / m, 0, 1)
        self._col_key, self._col_vals = key, vals
        return vals

    @staticmethod
    def _ramp(x):
        """Bleu -> vert -> jaune -> rouge pour x entre 0 et 1."""
        x = float(min(1.0, max(0.0, x)))
        stops = [(0.0, (60, 130, 255)), (0.35, (40, 220, 140)), (0.65, (255, 220, 50)), (1.0, (255, 60, 50))]
        for (a, ca), (b, cb) in zip(stops, stops[1:]):
            if x <= b:
                u = (x - a) / (b - a)
                return QtGui.QColor(*[int(ca[i] + (cb[i] - ca[i]) * u) for i in range(3)])
        return QtGui.QColor(*stops[-1][1])

    def _trace(self, q, geo, X, Y, z0, w, h, color, rng=None, vals=None):
        """Trace une trace GPS (pixels du monde au niveau z0), ou seulement le tour en cours (rng = indices)."""
        z, k, ox, oy = geo
        if rng is not None:
            X, Y = X[rng[0]:rng[1]], Y[rng[0]:rng[1]]
            if vals is not None:
                vals = vals[rng[0]:rng[1]]
        if len(X) < 2:
            return
        f = 2.0 ** (z - z0) * k
        sx, sy = ox + X * f, oy + Y * f
        n = len(sx)
        if n > 2500:
            idx = np.unique(np.append(np.arange(0, n, max(1, n // 2500)), n - 1))
            sx, sy = sx[idx], sy[idx]
            if vals is not None:
                vals = vals[idx]
        vis = (sx > -20) & (sx < w + 20) & (sy > -20) & (sy < h + 20)
        conn = np.append((vis[:-1] | vis[1:]).astype(np.int32), 0)
        if not conn.any():
            return
        path = pg.functions.arrayToQPath(sx, sy, connect=conn)
        q.setBrush(Qt.NoBrush)
        q.setPen(QtGui.QPen(qc("#000000", 170), 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))  # liseré sombre : lisible sur l'image
        q.drawPath(path)
        if vals is not None and len(vals) == len(sx):
            nb = 24
            bins = np.clip((np.nan_to_num(vals) * nb).astype(int), 0, nb - 1)
            for b in range(nb):
                cb = (conn.astype(bool) & (bins == b)).astype(np.int32)
                if not cb.any():
                    continue
                q.setPen(QtGui.QPen(self._ramp((b + 0.5) / nb), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                q.drawPath(pg.functions.arrayToQPath(sx, sy, connect=cb))
            return
        q.setPen(QtGui.QPen(qc(color), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        q.drawPath(path)

    def _render_base(self, pts, ptsb, w, h):
        dpr = self.devicePixelRatioF()
        pm = QtGui.QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(qc(CARD))
        q = painter_on(pm)
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(QtCore.QRectF(0.5, 0.5, w - 1, h - 1), 10, 10)
        q.setClipPath(clip)
        geo = self._geometry(pts, ptsb, w, h)
        z, k, ox, oy = geo
        missing = 0
        n = 2 ** z
        tx0, tx1 = int(math.floor((0 - ox) / k / 256)), int(math.floor((w - ox) / k / 256))
        ty0, ty1 = int(math.floor((0 - oy) / k / 256)), int(math.floor((h - oy) / k / 256))
        if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) <= MAX_TILES:
            for ty in range(max(ty0, 0), min(ty1, n - 1) + 1):
                for tx in range(max(tx0, 0), min(tx1, n - 1) + 1):
                    tile = self.store.get(z, tx, ty)
                    if tile is None:
                        missing += 1
                        continue
                    q.drawPixmap(QtCore.QRectF(ox + tx * 256 * k, oy + ty * 256 * k, 256 * k + 0.6, 256 * k + 0.6), tile,
                                 QtCore.QRectF(tile.rect()))
        sat = len(self.store.mem) > 0 and missing < (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
        if sat:
            q.fillRect(QtCore.QRectF(0, 0, w, h), qc("#000000", 70))
        if sat:
            q.setFont(font(9))
            q.setPen(qc("#ffffff", 190))
            q.drawText(QtCore.QRectF(0, h - 16, w - 8, 14), Qt.AlignRight | Qt.AlignVCenter, ATTRIBUTION)
        q.end()
        return pm, geo

    def _dot(self, p, pos, color):
        pt = self._xy(self._geo, *pos)
        p.setPen(Qt.NoPen)
        p.setBrush(qc(color, 60))
        p.drawEllipse(pt, 11, 11)
        p.setBrush(qc("#ffffff"))
        p.drawEllipse(pt, 6.5, 6.5)
        p.setBrush(qc(color))
        p.drawEllipse(pt, 4.5, 4.5)

    def paintEvent(self, _e):
        p = painter(self)
        w, h = self.width(), self.height()
        pts = self.points()
        if len(pts) < 2:
            self._base = None
            p.setFont(font(12, True))
            p.setPen(qc(SUB))
            p.drawText(QtCore.QPointF(10, 18), "Circuit")
            p.setFont(font(12))
            p.setPen(qc(MUTED))
            p.drawText(QtCore.QRectF(0, 0, w, h), Qt.AlignCenter, "Pas de données GPS dans cette source")
            return
        c = self.core
        ptsb = self.points_b()
        key = (w, h, len(pts), pts[-1], pts[0], len(ptsb), len(self.store.mem), self.zoom, self.center)
        if key != self._base_key or self._base is None:
            now = time.monotonic()
            if c.live and self._base is not None and now - self._last_geo < 0.6:
                pass  # en direct, le fond n'est recalculé que de temps en temps
            elif c.playing and self._base is not None and self.zoom > 1.0001 and now - self._last_geo < 0.04:
                pass  # lecture zoomée : le fond suit le point à ~25 images/s, le reste du dessin reste fluide
            else:
                self._base, self._geo = self._render_base(pts, ptsb, w, h)
                self._base_key = key
                self._last_geo = now
        p.drawPixmap(0, 0, self._base)
        if self._geo and self._fit:
            _key, z0, _k0, _bb, XA, YA, XB, YB = self._fit
            if XB is not None:
                self._trace(p, self._geo, XB, YB, z0, w, h, ORANGE, self._lap_range(self._ptsb_ms, " [B]"))
            self._trace(p, self._geo, XA, YA, z0, w, h, CYAN, self._lap_range(self._pts_ms, ""), vals=self.color_values())
            s0 = self._xy(self._geo, *pts[0])  # départ
            p.setPen(QtGui.QPen(qc("#ffffff"), 2))
            p.setBrush(qc(BG))
            p.drawEllipse(s0, 4, 4)
        p.setFont(font(12, True))
        p.setPen(qc("#000000", 160))
        p.drawText(QtCore.QPointF(11, 19), "Circuit")
        p.setPen(qc(TEXT))
        p.drawText(QtCore.QPointF(10, 18), "Circuit")
        if self.zoom > 1.0001:
            p.setFont(font(10))
            p.setPen(qc(TEXT))
            p.drawText(QtCore.QRectF(0, 4, w - 10, 16), Qt.AlignRight | Qt.AlignVCenter, f"× {self.zoom:.1f} · double-clic : tout voir")
        pos = self.position()
        if self._geo:
            pb = self.position_b()
            if pb:
                self._dot(p, pb, ORANGE)
            if pos:
                self._dot(p, pos, GREEN)


class LegendRow(QtWidgets.QFrame):
    """Une ligne de la légende : nom, min … max, valeur au curseur, croix de suppression ; clic = axe de gauche."""

    def __init__(self, page, key, color):
        super().__init__()
        self.page, self.key, self.color = page, key, color
        self.setCursor(Qt.PointingHandCursor)
        lay = QtWidgets.QGridLayout(self)
        lay.setContentsMargins(10, 6, 8, 6)
        lay.setSpacing(1)
        core = page.core
        self.name = Label(core.legend_label(key), TEXT, 13, True)
        self.rng = Label("", MUTED, 11)
        self.cur = Label("", color, 13, True)
        self.x = QtWidgets.QToolButton()
        self.x.setText("✕")
        self.x.setCursor(Qt.PointingHandCursor)
        self.x.setStyleSheet(f"QToolButton{{background:{CARD2};color:{SUB};border:none;border-radius:4px;padding:1px 5px;}}"
                             f"QToolButton:hover{{color:{TEXT};background:{HOVER};}}")
        self.x.clicked.connect(lambda: core.remove_curve(key))
        for lb in (self.name, self.rng, self.cur):  # le texte long est coupé au lieu d'élargir la légende
            lb.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
            lb.setMinimumWidth(0)
        lay.addWidget(self.name, 0, 0)
        lay.addWidget(self.x, 0, 1)
        lay.addWidget(self.rng, 1, 0, 1, 2)
        lay.addWidget(self.cur, 2, 0, 1, 2)
        self.set_ref(False)

    def set_ref(self, on):
        self.setStyleSheet(
            f"LegendRow{{background:{CARD};border:1px solid {self.color if on else BORDER};border-left:4px solid {self.color};"
            f"border-radius:6px;}}")

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and not self.x.underMouse():
            self.page.core.ref_key = self.key
            self.page.refresh_ref()


class LapStrip(QtWidgets.QWidget):
    """Bandeau juste au-dessus des courbes : un repère « Tour N » à chaque début de tour, placé sur l'axe du temps ;
    le tour en cours est en gras, avec le temps écoulé dans ce tour. Deux lignes en comparaison (A cyan, B orange)."""

    ROW = 24

    def __init__(self, page):
        super().__init__()
        self.page = page
        self._st = None
        self.setFixedHeight(self.ROW)

    def rows(self):
        c = self.page.core
        if c.live or not c.frames:
            return []
        if getattr(c, "compare_name", None):
            return [("A · ", "", CYAN), ("B · ", " [B]", ORANGE)]
        return [("", "", CYAN)]

    def refresh(self):
        n = len(self.rows())
        h = max(1, n) * self.ROW if n else 1
        if self.height() != h:
            self.setFixedHeight(h)
        self.update()

    def paintEvent(self, _e):
        pg_ = self.page
        rows = self.rows()
        if not rows or not pg_.plots:
            return
        c = pg_.core
        p = painter(self)
        vb = pg_.plots[0].vb
        r = vb.sceneBoundingRect()
        off = self.mapFromGlobal(pg_.gl.mapToGlobal(QtCore.QPoint(0, 0))).x()
        x0, x1 = r.left() + off, r.right() + off
        a, b = vb.viewRange()[0]
        if b <= a or x1 <= x0:
            return
        k = (x1 - x0) / (b - a)
        cur = c.cursor_ms()
        for n, (name, suffix, color) in enumerate(rows):
            tab = c.lap_table(suffix)
            if not tab:
                continue
            starts, nums, top = tab
            y = n * self.ROW
            for i, st in enumerate(starts):
                en = starts[i + 1] if i + 1 < len(starts) else c.frames[-1][0]
                ta, tb = st / 1000.0, en / 1000.0
                if tb < a or ta > b:
                    continue
                px0, px1 = x0 + (max(ta, a) - a) * k, x0 + (min(tb, b) - a) * k
                active = st <= cur < en or (i == len(starts) - 1 and cur >= st)
                if ta >= a:  # trait de début de tour
                    p.setPen(QtGui.QPen(qc(color, 200 if nums[i] > 0 else 90), 1.5))
                    p.drawLine(QtCore.QPointF(px0, y + 3), QtCore.QPointF(px0, y + self.ROW - 3))
                if active:
                    p.fillRect(QtCore.QRectF(px0, y + 2, px1 - px0, self.ROW - 4), qc(color, 28))
                if nums[i] <= 0:
                    txt, fnt = "Hors tour", font(11)
                elif active:
                    sec = max(0.0, (cur - st) / 1000.0)
                    txt, fnt = f"{name}Tour {nums[i]}/{top} · {int(sec // 60)}:{sec % 60:04.1f}", font(13, True)
                else:
                    txt, fnt = f"{name}Tour {nums[i]}", font(12, True)
                p.setFont(fnt)
                p.setPen(qc(color if nums[i] > 0 else MUTED, 255 if active else 175))
                if px1 - px0 > 60:
                    p.drawText(QtCore.QRectF(px0 + 6, y, px1 - px0 - 8, self.ROW), Qt.AlignVCenter | Qt.AlignLeft, txt)

    def state(self):
        c = self.page.core
        if not self.rows() or not self.page.plots:
            return (None,)
        vb = self.page.plots[0].vb
        return (tuple(round(v, 3) for v in vb.viewRange()[0]), round(vb.sceneBoundingRect().left()), round(vb.sceneBoundingRect().right()),
                int(c.cursor_ms() // 100), len(self.rows()), id(c.full_t))


class MarkStrip(QtWidgets.QWidget):
    """Marqueurs posés par l'utilisateur : un drapeau jaune sur l'axe du temps, la note à côté ; un clic va à l'instant."""

    ROW = 20

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setFixedHeight(1)
        self.setMouseTracking(True)
        self._hit = []

    def items(self):
        from .analyse_qt import marks_sync

        c = self.page.core
        if c.live or not c.frames:
            return []
        marks_sync(c)
        return getattr(c, "markers", [])

    def refresh(self):
        h = self.ROW if self.items() else 1
        if self.height() != h:
            self.setFixedHeight(h)
        self.update()

    def _map(self):
        pg_ = self.page
        if not pg_.plots:
            return None
        vb = pg_.plots[0].vb
        r = vb.sceneBoundingRect()
        off = self.mapFromGlobal(pg_.gl.mapToGlobal(QtCore.QPoint(0, 0))).x()
        a, b = vb.viewRange()[0]
        x0, x1 = r.left() + off, r.right() + off
        if b <= a or x1 <= x0:
            return None
        return x0, a, (x1 - x0) / (b - a), x1

    def paintEvent(self, _e):
        marks = self.items()
        m = self._map()
        self._hit = []
        if not marks or m is None:
            return
        x0, a, k, x1 = m
        p = painter(self)
        p.setFont(font(11, True))
        for i, mk in enumerate(marks):
            x = x0 + (mk["ms"] / 1000.0 - a) * k
            if x < x0 - 2 or x > x1 + 2:
                continue
            p.setPen(QtGui.QPen(qc(YELLOW), 1.5))
            p.drawLine(QtCore.QPointF(x, 2), QtCore.QPointF(x, self.ROW - 2))
            p.setBrush(qc(YELLOW))
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x, 2), QtCore.QPointF(x + 8, 6), QtCore.QPointF(x, 10)]))
            p.setPen(qc(YELLOW))
            txt = mk["text"]
            p.drawText(QtCore.QRectF(x + 11, 0, 200, self.ROW), Qt.AlignVCenter | Qt.AlignLeft, txt)
            self._hit.append((x - 4, x + 11 + 6 * len(txt), i))

    def mousePressEvent(self, e):
        c = self.page.core
        for x0, x1, i in self._hit:
            if x0 <= e.position().x() <= x1:
                total = c.frames[-1][0] if c.frames else 0
                if total:
                    c.seek(c.markers[i]["ms"] / total)
                return

    def state(self):
        c = self.page.core
        m = self.items()
        if not m or not self.page.plots:
            return (len(m),)
        vb = self.page.plots[0].vb
        return (tuple(round(v, 3) for v in vb.viewRange()[0]), round(vb.sceneBoundingRect().left()), len(m),
                tuple(x["text"] for x in m))


class GraphPage(QtWidgets.QWidget):
    def __init__(self, core):
        super().__init__()
        self.core = core
        self.plots, self.lines, self.curves = [], [], {}
        self._pool_plots, self._pool_lines, self._pool_curves = [], [], {}
        self.follow = True
        self._np = {}
        self._guard = False
        self._sig = None
        self._cur_shown = None
        self._last_legend = 0.0
        self._last_live = 0.0
        self._rows = {}
        self._tmax = 1.0
        self._fit = False
        core.signal_list = None

        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(18, 0, 18, 0)
        # trois volets séparés par des poignées qu'on glisse : (circuit + signaux) | courbes | légende
        self.split = QtWidgets.QSplitter(Qt.Horizontal)
        self.split.setHandleWidth(8)
        self.split.setChildrenCollapsible(False)
        self.split.setStyleSheet(SPLIT_QSS)
        outer.addWidget(self.split)

        # ---- gauche : circuit + liste des signaux (séparés verticalement)
        self.lsplit = QtWidgets.QSplitter(Qt.Vertical)
        self.lsplit.setHandleWidth(8)
        self.lsplit.setChildrenCollapsible(False)
        self.lsplit.setStyleSheet(SPLIT_QSS)
        card = Card()
        cl = QtWidgets.QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        self.map = CircuitMap(core)
        self.cmb_color = QtWidgets.QComboBox()
        for label, _m in CircuitMap.COLOR_MODES:
            self.cmb_color.addItem(label)
        self.cmb_color.setToolTip("Colore le tracé du circuit d'après la vitesse, le freinage ou l'angle")
        self.cmb_color.activated.connect(lambda i: self.map.set_color_mode(CircuitMap.COLOR_MODES[i][1]))
        cl.addWidget(self.cmb_color)
        cl.addWidget(self.map, 1)
        self.lsplit.addWidget(card)
        lbox = QtWidgets.QWidget()
        left = QtWidgets.QVBoxLayout(lbox)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(6)
        head = Label("Signaux · cliquer pour tracer ou retirer", SUB, 12, True)
        left.addWidget(head)
        self.list = GroupedSignalList(core.toggle_curve, core.color_of)
        core.signal_list = self.list
        left.addWidget(self.list, 1)
        lbox.setMinimumHeight(140)
        self.lsplit.addWidget(lbox)
        self.lsplit.setStretchFactor(0, 0)
        self.lsplit.setStretchFactor(1, 1)
        self.lsplit.setSizes([260, 500])
        self.lsplit.setMinimumWidth(190)
        self.split.addWidget(self.lsplit)

        # ---- centre : barre d'outils + courbes
        centre = QtWidgets.QVBoxLayout()
        centre.setSpacing(6)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(Label("Sessions", SUB, 12, True))
        self.b_cmp_end = self._btn("Retirer B", MUTED)
        self.b_cmp_end.clicked.connect(lambda: core.end_compare())
        self.b_mode_t = self._tab("Temps")
        self.b_mode_g = self._tab("Position GPS")
        self.b_mode_t.setToolTip("Les deux sessions sont alignées sur le début du tour 1 : on compare à temps égal")
        self.b_mode_g.setToolTip("Les deux sessions sont recalées sur la position GPS : on compare au même endroit de la piste")
        self.b_mode_t.clicked.connect(lambda: core.set_compare_mode("time"))
        self.b_mode_g.clicked.connect(lambda: core.set_compare_mode("gps"))
        self.l_cmp = Label("Comparaison :", SUB, 12, True)
        top.addSpacing(14)
        top.addWidget(self.l_cmp)
        top.addWidget(self.b_mode_t)
        top.addWidget(self.b_mode_g)
        top.addWidget(self.b_cmp_end)
        top.addStretch(1)
        self.b_mark = self._btn("Marqueur (M)", YELLOW)
        self.b_mark.setToolTip("Pose une note à l'instant du curseur (enregistrée à côté du fichier)")
        self.b_mark.clicked.connect(self.add_mark)
        self.b_math = self._btn("f(x) Voie calculée…", CYAN)
        self.b_math.setToolTip("Crée une voie à partir d'une formule : [GPS Vitesse] / 3.6, deriv(...), smooth(...)")
        self.b_math.clicked.connect(self.open_math)
        top.addWidget(self.b_mark)
        top.addWidget(self.b_math)
        for w_ in (self.l_cmp, self.b_mode_t, self.b_mode_g, self.b_cmp_end):
            w_.setVisible(False)
        centre.addLayout(top)
        bar = QtWidgets.QHBoxLayout()
        self.b_over, self.b_stack = self._tab("Superposées"), self._tab("Empilées")
        self.b_over.clicked.connect(lambda: self.set_stack(False))
        self.b_stack.clicked.connect(lambda: self.set_stack(True))
        bar.addWidget(self.b_over)
        bar.addWidget(self.b_stack)
        hint = Label("Molette : zoom · glisser : déplacer · clic : curseur · double-clic : tout voir", MUTED, 12)
        bar.addSpacing(10)
        bar.addWidget(hint)
        bar.addStretch(1)
        self.b_all = self._btn("Tout voir", CYAN)
        self.b_all.clicked.connect(self.fit_all)
        self.b_follow = self._btn("Suivre", GREEN)
        self.b_follow.clicked.connect(self.set_follow)
        bar.addWidget(self.b_all)
        bar.addWidget(self.b_follow)
        bar.addSpacing(10)
        bar.addWidget(Label("Fenêtre", SUB, 12, True))
        self.win = QtWidgets.QComboBox()
        self.win.setEditable(True)  # la zone de texte affiche la durée réelle de la fenêtre (zoom à la molette compris)
        self.win.lineEdit().setReadOnly(True)
        self.win.setFixedWidth(100)
        self.win.addItems([f"{w} s" for w in WINDOWS])
        self.win.setCurrentText("30 s")
        self.win.activated.connect(self.on_window)
        bar.addWidget(self.win)
        centre.addLayout(bar)
        pg.setConfigOptions(antialias=True, background=BG, foreground=SUB)
        self.gl = pg.GraphicsLayoutWidget()
        self.gl.setBackground(BG)
        self.gl.ci.layout.setSpacing(2)
        self.gl.scene().sigMouseClicked.connect(self.on_click)
        self._row_h = None  # hauteurs choisies à la souris en mode empilé (None = automatique)
        self._row_drag = None
        self.gl.viewport().installEventFilter(self)
        self.gl.viewport().setMouseTracking(True)
        for r in range(POOL):
            self._make_plot(r).setVisible(False)
        self.laps = LapStrip(self)
        centre.addWidget(self.laps)
        self.marks = MarkStrip(self)
        centre.addWidget(self.marks)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setWidget(self.gl)
        centre.addWidget(self.scroll, 1)
        foot = QtWidgets.QHBoxLayout()
        self.l_mode = Label("vue libre", YELLOW, 12, True)
        foot.addStretch(1)
        foot.addWidget(self.l_mode)
        centre.addLayout(foot)
        cw = QtWidgets.QWidget()
        cw.setLayout(centre)
        cw.setMinimumWidth(360)
        self.split.addWidget(cw)

        # ---- droite : légende
        right = QtWidgets.QVBoxLayout()
        right.addWidget(Label("Signal · min … max · actuel", MUTED, 12, True))
        self.legend_host = QtWidgets.QWidget()
        self.legend_lay = QtWidgets.QVBoxLayout(self.legend_host)
        self.legend_lay.setContentsMargins(0, 0, 0, 0)
        self.legend_lay.setSpacing(6)
        self.legend_lay.addStretch(1)
        sc = QtWidgets.QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QtWidgets.QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setWidget(self.legend_host)
        right.addWidget(sc, 1)
        rw = QtWidgets.QWidget()
        rw.setLayout(right)
        rw.setMinimumWidth(170)
        self.split.addWidget(rw)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 0)
        self.split.setSizes([300, 900, 250])
        self._restore_layout()
        self.split.splitterMoved.connect(self._save_layout)
        self.lsplit.splitterMoved.connect(self._save_layout)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    # ------------------------------------------------------------------ petits composants
    def _restore_layout(self):
        try:
            st = QtCore.QSettings("TrackLab", "TrackLabQt")
            for name, sp in (("split", self.split), ("lsplit", self.lsplit)):
                v = st.value("courbes/" + name)
                if v:
                    sp.restoreState(v)
        except Exception:
            pass

    def _save_layout(self, *_a):
        try:
            st = QtCore.QSettings("TrackLab", "TrackLabQt")
            st.setValue("courbes/split", self.split.saveState())
            st.setValue("courbes/lsplit", self.lsplit.saveState())
        except Exception:
            pass

    @staticmethod
    def _tab(text):
        b = QtWidgets.QPushButton(text)
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background:{CARD2};border:none;border-radius:6px;padding:7px 14px;color:{SUB};font-weight:700;}}"
            f"QPushButton:checked{{background:{CYAN};color:{BG};}}")
        return b

    @staticmethod
    def _btn(text, color):
        b = QtWidgets.QPushButton(text)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(f"QPushButton{{background:{CARD2};border:none;border-radius:6px;padding:7px 14px;color:{color};font-weight:700;}}"
                        f"QPushButton:hover{{background:{HOVER};}}")
        return b

    # ------------------------------------------------------------------ données
    def t_off(self):
        """Décalage du temps (s) : en direct, l'axe compte depuis la connexion (les horodatages sont ceux de l'horloge du PC)."""
        c = self.core
        return c.t0 / 1000.0 if c.live else 0.0

    def arrays(self, key):
        """(temps en s, valeurs) d'un signal : tableaux complets du fichier, ou historique récent en direct."""
        c = self.core
        if c.full_t.get(key) and not c.live:  # en direct, l'historique remplace la capture chargée
            ts = c.full_t[key]
            hit = self._np.get(key)
            if hit is None or hit[0] is not ts:
                t = np.asarray(ts, dtype=np.float64) / 1000.0
                v = np.asarray(c.full_v[key], dtype=np.float64)
                n = min(len(t), len(v))
                t, v = t[:n], v[:n]
                # NaN, infinis et valeurs absurdes (décodage expérimental) corrompent le tracé : on les écarte
                ok = np.isfinite(t) & np.isfinite(v) & (np.abs(v) < 1e12)
                if not ok.all():
                    t, v = t[ok], v[ok]
                hit = self._np[key] = (ts, t, v)
            return hit[1], hit[2]
        h = c.hist.get(key)
        if not h:
            return np.empty(0), np.empty(0)
        a = np.asarray(h, dtype=np.float64)
        ok = np.isfinite(a[:, 0]) & np.isfinite(a[:, 1]) & (np.abs(a[:, 1]) < 1e12)
        if not ok.all():
            a = a[ok]
        return a[:, 0] / 1000.0 - self.t_off(), a[:, 1]

    def bounds(self):
        c = self.core
        if c.full_t and c.frames and not c.live:
            return 0.0, c.frames[-1][0] / 1000.0
        return 0.0, max(c.t_now - c.t0, 1000) / 1000.0 if c.live else max(c.t_now, 1000) / 1000.0

    def cursor_s(self):
        return self.core.cursor_ms() / 1000.0 - self.t_off()

    def selected(self):
        c = self.core
        return [k for k in c.curve_keys() if k in c.sel]

    def _pen(self, key):
        """Trait de la courbe : plein, ou pointillé pour la voie de la 2e session comparée."""
        pen = pg.mkPen(self.core.color_of(key), width=PEN_W)
        if key[1].endswith(" [B]"):
            pen.setStyle(Qt.DashLine)
        return pen

    def axis(self, key):
        """(lo, hi, graduations) d'un signal : échelle stable (fichier entier, ou élargie par paliers en direct)."""
        t, v = self.arrays(key)
        mn = float(np.nanmin(v)) if len(v) else 0.0
        mx = float(np.nanmax(v)) if len(v) else 1.0
        return self.core.axis_key(key, mn, mx)

    # ------------------------------------------------------------------ construction du tracé
    def set_stack(self, stacked):
        self.core.stack.set(stacked)
        self.build()

    def _make_plot(self, r):
        """Crée (une seule fois) le tracé n° r : il est ensuite réutilisé, jamais détruit (la destruction répétée de
        PlotItem faisait planter pyqtgraph/PySide)."""
        p = self.gl.addPlot(row=r, col=0, axisItems={"bottom": TimeAxis("bottom"), "left": RefAxis("left")})
        p.showGrid(x=True, y=True, alpha=0.12)
        p.setMenuEnabled(False)
        p.hideButtons()
        p.setMouseEnabled(x=True, y=False)
        p.setClipToView(True)
        p.setDownsampling(auto=True, mode="peak")
        p.vb.setDefaultPadding(0.0)
        p.vb.sigRangeChangedManually.connect(self.on_manual)
        p.getAxis("left").setWidth(66)
        p.getAxis("bottom").setStyle(tickTextOffset=4)
        if self._pool_plots:
            p.setXLink(self._pool_plots[0])
        ln = pg.InfiniteLine(pos=0.0, angle=90, movable=True, pen=pg.mkPen(YELLOW, width=2))
        ln.setZValue(100)
        ln.sigPositionChangeFinished.connect(self.on_line_done)
        ln.sigPositionChanged.connect(self.on_line_move)
        p.addItem(ln)
        self._pool_plots.append(p)
        self._pool_lines.append(ln)
        return p

    @staticmethod
    def _two_points(t, v):
        """Une courbe d'un seul point fait planter le tracé : on la prolonge en un segment plat."""
        if len(t) == 1:
            return np.array([t[0], t[0] + 1e-3]), np.array([v[0], v[0]])
        return t, v

    def _curve_item(self, r, i):
        """Courbe n° i du tracé r : créée une fois, rattachée à ce tracé pour toujours (changer un objet de tracé
        déstabilise pyqtgraph), simplement masquée quand elle ne sert pas."""
        lst = self._pool_curves.setdefault(r, [])
        while len(lst) <= i:
            cv = pg.PlotDataItem(pen=pg.mkPen(CYAN, width=PEN_W), skipFiniteCheck=True)
            self._pool_plots[r].addItem(cv)
            lst.append(cv)
        cv = lst[i]
        cv.setVisible(True)
        return cv

    def build(self):
        c = self.core
        keys = self.selected()
        self.b_over.setChecked(not c.stack.get())
        self.b_stack.setChecked(c.stack.get())
        view = self.view_range() if self.plots else None
        live = bool(c.live)
        if live != getattr(self, "_was_live", False):  # passage fichier <-> direct : la vue repart sur la fenêtre courante
            self._was_live = live
            view = None
        self._building = True
        empty = np.empty(0)
        for lst in self._pool_curves.values():  # toutes les courbes sont masquées et vidées ; celles utilisées réapparaissent
            for cv in lst:
                if cv.isVisible():
                    cv.setVisible(False)
                    cv.setData(empty, empty)
        self.curves = {}
        lo_t, hi_t = self.bounds()
        self._tmax = hi_t
        stacked = bool(c.stack.get())
        n = 1 if (not stacked or not keys) else min(len(keys), POOL)
        if self._row_h is not None and (not stacked or len(self._row_h) != n):
            self._row_h = None  # le nombre de courbes a changé : retour à la hauteur automatique
        self.apply_row_heights(n, stacked)
        for i, pl in enumerate(self._pool_plots):
            pl.setVisible(i < n)
        self.plots = self._pool_plots[:n]
        self.lines = self._pool_lines[:n]
        for r, p in enumerate(self.plots):
            p.vb.setLimits(xMin=-1.0, xMax=max(hi_t, 5.0) * 1.3 + 5, minXRange=0.05)
            p.getAxis("bottom").setStyle(showValues=(r == n - 1))
            ax = p.getAxis("left")
            ax.set_ref(None, None)
            ax.showLabel(False)
        if keys and not stacked:
            p = self.plots[0]
            p.setYRange(-0.04, 1.04, padding=0)
            p.enableAutoRange(axis="y", enable=False)
            for i, k in enumerate(keys):
                lo, hi, _t = self.axis(k)
                t, v = self.arrays(k)
                span = (hi - lo) or 1.0
                cv = self._curve_item(0, i)
                cv.setPen(self._pen(k))
                t2, v2 = self._two_points(t, (v - lo) / span)
                cv.setData(t2, v2)
                self.curves[k] = cv
        elif keys:
            if len(keys) > POOL:
                self.l_mode.setText(f"empilé : {POOL} premières courbes (les autres : mode Superposées)")
            for i, (p, k) in enumerate(zip(self.plots, keys)):
                lo, hi, _t = self.axis(k)
                pad = (hi - lo) * 0.06 or 1.0
                p.setYRange(lo - pad, hi + pad, padding=0)
                p.enableAutoRange(axis="y", enable=False)
                ax = p.getAxis("left")
                ax.setLabel(c.legend_label(k)[:24], color=c.color_of(k))
                ax.showLabel(True)
                ax.set_ref(None, c.color_of(k))
                t, v = self.arrays(k)
                cv = self._curve_item(i, 0)
                cv.setPen(self._pen(k))
                t2, v2 = self._two_points(t, v)
                cv.setData(t2, v2)
                self.curves[k] = cv
        cur = self.cursor_s()
        for ln in self.lines:
            ln.setValue(cur)
        self.build_legend(keys)
        if keys:
            self.refresh_ref()
        self._building = False
        if self._fit and keys:  # l'ajustement attend qu'il y ait de vraies courbes (le chargement relance l'affichage en cours de route)
            self._fit = False
            lo_t, hi_t = self.bounds()
            view = (lo_t - (hi_t - lo_t) * 0.01, hi_t + (hi_t - lo_t) * 0.01)
            self.follow = False
            self.l_mode.setText("vue libre")
        elif view is None:
            view = self.page_range(30.0)
        self.plots[0].setXRange(view[0], view[1], padding=0)
        self.on_cursor(force=True)
        self.relayout()
        QtCore.QTimer.singleShot(0, self.relayout)

    # -- hauteur des courbes empilées réglable à la souris (poignées entre les lignes) --
    GRAB = 5  # tolérance en pixels autour de la limite entre deux courbes

    def apply_row_heights(self, n, stacked):
        lay = self.gl.ci.layout
        big = 16777215.0
        if stacked and self._row_h is not None and len(self._row_h) == n:
            for r in range(POOL):
                if r < n:
                    h = float(self._row_h[r])
                    lay.setRowMinimumHeight(r, h)
                    lay.setRowMaximumHeight(r, h)
                    lay.setRowPreferredHeight(r, h)
                else:
                    lay.setRowMinimumHeight(r, -1.0)
                    lay.setRowMaximumHeight(r, -1.0)
                    lay.setRowPreferredHeight(r, -1.0)
            self._rows_custom = True
            tot = int(sum(self._row_h)) + 4 * n
            self.gl.setMinimumHeight(tot)
            self.gl.setMaximumHeight(tot)
        else:
            if getattr(self, "_rows_custom", False):  # retour aux valeurs par défaut de Qt (-1 = non défini)
                for r in range(POOL):
                    lay.setRowMinimumHeight(r, -1.0)
                    lay.setRowMaximumHeight(r, -1.0)
                    lay.setRowPreferredHeight(r, -1.0)
                self._rows_custom = False
            self.gl.setMaximumHeight(16777215)
            self.gl.setMinimumHeight(max(300, 150 * n) if stacked else 300)

    def _row_edges(self):
        out = []
        for p in self.plots:
            rect = p.sceneBoundingRect()
            out.append((rect.top(), rect.bottom()))
        return out

    def _handle_at(self, pos):
        """Indice r si la souris est sur la limite entre la courbe r et la r+1 (mode empilé), sinon -1."""
        if not self.core.stack.get() or len(self.plots) < 2:
            return -1
        y = self.gl.mapToScene(pos).y()
        edges = self._row_edges()
        for r in range(len(edges) - 1):
            lim = (edges[r][1] + edges[r + 1][0]) / 2.0
            if abs(y - lim) <= self.GRAB:
                return r
        return -1

    def eventFilter(self, obj, ev):
        if obj is not self.gl.viewport():
            return False
        t = ev.type()
        E = QtCore.QEvent
        try:
            if t == E.MouseMove:
                pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
                if self._row_drag is not None:
                    r, y0, h0 = self._row_drag
                    dy = self.gl.mapToScene(pos).y() - y0
                    lo = 50.0
                    a = min(max(h0[r] + dy, lo), h0[r] + h0[r + 1] - lo)
                    hs = list(h0)
                    hs[r], hs[r + 1] = a, h0[r] + h0[r + 1] - a
                    self._row_h = hs
                    self.apply_row_heights(len(hs), True)
                    self.relayout()
                    return True
                self.gl.viewport().setCursor(QtCore.Qt.SizeVerCursor if self._handle_at(pos) >= 0 else QtCore.Qt.ArrowCursor)
            elif t in (E.MouseButtonPress, E.MouseButtonDblClick) and ev.button() == QtCore.Qt.LeftButton:
                pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
                r = self._handle_at(pos)
                if r >= 0:
                    if t == E.MouseButtonDblClick:  # double-clic sur une poignée : hauteurs égales de nouveau
                        self._row_h = None
                        self.apply_row_heights(len(self.plots), True)
                        self.relayout()
                        return True
                    h0 = self._row_h or [max(60.0, p.sceneBoundingRect().height()) for p in self.plots]
                    self._row_drag = (r, self.gl.mapToScene(pos).y(), list(h0))
                    return True
            elif t == E.MouseButtonRelease and self._row_drag is not None:
                self._row_drag = None
                return True
        except Exception:  # une poignée ratée ne doit jamais faire tomber l'appli
            self._row_drag = None
        return False

    def relayout(self):
        """Force le recalcul de la mise en page des tracés (après avoir affiché des tracés jusque-là cachés, la zone
        restait vide jusqu'au prochain redimensionnement)."""
        vp = self.gl.viewport().rect()
        if vp.width() > 20 and vp.height() > 20:
            self.gl.ci.setGeometry(QtCore.QRectF(0, 0, vp.width(), vp.height()))  # la mise en page épouse la zone visible
        lay = self.gl.ci.layout
        lay.invalidate()
        lay.activate()
        self.gl.viewport().update()

    def showEvent(self, e):
        super().showEvent(e)
        QtCore.QTimer.singleShot(0, self.relayout)
        QtCore.QTimer.singleShot(150, self.relayout)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QtCore.QTimer.singleShot(0, self.relayout)

    def build_legend(self, keys):
        for i in reversed(range(self.legend_lay.count() - 1)):
            w = self.legend_lay.itemAt(i).widget()
            if w:
                w.hide()
                w.deleteLater()  # destruction différée : la ligne cliquée peut encore être en train de traiter son événement
        self._rows = {}
        for k in keys:
            row = LegendRow(self, k, self.core.color_of(k))
            self.legend_lay.insertWidget(self.legend_lay.count() - 1, row)
            self._rows[k] = row
        self.update_legend(force=True)

    def refresh_ref(self):
        c = self.core
        keys = self.selected()
        if c.ref_key not in keys:
            c.ref_key = keys[0] if keys else None
        for k, row in self._rows.items():
            row.set_ref(k == c.ref_key)
        if self.plots and not c.stack.get() and isinstance(self.plots[0].getAxis("left"), RefAxis):
            ax = self.plots[0].getAxis("left")
            if c.ref_key is not None:
                ax.set_ref(self.axis(c.ref_key), c.color_of(c.ref_key))
            else:
                ax.set_ref(None, None)

    # ------------------------------------------------------------------ fenêtre de temps
    def view_range(self):
        return tuple(self.plots[0].vb.viewRange()[0]) if self.plots else (0.0, 30.0)

    def span(self):
        a, b = self.view_range()
        return max(0.05, b - a)

    def page_range(self, span):
        cur = max(0.0, self.cursor_s())
        a = math.floor(cur / span) * span
        return a, a + span

    def set_view(self, a, b):
        if self.plots:
            self.plots[0].setXRange(a, b, padding=0)

    def fit_all(self):
        lo, hi = self.bounds()
        self.set_view(lo - (hi - lo) * 0.01, hi + (hi - lo) * 0.01)
        self.set_follow(False)

    def request_fit(self):
        """Le fichier vient d'être chargé : la prochaine construction montre tout, curseur à zéro."""
        self._fit = True
        self._sig = None
        self._np = {}

    def on_window(self, _i=None):
        span = float(self.win.currentText().split()[0])
        self.set_view(*self.page_range(span))
        self.follow = True
        self.l_mode.setText("suit la lecture")

    def set_follow(self, on=True):
        self.follow = bool(on)
        self.l_mode.setText("suit la lecture" if self.follow else "vue libre")
        if self.follow:
            self.set_view(*self.page_range(self.span()))

    def show_span(self):
        """La zone « Fenêtre » indique la durée réellement affichée (zoom à la molette compris)."""
        if not self.plots:
            return
        r = self.view_range()
        if r != getattr(self, "_rng_shown", None):
            self._rng_shown = r
            sp = r[1] - r[0]
            txt = f"{sp:.1f} s" if sp < 100 else f"{sp:.0f} s"
            if self.win.currentText() != txt:
                self.win.setCurrentText(txt)

    def on_manual(self, *_a):
        self.follow = False
        self.l_mode.setText("vue libre")

    # ------------------------------------------------------------------ curseur
    def on_cursor(self, force=False):
        t = self.cursor_s()
        if not force and self._cur_shown is not None and abs(t - self._cur_shown) < 1e-4:
            return
        self._cur_shown = t
        self._guard = True
        for ln in self.lines:
            ln.setValue(t)
        self._guard = False
        if self.plots and (self.core.playing or self.core.live):
            a, b = self.view_range()
            if t > b or t < a:  # le curseur sort de la vue : on tourne la page
                span = b - a
                na = a + math.floor((t - a) / span) * span
                self.set_view(na, na + span)
        self.update_legend()

    def add_mark(self):
        from .analyse_qt import add_marker

        add_marker(self.core, self)
        self.marks.refresh()
        win = self.window()
        if hasattr(win, "analyse"):
            win.analyse.fill_marks()

    def open_math(self):
        from .analyse_qt import MathDialog

        if not self.core.full_t or self.core.live:
            QtWidgets.QMessageBox.information(self, "Voie calculée", "Ouvrez d'abord un fichier.")
            return
        MathDialog(self.core, self).exec()

    def ensure_cursor(self):
        """Après un pas à pas : si le curseur sort de la vue, on la décale pour le garder visible."""
        if not self.plots:
            return
        t = self.cursor_s()
        a, b = self.view_range()
        span = b - a
        if t > b - span * 0.02:
            self.set_view(t - span * 0.5, t + span * 0.5)
        elif t < a + span * 0.02:
            self.set_view(t - span * 0.5, t + span * 0.5)
        self.on_cursor(force=True)

    def on_line_move(self, ln):
        if self._guard:
            return
        self._guard = True
        for other in self.lines:
            if other is not ln:
                other.setValue(ln.value())
        self._guard = False
        self._cur_shown = ln.value()
        self.update_legend(at=ln.value())

    def on_line_done(self):
        if self._guard or not self.lines:
            return
        self.seek_to(self.lines[0].value())

    def seek_to(self, t):
        c = self.core
        if not c.frames or c.live:
            return
        total = c.frames[-1][0]
        t = max(0.0, min(total / 1000.0, t))
        c._cursor_override = t * 1000.0
        self._cur_shown = t
        self._guard = True
        for ln in self.lines:
            ln.setValue(t)
        self._guard = False
        self.update_legend(at=t)

        def do():
            try:
                c.seek(t * 1000.0 / total if total else 0.0)
            finally:
                c._cursor_override = None
            self._cur_shown = None

        QtCore.QTimer.singleShot(0, do)

    def on_click(self, ev):
        if not self.plots or ev.button() != Qt.LeftButton:
            return
        if ev.double():
            self.fit_all()
            ev.accept()
            return
        for p in self.plots:
            if p.vb.sceneBoundingRect().contains(ev.scenePos()):
                self.seek_to(p.vb.mapSceneToView(ev.scenePos()).x())
                ev.accept()
                return

    # ------------------------------------------------------------------ légende : valeurs au curseur
    def value_at(self, key, t):
        ts, vs = self.arrays(key)
        if not len(ts):
            return None
        i = int(np.searchsorted(ts, t, side="right")) - 1
        return float(vs[max(0, i)])

    def update_legend(self, force=False, at=None):
        now = time.monotonic()
        if not force and now - self._last_legend < 0.03:
            return
        self._last_legend = now
        t = self.cursor_s() if at is None else at
        for k, row in self._rows.items():
            v = self.value_at(k, t)
            unit = self.core.unit_of(k)
            row.cur.setText("—" if v is None else f"{fmt_val(v)} {unit}".strip())
            if force:
                ts, vs = self.arrays(k)
                if len(vs):
                    row.rng.setText(f"{fmt_val(float(np.nanmin(vs)))} … {fmt_val(float(np.nanmax(vs)))} {unit}".strip())

    # ------------------------------------------------------------------ boucle d'affichage
    def tick(self):
        c = self.core
        if not self.isVisible():
            return
        sig = (tuple(sorted(c.sel)), c.stack.get(), id(c.full_t), bool(c.live), len(c.dyn), tuple(sorted(c.color_map.items())))
        if sig != self._sig:
            self._sig = sig
            self.list.set_groups(c.signal_groups(), c.sel)
            self.build()
        now = time.monotonic()
        if c.live and now - self._last_live > 0.17:  # en direct : les courbes grandissent
            self._last_live = now
            self.refresh_live()
        self.on_cursor()
        self.show_span()
        self.map.tick()
        self.update_lap()

    def update_lap(self):
        """Bandeau des tours et boutons de comparaison."""
        c = self.core
        cmp_on = bool(getattr(c, "compare_name", None))
        if self.b_cmp_end.isVisible() != cmp_on:
            for w_ in (self.l_cmp, self.b_mode_t, self.b_mode_g, self.b_cmp_end):
                w_.setVisible(cmp_on)
        if cmp_on:
            gps = getattr(c, "compare_mode", "time") == "gps"
            self.b_mode_t.setChecked(not gps)
            self.b_mode_g.setChecked(gps)
        stm = self.marks.state()
        if stm != getattr(self, "_marks_st", None):
            self._marks_st = stm
            self.marks.refresh()
        st = self.laps.state()
        if st != getattr(self, "_lap_st", None):
            self._lap_st = st
            self.laps.refresh()

    def refresh_live(self):
        c = self.core
        lo_t, hi_t = self.bounds()
        for k, curve in self.curves.items():
            t, v = self.arrays(k)
            if c.stack.get():
                curve.setData(t, v)
            else:
                lo, hi, _t = self.axis(k)
                curve.setData(t, (v - lo) / ((hi - lo) or 1.0))
        if self.plots:
            self.plots[0].vb.setLimits(xMax=max(hi_t, 5.0) * 1.3 + 5)
            self.refresh_ref()
