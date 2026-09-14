#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_part5_figures.py — PART 5 的兩張骨架比對圖，以及圖說裡的每一個數字。

比的是同一顆神經元的兩份骨架：

  A  本機 FlyCircuit 釋出的 SWC
     /mnt/sda1/work1/fly_circuit/FC12_swc/Cha-F-100205_swc.swc
     （TREES toolbox 產生，FlyCircuit 自己的座標框）
  B  VFB 提供下載的 SWC
     https://www.virtualflybrain.org/data/VFB/i/0000/5010/VFB_00101567/volume.swc
     （nat::write.neuron.swc 產生，對位到 JRC2018Unisex）

產出：
  assets/p5-skel-local.png   A
  assets/p5-skel-vfb.png     B
  out/part5_figures.json     圖說與正文裡用到的每一個數字

**這兩張不是解剖方位圖。** 兩份資料在不同的座標框裡（PART 1 第 6 節），
所以本程式**不宣稱任何解剖方位**：它把每一份各自置中、做主成分旋轉、
再除以自己的最大跨距，只比形狀。方位慣例那一套（背側朝上、前側在左）
在這裡不適用，也不應該套用——套了就是宣稱一件沒驗過的事。

主成分的正負號本身是任意的，所以用兩條**確定性**的規則釘住，
否則同一份資料重跑兩次可能左右相反：
  · 讓離原點最遠的那個點落在第一主軸的正向
  · 讓第二主軸上絕對值最大的點落在正向

