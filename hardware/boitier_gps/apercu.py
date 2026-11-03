#!/usr/bin/env python3
"""Images d'aperçu du boîtier GPS (utilise les maillages écrits par generer_boitier.py)."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generer_boitier as g  # noqa: E402


def box(x0, x1, y0, y1, z0, z1):
    v = np.array([[x, y, z] for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)], float)
    f = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    t = []
    for a, b, c, d in f:
        t += [[v[a], v[b], v[c]], [v[a], v[c], v[d]]]
    return np.array(t)


def main(d):
    shell = np.load(os.path.join(d, "_shell.npy")).astype(float)
    plate = np.load(os.path.join(d, "_plate.npy")).astype(float)
    pcb = box(g.PCB_CX - g.PCB_L / 2, g.PCB_CX + g.PCB_L / 2, -g.PCB_W / 2, g.PCB_W / 2, g.POST_H, g.POST_H + g.PCB_T)
    ant_z0 = g.H_IN - g.GAP_ANT - g.ANT_H
    ant = box(g.PCB_CX - g.ANT / 2, g.PCB_CX + g.ANT / 2, -g.ANT / 2, g.ANT / 2, ant_z0, ant_z0 + g.ANT_H)
    col_s, col_p = (214, 218, 224), (150, 160, 172)
    col_pcb, col_ant = (40, 140, 90), (205, 160, 70)
    # éclaté, vue 3/4
    sh = shell.copy(); sh[:, :, 2] += 16
    ant2 = ant.copy(); ant2[:, :, 2] += 16 * 0
    g.render([(plate, col_p), (pcb, col_pcb), (ant + [0, 0, 8], col_ant), (sh, col_s)], os.path.join(d, "apercu_eclate.png"), view=(55, -35))
    # coupe y >= 0 : maillages recalculés avec un plan de coupe (faces fermées)
    txt = g.text_mask()
    cut = lambda f: (lambda x, y, z: np.maximum(f(x, y, z), -y))
    cs = g.mesh(cut(g.shell_sdf(txt)), (-g.OX - 3, -0.4, -0.6), (g.OX + g.NOZ_LEN + 1, g.OY + 3, g.H + 0.6), 0.4).astype(float)
    cp = g.mesh(cut(g.plate_sdf()), (-g.OX - 3, -0.4, -g.FOND_T - 0.6), (g.OX + 3, g.OY + 3, g.POST_H + g.PCB_T + 1.8), 0.4).astype(float)
    pcb_c = box(g.PCB_CX - g.PCB_L / 2, g.PCB_CX + g.PCB_L / 2, 0, g.PCB_W / 2, g.POST_H, g.POST_H + g.PCB_T)
    ant_c = box(g.PCB_CX - g.ANT / 2, g.PCB_CX + g.ANT / 2, 0, g.ANT / 2, ant_z0, ant_z0 + g.ANT_H)
    g.render([(cp, col_p), (pcb_c, col_pcb), (ant_c, col_ant), (cs, col_s)], os.path.join(d, "apercu_coupe.png"), view=(-78, 0), size=(1400, 700))
    # dessus (gravure) et dessous
    g.render([(plate, col_p), (shell, col_s)], os.path.join(d, "apercu_dessus.png"), view=(8, -18), size=(1400, 800))
    g.render([(shell, col_s), (plate, col_p)], os.path.join(d, "apercu_assemble.png"), view=(48, -30), size=(1400, 900))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
