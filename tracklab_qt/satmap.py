"""Fond de carte satellite (tuiles Web Mercator, imagerie Esri World Imagery) avec cache disque.

Le téléchargement est asynchrone (QNetworkAccessManager) : sans réseau ou si un serveur ne répond pas, le circuit reste
simplement tracé sur fond sombre."""

import math
import os

from PySide6 import QtCore, QtGui, QtNetwork

URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
ATTRIBUTION = "Imagerie © Esri, Maxar, Earthstar Geographics"
MAX_Z = 19
MAX_TILES = 40


def world_px(lat, lon, z):
    """Coordonnées (x, y) en pixels dans le monde Web Mercator au niveau de zoom z."""
    n = 256.0 * (2 ** z)
    lat = max(-85.0511, min(85.0511, lat))
    x = (lon + 180.0) / 360.0 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


class TileStore(QtCore.QObject):
    """Mémoire + disque + réseau pour les tuiles ; `changed` est émis quand une tuile arrive."""

    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        base = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.CacheLocation) or os.path.expanduser("~/.tracklab_cache")
        self.dir = os.path.join(base, "tuiles_esri")
        self.mem = {}
        self.pending = set()
        self.failed = {}
        self.net = None
        self.enabled = os.environ.get("TRACKLAB_NO_TILES") != "1"

    def _manager(self):
        if self.net is None:
            self.net = QtNetwork.QNetworkAccessManager(self)
        return self.net

    def get(self, z, x, y):
        key = (z, x, y)
        pm = self.mem.get(key)
        if pm is not None:
            return pm
        path = os.path.join(self.dir, str(z), str(x), f"{y}.jpg")
        if os.path.exists(path):
            pm = QtGui.QPixmap(path)
            if not pm.isNull():
                self.mem[key] = pm
                return pm
        if self.enabled and key not in self.pending and self.failed.get(key, 0) < 2 and len(self.pending) < 64:
            self.pending.add(key)
            req = QtNetwork.QNetworkRequest(QtCore.QUrl(URL.format(z=z, x=x, y=y)))
            req.setHeader(QtNetwork.QNetworkRequest.UserAgentHeader, "TrackLab/0.6")
            req.setTransferTimeout(8000)
            rep = self._manager().get(req)
            rep.finished.connect(lambda r=rep, k=key, p=path: self._done(r, k, p))
        return None

    def _done(self, rep, key, path):
        self.pending.discard(key)
        try:
            if rep.error() == QtNetwork.QNetworkReply.NoError:
                data = bytes(rep.readAll())
                pm = QtGui.QPixmap()
                if pm.loadFromData(data):
                    try:
                        os.makedirs(os.path.dirname(path), exist_ok=True)
                        with open(path, "wb") as f:
                            f.write(data)
                    except OSError:
                        pass
                    self.mem[key] = pm
                    self.changed.emit()
                    return
            self.failed[key] = self.failed.get(key, 0) + 1
        finally:
            rep.deleteLater()


def choose_zoom(lat0, lat1, lon0, lon1, w, h):
    """Plus grand niveau de zoom pour lequel l'emprise tient dans (w, h) sans dépasser MAX_TILES tuiles."""
    for z in range(MAX_Z, 1, -1):
        x0, y1 = world_px(lat0, lon0, z)
        x1, y0 = world_px(lat1, lon1, z)
        bw, bh = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
        if bw <= w * 1.0 and bh <= h * 1.0:
            return z
    return 2
