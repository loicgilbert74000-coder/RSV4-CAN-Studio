"""Connexion en direct : port série USB-CAN ou Wi-Fi vers l'ESP32."""

import socket
import threading
import time
from tkinter import messagebox

try:
    import serial
except ImportError:
    serial = None

from .protocol import WIFI_FRAME_LEN, WIFI_MAGIC, xor_sum
from .theme import GREEN, MUTED


class ConnectionMixin:
    """Connexion en direct : port série USB-CAN ou Wi-Fi vers l'ESP32."""

    def toggle_connect(self):
        self.disconnect() if self.live else self.connect()

    def disconnect(self):
        was_live = self.live
        self.live = False
        self.stop_event.set()
        if was_live:
            self.set_conn_ui(False, "Déconnecté")
            self.set_state("Déconnecté", MUTED)

    def connect(self):
        wifi = self.transport.get().startswith("Wi-Fi")
        if wifi:
            try:
                tcp = int(self.tcp_port.get())
            except ValueError:
                messagebox.showerror("Connexion Wi-Fi", "Port TCP invalide.")
                return
            host = self.host.get().strip()
            target = f"{host}:{tcp}"
            msg = f"Connexion Wi-Fi à l'ESP32 ({target}).\nL'ESP32 doit être en écoute seule (listen-only), comme le mode Silent.\n\n"
        else:
            if serial is None:
                messagebox.showerror("Dépendance", "pyserial manquant")
                return
            br = self.model["bitrate"]
            if br is None:
                msg = "Le débit CAN de cette moto n'est pas défini dans l'application.\nRéglez le débit du véhicule dans USBCAN avant de continuer, puis fermer USBCAN.\n\n"
            else:
                msg = f"Configurer l'adaptateur en mode Silent et CAN {br} avec USBCAN, puis fermer USBCAN.\n\n"
        if not messagebox.askokcancel(
            "Sécurité CAN",
            msg + "Cette application n'envoie aucune commande, et ne peut pas vérifier que le mode Silent reste actif.\n\nContinuer ?",
        ):
            return
        self.disconnect()
        self.stop_event = threading.Event()
        stop = self.stop_event
        self.live = True
        self.clear_data()
        self.t0 = int(time.monotonic() * 1000)
        self.set_conn_ui(True, "Connecté")
        if wifi:
            self.set_state(f"Wi-Fi · ESP32 {target}", GREEN)
            worker = self.make_wifi_worker(host, tcp, stop)
        else:
            self.set_state(f"USB-CAN · écoute sur {self.port.get()}", GREEN)
            worker = self.make_serial_worker(self.port.get(), self.baud.get(), stop)
        threading.Thread(target=worker, daemon=True).start()

    def make_serial_worker(self, port_name, baud, stop):
        q = self.q
        def worker():
            try:
                with serial.Serial(port_name, int(baud), timeout=0.2) as port:
                    buf = bytearray()
                    while not stop.is_set():
                        buf.extend(port.read(512))
                        while len(buf) > 3:
                            ix = buf.find(b"\xaa")
                            if ix < 0:
                                buf.clear()
                                break
                            del buf[:ix]
                            if len(buf) < 3:
                                break
                            typ = buf[1]
                            if typ == 85:
                                if len(buf) < 20:
                                    break
                                p = bytes(buf[:20])
                                del buf[:20]
                                if p[2] == 1 and p[3] in (1, 2) and (p[4] == 1) and (p[9] <= 8) and (
                                    sum(p[2:19]) & 255 == p[19]
                                ):
                                    q.put((int.from_bytes(p[5:9], "little"), p[10:10 + p[9]]))
                                continue
                            if typ & 192 != 192 or typ & 15 > 8:
                                del buf[0]
                                continue
                            idlen = 4 if typ & 32 else 2
                            total = 3 + idlen + (typ & 15)
                            if len(buf) < total:
                                break
                            if buf[total - 1] != 85:
                                del buf[0]
                                continue
                            p = bytes(buf[:total])
                            del buf[:total]
                            if not typ & 16:
                                q.put((int.from_bytes(p[2:2 + idlen], "little"), p[2 + idlen:-1]))
            except Exception as e:
                q.put(("error", str(e)))
        return worker

    def make_wifi_worker(self, host, port, stop):
        q = self.q
        def worker():
            try:
                with socket.create_connection((host, port), timeout=3) as sock:
                    sock.settimeout(0.3)
                    buf = bytearray()
                    while not stop.is_set():
                        try:
                            chunk = sock.recv(4096)
                        except socket.timeout:
                            continue
                        if not chunk:
                            raise ConnectionError("l'ESP32 a fermé la connexion")
                        buf.extend(chunk)
                        while len(buf) >= WIFI_FRAME_LEN:
                            ix = buf.find(WIFI_MAGIC)
                            if ix < 0:
                                del buf[:-1]
                                break
                            if ix > 0:
                                del buf[:ix]
                            if len(buf) < WIFI_FRAME_LEN:
                                break
                            p = bytes(buf[:WIFI_FRAME_LEN])
                            if xor_sum(p[2:19]) != p[19]:
                                del buf[:1]
                                continue
                            del buf[:WIFI_FRAME_LEN]
                            cid = int.from_bytes(p[6:10], "little")
                            dlc = min(p[10], 8)
                            q.put((cid, p[11:11 + dlc]))
            except Exception as e:
                q.put(("error", str(e)))
        return worker
