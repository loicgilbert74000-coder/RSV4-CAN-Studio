"""Fichiers livrés avec l'application (session de démonstration)."""

import os
import sys


def _find(*names):
    bases = []
    if getattr(sys, "_MEIPASS", None):  # exécutable PyInstaller
        bases.append(os.path.join(sys._MEIPASS, "tracklab_qt", "demo"))
    bases.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo"))
    for b in bases:
        for n in names:
            p = os.path.join(b, n)
            if os.path.exists(p):
                return p
    return None


def demo_path():
    """Session de démonstration (Portimão, pilote A : mesures RaceBox + voies moto simulées), ou None si introuvable."""
    return _find("portimao_A.csv", "demo_racebox.csv")


def demo_path_b():
    """Second pilote simulé (Portimão) pour tester la comparaison A / B, ou None."""
    return _find("portimao_B.csv")