**圖內一律不放文字**，說明全部寫在 HTML 的 figcaption 裡。
分支點（度數 ≥ 3）畫成實心點，端點畫成空心點——這兩種點的**個數**就是這一節的重點。
"""
from __future__ import annotations

import collections
import json
import math
import urllib.request
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path("/home/wanjuli/claude_linux/BSC_plan/specific_topics/VFB")
ASSETS = ROOT / "assets"
OUT = ROOT / "out"

LOCAL_SWC = Path("/mnt/sda1/work1/fly_circuit/FC12_swc/Cha-F-100205_swc.swc")
VFB_SWC = {
    "JRC2018U": "https://www.virtualflybrain.org/data/VFB/i/0000/5010/VFB_00101567/volume.swc",
    "JFRC2": "https://www.virtualflybrain.org/data/VFB/i/0000/5010/VFB_00017894/volume.swc",
}
NEURON = "Cha-F-100205"
VFB_ID = "VFB_00005010"


# ══════════════════════════════════════════════════════════════════
def parse_swc(text: str) -> list[dict]:
    """讀 SWC。**半徑欄要容忍 `NA`**——VFB 那一份的半徑全部是 NA。"""
    out = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        f = ln.split()
        if len(f) < 7:
            continue

        def num(s):
            return float("nan") if s.upper() == "NA" else float(s)

        out.append({"n": int(f[0]), "label": int(float(f[1])),
                    "xyz": np.array([num(f[2]), num(f[3]), num(f[4])]),
                    "r": num(f[5]), "par": int(f[6])})
    return out


def stats(rows: list[dict]) -> dict:
    """形狀統計。**度數是無向的**——SWC 的 parent 只是書寫順序，不是生物學方向。"""
    deg = collections.Counter()
    for a in rows:
        if a["par"] != -1:
            deg[a["n"]] += 1
            deg[a["par"]] += 1
    xyz = {a["n"]: a["xyz"] for a in rows}
    length = sum(float(np.linalg.norm(xyz[a["n"]] - xyz[a["par"]]))
                 for a in rows if a["par"] != -1)
    span = np.array([a["xyz"] for a in rows]).ptp(axis=0)
    return {"points": len(rows),
            "roots": sum(1 for a in rows if a["par"] == -1),
            "branch_points": sum(1 for v in deg.values() if v >= 3),
            "tips": sum(1 for v in deg.values() if v == 1),
            "total_path_length": round(length, 2),
            "bbox_span": [round(float(v), 2) for v in span],
            "span_ratio": [round(float(v / span.max()), 3) for v in span],
            "degree_sequence": sorted(deg.values()),
            # 半徑欄要講清楚是哪一種「沒有」：VFB 那份寫 NA，本機那份寫 0——
            # 只說「有沒有半徑」會把兩件事混成一件。
            "radius": ("全部是 NA" if not np.isfinite([a["r"] for a in rows]).any()
                       else ("全部是 0" if all(a["r"] == 0 for a in rows)
                             else "有數值"))}


def shape_frame(rows: list[dict]) -> np.ndarray:
    """置中 → 主成分旋轉 → 除以最大跨距。回傳 N×2 的形狀座標。"""
    x = np.array([a["xyz"] for a in rows], dtype=float)
    x = x - x.mean(axis=0)
    _, _, vt = np.linalg.svd(x, full_matrices=False)
    p = x @ vt[:2].T
    # 確定性的正負號：離原點最遠的點落在第一主軸正向
    far = p[np.argmax(np.linalg.norm(p, axis=1))]
    if far[0] < 0:
        p[:, 0] *= -1
    if p[np.argmax(np.abs(p[:, 1])), 1] < 0:
        p[:, 1] *= -1
    return p / np.abs(p[:, 0]).max()


def draw(rows: list[dict], path: Path, colour: str) -> None:
    p = shape_frame(rows)
    idx = {a["n"]: i for i, a in enumerate(rows)}
    deg = collections.Counter()
    for a in rows:
        if a["par"] != -1:
            deg[a["n"]] += 1
            deg[a["par"]] += 1

    fig, ax = plt.subplots(figsize=(4.6, 2.3), dpi=220)
    for a in rows:
        if a["par"] == -1 or a["par"] not in idx:
            continue
        q = p[[idx[a["n"]], idx[a["par"]]]]
        ax.plot(q[:, 0], q[:, 1], "-", color=colour, lw=1.6, solid_capstyle="round")
    br = [idx[k] for k, v in deg.items() if v >= 3 and k in idx]
    tp = [idx[k] for k, v in deg.items() if v == 1 and k in idx]
    ax.plot(p[tp, 0], p[tp, 1], "o", mfc="white", mec=colour, mew=1.4, ms=5.5)
    ax.plot(p[br, 0], p[br, 1], "o", color=colour, ms=6.5)
    # 兩張共用同一個裁切框，否則「看起來一樣大」是畫出來的假象
    ax.set_xlim(-1.15, 1.15)
    ax.set_ylim(-0.45, 0.45)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.tight_layout(pad=0.1)
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def main() -> int:
    ASSETS.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)

    local = parse_swc(LOCAL_SWC.read_text(errors="replace"))
    vfb = {}
    for name, url in VFB_SWC.items():
        with urllib.request.urlopen(url, timeout=60) as r:
            vfb[name] = parse_swc(r.read().decode("utf-8", errors="replace"))

    draw(local, ASSETS / "p5-skel-local.png", "#b45309")
    draw(vfb["JRC2018U"], ASSETS / "p5-skel-vfb.png", "#1d4ed8")

    s_local, s_vfb = stats(local), stats(vfb["JRC2018U"])
    s_jfrc = stats(vfb["JFRC2"])

    # VFB 兩個座標系的版本：形狀統計一不一樣？
    # **不要拿邊集合比**——節點編號不同，邊集合當然不同，那不代表拓樸不同。
    same_degseq = s_vfb["degree_sequence"] == s_jfrc["degree_sequence"]

    payload = {
        "neuron": {"name": NEURON, "vfb_id": VFB_ID},
        "sources": {"local_swc": str(LOCAL_SWC), "vfb_swc": VFB_SWC},
        "local_flycircuit": s_local,
        "vfb_jrc2018u": s_vfb,
        "vfb_jfrc2": s_jfrc,
        "vfb_two_frames_same_degree_sequence": same_degseq,
        "path_length_diff_between_vfb_frames_pct": round(
            abs(s_vfb["total_path_length"] - s_jfrc["total_path_length"])
            / s_jfrc["total_path_length"] * 100, 1),
        "note": (
            "兩份骨架的**點數與分支點數就不一樣**，所以 VFB 那一份不是本機那一份的"
            "座標轉換。本程式不判斷哪一份「對」——它們是兩條不同的處理管線，"
            "而 VFB 也從未宣稱它提供的是 FlyCircuit 釋出的那個 SWC 檔。"
            "路徑長不可直接比（兩份在不同座標框、不同單位尺度）；"
            "可比的是點數、分支點數、端點數與各軸跨距的**比例**。"),
    }
    (OUT / "part5_figures.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"  A 本機 FlyCircuit  {s_local['points']:3d} 點　"
          f"分支 {s_local['branch_points']}　端點 {s_local['tips']}　"
          f"跨距比例 {s_local['span_ratio']}")
    print(f"  B VFB / JRC2018U  {s_vfb['points']:3d} 點　"
          f"分支 {s_vfb['branch_points']}　端點 {s_vfb['tips']}　"
          f"跨距比例 {s_vfb['span_ratio']}")
    print(f"  VFB 兩個座標框的度數序列相同：{same_degseq}")
    print(f"  → assets/p5-skel-local.png、assets/p5-skel-vfb.png、out/part5_figures.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
