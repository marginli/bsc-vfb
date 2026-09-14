#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_figure.py — 把 recompute.py 的比對結果畫成一張圖。

    python3 recompute.py && python3 make_figure.py

產出：
    out/scatter.png                  兩格：逐型散點、以及 21 個差異的大小
    ../assets/p8-scatter.png         同一張，給教學頁用（VFB/assets 存在時才寫）

**兩格都用對數軸**。理由：每型顆數從 1 跨到 4,000，線性軸會把九成的點
擠在左下角一團，看不出「絕大多數落在對角線上」這件事——而那正是結論。
對數軸畫不了 0，但這裡沒有 0（對得上的型兩邊都至少 1 顆），所以不用特別處理。

圖內不放文字說明，只留座標軸標籤，其餘寫在 HTML 的 figcaption 裡。
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
ASSETS = HERE.parent / "assets"

INK, GREY, HOT = "#1a1a1a", "#9aa0a6", "#c0392b"


def main() -> int:
    target = json.loads((OUT / "target.json").read_text("utf-8"))
    vfb = json.loads((OUT / "vfb.json").read_text("utf-8"))
    cmp_ = json.loads((OUT / "compare.json").read_text("utf-8"))

    paper = {k: v["cells"] for k, v in target["by_instance"].items()}
    got = vfb["keys_instance"]
    both = sorted(set(paper) & set(got))
    same = [(paper[k], got[k]) for k in both if paper[k] == got[k]]
    diff = [(paper[k], got[k]) for k in both if paper[k] != got[k]]

    fig, (ax, bx) = plt.subplots(1, 2, figsize=(10.6, 4.6),
                                 gridspec_kw={"width_ratios": [1.15, 1]})

    # ── 左：逐型散點 ────────────────────────────────────────────────
    lo, hi = 0.7, max(max(paper.values()), max(got.values())) * 1.6
    ax.plot([lo, hi], [lo, hi], "-", color=GREY, lw=1, zorder=1)
    ax.scatter([a for a, _ in same], [b for _, b in same], s=9,
               facecolor="none", edgecolor=INK, lw=0.6, zorder=2)
    ax.scatter([a for a, _ in diff], [b for _, b in diff], s=26,
               color=HOT, zorder=3)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(lo, hi); ax.set_ylim(lo, hi)
    ax.set_aspect("equal")
    ax.set_xlabel("cells per type, paper", fontsize=10)
    ax.set_ylabel("cells per type, recomputed from VFB", fontsize=10)
    ax.tick_params(labelsize=9)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)

    # ── 右：21 個差異，由大到小 ─────────────────────────────────────
    d = sorted((abs(x["delta"]) for x in cmp_["differences"]), reverse=True)
    bx.bar(range(1, len(d) + 1), d, color=HOT, width=0.72)
    bx.set_yscale("log")
    bx.set_xlim(0.3, len(d) + 0.7)
    bx.set_xticks([1, 5, 10, 15, 20])
    bx.set_xlabel("the %d types that disagree, ranked" % len(d), fontsize=10)
    bx.set_ylabel("size of disagreement (cells)", fontsize=10)
    bx.tick_params(labelsize=9)
    for s in ("top", "right"):
        bx.spines[s].set_visible(False)

    fig.tight_layout()
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / "scatter.png", dpi=170, facecolor="white")
    if ASSETS.is_dir():
        fig.savefig(ASSETS / "p8-scatter.png", dpi=170, facecolor="white")
    plt.close(fig)

    stats = {"matched": len(both), "on_diagonal": len(same), "off_diagonal": len(diff),
             "largest": d[0] if d else 0, "smallest": d[-1] if d else 0}
    (OUT / "figure.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
