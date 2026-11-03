"""Cœur de l'application Qt : toute la logique de TrackLab (décodage, lecture, connexion, enregistrements)
réutilisée telle quelle depuis le paquet `tracklab`, sans aucune fenêtre tkinter.

L'interface Qt est branchée par l'objet `ui` : il reçoit les évènements (état, progression, page…) et fournit
des contrôles de même API que les anciens widgets (jauges, tuiles, afficheur…) que l'on affecte à `core.<nom>`."""

import time

from tracklab.app import App
from tracklab.config import MODELS
from tracklab.recording import fmt_size
from tracklab.theme import CARD, GREEN, MUTED, RED, YELLOW


class Null:
    """Contrôle muet : accepte n'importe quel appel (tant que l'interface n'a pas fourni le vrai contrôle)."""

    items = {}

    def __getattr__(self, name):
        return Null()

    def __call__(self, *a, **k):
        return Null()

    def __contains__(self, _x):
        return False

    def __iter__(self):
        return iter(())

    def __eq__(self, other):
        return False

    def __ne__(self, other):
        return True

    def __hash__(self):
        return 0

    def __bool__(self):
        return False


class Var:
    """Variable observable : même API que tkinter.StringVar / DoubleVar / BooleanVar."""

    def __init__(self, value=None):
        self._v = value
        self._cb = []

    def get(self):
        return self._v

    def set(self, value):
        self._v = value
        for cb in list(self._cb):
            cb()

    def trace_add(self, _mode, cb):
        self._cb.append(lambda: cb())


class Root:
    """Équivalent minimal de la fenêtre tkinter : `after`, `update`… branchés sur la boucle Qt."""

    def __init__(self, ui):
        self.ui = ui
        self._n = 0
        self._live = {}

    def after(self, ms, fn=None, *args):
        self._n += 1
        ident = str(self._n)
        self._live[ident] = True

        def run():
            if self._live.pop(ident, False):
                fn(*args)

        self.ui.single_shot(int(ms), run)
        return ident

    def after_cancel(self, ident):
        self._live.pop(ident, None)

    def update(self):
        self.ui.process_events()

    def update_idletasks(self):
        self.ui.process_events()

    def winfo_exists(self):
        return True


