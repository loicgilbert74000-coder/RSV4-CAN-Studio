"""Fichiers livrés avec l'application (session de démonstration)."""

import os
import sys


def demo_path():
    """Chemin de la session RaceBox de démonstration, ou None si elle est introuvable."""
    bases = []
    if getattr(sys, "_MEIPASS", None):  # exécutable PyInstaller
        bases.append(os.path.join(sys._MEIPASS, "tracklab_qt", "demo"))
    bases.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo"))
    for b in bases:
        p = os.path.join(b, "demo_racebox.csv")
        if os.path.exists(p):
            return p
    return None