class Core(App):
    """L'application sans fenêtre : état, décodage, lecture, connexion Wi-Fi / série, enregistrements."""

    def __init__(self, ui, dialogs):
        self.ui = ui
        self.dlg = dialogs
        self.root = Root(ui)
        self.init_state()
        self.build_esp_vars()
        # contrôles muets en attendant ceux de l'interface
        for name in ("rpm", "speedg", "gear", "gear_val", "tps_lbl", "board", "lcd", "key_open", "key_start", "key_play",
                     "key_pause", "key_speed", "rec_btn", "conn_btn", "signal_list", "chart", "taxis", "footnote",
                     "bus_note", "model_cb", "rec_info", "rec_dot", "rec_state", "rec_btn2", "conn_lbl", "conn_dot",
                     "throttle_val", "gaz_bar"):
            setattr(self, name, Null())
        self.cards = {k: (Null(), Null()) for k in ("throttle", "temp", "oil", "battery", "front", "rear")}
        self.tile_unit = {}
        self.assign_defaults()
        self.decoder = MODELS[self.model_key]["decoder"]

    def mkvar(self, value):
        return Var(value)

    def update_esp_live(self, now, rate):
        self.ui.update_esp_live(now, rate)

    def assign_defaults(self):
        from tracklab.config import GROUP_OF, TILE_DEFS  # noqa: F401  (unités des tuiles)
        from tracklab.util import disp_unit

        self.tile_unit = {(cid, name): disp_unit(unit) for cid, name, *_, unit in TILE_DEFS}
        self.status_color = MUTED
        self.set_conn_state = (False, "Déconnecté")

    # ---------- évènements vers l'interface ----------
    def set_state(self, text, color):
        self.status.set(text)
        self.status_color = color
        self.ui.on_state(text, color)

    def progress_show(self, text, pct):
        self.ui.progress_show(text, pct)

    def progress_hide(self):
        self.ui.progress_hide()

    def show_page(self, key):
        self.current_page = key
        if key == "frames" and self._table_stale:
            self.rebuild_table()
        self._map_state = None
        self.ui.show_page(key)

    def set_conn_ui(self, live, text):
        self._conn_shown = None
        if live:
            self.view_end = None  # en direct, la vue suit les courbes
        self.set_conn_state = (live, text)
        self.ui.set_conn_ui(live, text)

    def open_connection_dialog(self):
        self.ui.open_connection_dialog()

    def open_choice(self):
        self.ui.open_choice()

    def settings(self):
        self.ui.open_settings()

    # ---------- modèle de moto ----------
    def apply_model(self, key):
        self.model_key = key
        m = MODELS[key]
        self.decoder = m["decoder"]
        self.clear_data()
        self.ui.apply_model_ui(key)

    def on_model(self, key):
        if self.live:
            self.disconnect()
        self.pause()
        self.apply_model(key)
        if self.frames:
            self.set_state(f"Modèle : {self.model['label']}", "#9fb0c8")
            self.prebuild()

    # ---------- pied de page, liaison, voyants ----------
    def show_footer(self, key, text):
        if self._footer_shown.get(key) != text:
            self._footer_shown[key] = text
            self.ui.show_footer(key, text)

    def update_conn_label(self, now):
        link = self.link_state(now)
        shown = {None: ("Déconnecté", MUTED, "#9fb0c8"), "attente": ("Connexion…", YELLOW, YELLOW),
                 "ok": ("Connecté", GREEN, GREEN), "muet": ("Aucune donnée", RED, RED)}[link]
        if shown != self._conn_shown:
            self._conn_shown = shown
            self.ui.set_link_label(*shown)

    def set_srow(self, key, text, color):
        if self._srow_shown.get(key) == (text, color):
            return
        self._srow_shown[key] = (text, color)
        self.ui.set_status_row(key, text, color)

    # ---------- tableau des trames (le tableau Qt lit `self.rows`) ----------
    def on_row(self, row):
        if not self.bulk and not self.table_paused and self.row_match(row):
            self.matched += 1
            self.ui.table_new_row(row)

    def clear_table(self):
        self.rows.clear()
        self.matched = 0
        self.ui.table_clear()

    def rebuild_table(self):
        self._table_stale = False
        self.matched = sum(1 for r in self.rows if self.row_match(r))
        self.ui.table_rebuild()

    def refresh_count(self):
        self.ui.table_count()

    def toggle_table_pause(self):
        self.table_paused = not self.table_paused
        self.ui.table_pause_changed(self.table_paused)

    def schedule_filter(self):
        self.ui.table_filter_changed()

    # ---------- enregistrements ----------
    def rec_set_info(self, text):
        self.ui.rec_info(text)

    def refresh_rec_trees(self):
        self.ui.rec_refresh()

    def update_rec_live(self, esp, link_ok):
        on = bool(esp and esp.get("rec"))
        if esp and link_ok:
            if not esp.get("store"):
                shown = ("Aucun stockage (carte SD absente ?)", YELLOW, "Démarrer", False, False)
            elif on:
                shown = (f"EN COURS · fichier {esp['rec_no']:04d} · {fmt_size(esp['rec_bytes'])}", RED, "Arrêter", True, True)
            else:
                free = esp.get("free_mb", 0)
                kind = "carte SD" if esp.get("sd") else "mémoire interne"
                shown = (f"Arrêté · {kind} · {free} Mo libres", GREEN, "Démarrer", True, False)
        else:
            shown = ("—", MUTED, "Démarrer", False, False)
        if shown != self._rec_shown:
            self._rec_shown = shown
            self.ui.set_rec_state(*shown)
        if on and not self._rec_was_on and self.table_paused:
            self.toggle_table_pause()
        if link_ok and esp:
            if not self._rec_listed or (self._rec_was_on and not on):
                self._rec_listed = True
                self.send_quiet("LIST")
        if self.rec_req and time.monotonic() - self.rec_req[2] > 20:
            self.rec_fail(self.rec_req[0], "Pas de réponse de Tracklab pour ce fichier.")
        self._rec_was_on = on

    def open_recording(self, path):
        self.rec_open_after = None
        if self.live:
            self.disconnect()
        self.load(path)
        self.ui.close_dialogs()

    # ---------- courbes : l'interface trace, le cœur garde l'état ----------
    def fit_all(self):
        self.ui.graph_fit_all()

    def draw_chart(self):
        self.ui.graph_changed()

    def follow(self):
        self.view_end = None
        self.ui.graph_changed()

    def toggle_curve(self, key):
        if key in self.sel:
            self.remove_curve(key)
            return
        self.assign_color(key)
        self.sel.add(key)
        self.ui.graph_selection_changed()

    def remove_curve(self, key):
        self.sel.discard(key)
        self.color_map.pop(key, None)
        self.band_h.pop(key, None)
        if self.ref_key == key:
            self.ref_key = None
        self.ui.graph_selection_changed()
