#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_part1_figures.py — PART 1 的六張真實資料圖。

資料來源（都可公開，見 BSC_plan/D03/D03_資料說明卡.md）：
  FCWB 標準腦模板        Zenodo record 10568（Ostrovsky & Jefferis 2014）  CC0
  FCWBNP 腦區分區標籤    natverse，GPL-3；分區出自 Ito et al. 2014, Neuron 81:755-765
  FC12_warp 座標框的同一份標籤與 515 組質心對應   本專案 D03 自製

產出：
  assets/p1-view-front.png      A 站在前方往後看
  assets/p1-view-side.png       B 站在左側往右看
  assets/p1-view-top.png        C 站在背側往腹側看
  assets/p1-frame-fcwb.png      A 同一份分區，FCWB 座標框
  assets/p1-frame-fc12.png      B 同一份分區，FC12_warp 座標框（同一套繪圖慣例）
  assets/p1-bridge-residual.png 515 組對應的留出殘差分布
  out/part1_figures.json        圖說裡用到的每一個數字

**圖內一律不放文字**，說明全部寫在 HTML 的 figcaption 裡。

本專題的方位慣例（三張視圖共用，面板標題要寫「站在哪裡看」）：
  正視圖  站在前方往後看：背側在上、果蠅的右腦在畫面左側
  側視圖  站在左側往右看：背側在上、前側在畫面左側
  頂視圖  站在背側往腹側看：前側在上、果蠅的右腦在畫面右側

三張都不是「沿某軸投影」講得完的——攝影機站在軸的哪一端決定了哪一面擋住哪一面，
所以每一張都由 camera_at_low 指定從低索引端還是高索引端看進去。
"""
from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

import numpy as np
import nrrd
from PIL import Image

D03 = Path("/home/wanjuli/claude_linux/BSC_plan/D03")
ROOT = Path("/home/wanjuli/claude_linux/BSC_plan/specific_topics/VFB")
ASSETS = ROOT / "assets"
OUT = ROOT / "out"

BG = np.array([255, 255, 255], np.float64)
INK = np.array([27, 39, 51], np.float64)
GREY = np.array([223, 228, 234], np.float64)

# 41 個基本名各給一色（左右同色）。**顏色本身不帶意義**，只是為了讓相鄰的分區分得開——
# 這一頁講的是座標系，不是分區的身分，所以不放圖例，並在圖說裡講明這件事。
PALETTE = ["#2563eb", "#9333ea", "#d97706", "#16a34a", "#dc2626", "#0891b2",
           "#c026d3", "#65a30d", "#ea580c", "#4f46e5", "#0d9488", "#be123c",
           "#7c3aed", "#a16207", "#059669", "#1d4ed8", "#db2777", "#84cc16",
           "#f59e0b", "#06b6d4", "#8b5cf6"]


def hex2rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.float64)


# ══════════════════════════════════════════════════════════════════
# 讀資料與驗座標軸
# ══════════════════════════════════════════════════════════════════
def load_table() -> dict[int, dict]:
    rows = list(csv.DictReader(open(D03 / "D03_region_table.csv", encoding="utf-8")))
    return {int(r["id"]): r for r in rows}


def centroid(labels: np.ndarray, table: dict, name: str) -> np.ndarray:
    rid = next(k for k, v in table.items() if v["name"] == name)
    return np.argwhere(labels == rid).mean(0)


def axis_report(labels: np.ndarray, table: dict, tag: str) -> dict:
    """量出三個軸的方向，不猜。回傳每個軸「低索引端是哪一側」。

    判準用的是方位明確、彼此距離大的腦區：
      左右  ME_R 對 ME_L（兩片視葉，全腦左右距離最大的一對）
      背腹  MB_CA_R 對 GNG（蕈狀體萼在背側、顎神經節在腹側）
      前後  AL_R 對 MB_CA_R（觸角葉在前、萼在後）
    """
    me_r, me_l = centroid(labels, table, "ME_R"), centroid(labels, table, "ME_L")
    ca, gng = centroid(labels, table, "MB_CA_R"), centroid(labels, table, "GNG")
    al = centroid(labels, table, "AL_R")

    lr = int(np.argmax(np.abs(me_l - me_r)))
    rest = [a for a in (0, 1, 2) if a != lr]
    dv = max(rest, key=lambda a: abs(ca[a] - gng[a]))
    ap = [a for a in rest if a != dv][0]

    rep = {
        "tag": tag,
        "axis_leftright": lr,
        "axis_dorsoventral": dv,
        "axis_anteroposterior": ap,
        "low_is_right": bool(me_r[lr] < me_l[lr]),
        "low_is_dorsal": bool(ca[dv] < gng[dv]),
        "low_is_anterior": bool(al[ap] < ca[ap]),
    }
    print(f"  {tag}：左右=axis{lr}（低={'右' if rep['low_is_right'] else '左'}）"
          f"、背腹=axis{dv}（低={'背' if rep['low_is_dorsal'] else '腹'}）"
          f"、前後=axis{ap}（低={'前' if rep['low_is_anterior'] else '後'}）")
    return rep


# ══════════════════════════════════════════════════════════════════
# 投影與上色
# ══════════════════════════════════════════════════════════════════
def project(labels: np.ndarray, axis: int, camera_at_low: bool):
    """攝影機站在 axis 的哪一端往裡看，取每條視線碰到的第一個標籤。

    camera_at_low=True  → 從索引 0 那一端看進去
    camera_at_low=False → 從最大索引那一端看進去（先把該軸反過來）
    回傳 (lab2d, depth2d)，depth 是離攝影機的距離，用來做明暗。
    """
    vol = labels if camera_at_low else np.flip(labels, axis=axis)
    hit = vol > 0
    any_hit = hit.any(axis=axis)
    first = np.argmax(hit, axis=axis)
    idx = list(np.indices(first.shape))
    idx.insert(axis, first)
    lab2d = np.where(any_hit, vol[tuple(idx)], 0)
    depth = np.where(any_hit, first, 0)
    return lab2d, depth


def colourise(lab2d: np.ndarray, depth: np.ndarray, table: dict) -> np.ndarray:
    """(row, col, 3)。同一個基本名左右同色；愈深的愈暗。"""
    bases = sorted({v["base_name"] for v in table.values()})
    colour = {b: hex2rgb(PALETTE[i % len(PALETTE)]) for i, b in enumerate(bases)}

    img = np.repeat(BG[None, None, :], lab2d.shape[0], 0).repeat(lab2d.shape[1], 1)
    mask = lab2d > 0
    if mask.any():
        d = depth[mask].astype(np.float64)
        lo, hi = d.min(), d.max()
        shade = np.ones(depth.shape)
        if hi > lo:
            shade = np.clip(1.05 - 0.38 * (depth - lo) / (hi - lo), 0.70, 1.05)
        for rid, row in table.items():
            m = lab2d == rid
            if not m.any():
                continue
            col = np.clip(colour[row["base_name"]][None, None, :] * shade[..., None], 0, 255)
            img = np.where(m[..., None], col, img)
    return img


def to_image(plane: np.ndarray, rows_axis_flip: bool, cols_axis_flip: bool,
             transpose: bool, scale: int = 2) -> Image.Image:
    """把投影平面擺成成品畫面。

    plane 的兩個軸是原本體積裡「除了投影軸以外」的兩個，順序由小到大。
    transpose  把它們對調，讓第一個軸當畫面的列（由上到下）。
    *_flip     反轉該軸，用來把「低索引在上／在左」改成相反。
    """
    arr = np.transpose(plane, (1, 0, 2)) if transpose else plane
    if rows_axis_flip:
        arr = arr[::-1]
    if cols_axis_flip:
        arr = arr[:, ::-1]
    im = Image.fromarray(arr.astype(np.uint8))
    return im.resize((im.width * scale, im.height * scale), Image.LANCZOS)


def crop_pad(im: Image.Image, margin: int = 20) -> Image.Image:
    a = np.asarray(im).astype(np.int16)
    mask = np.abs(a - BG.astype(np.int16)[None, None, :]).sum(2) > 12
    if not mask.any():
        return im
    r = np.flatnonzero(mask.any(1))
    c = np.flatnonzero(mask.any(0))
    im = im.crop((c[0], r[0], c[-1] + 1, r[-1] + 1))
    out = Image.new("RGB", (im.width + 2 * margin, im.height + 2 * margin),
                    tuple(BG.astype(int)))
    out.paste(im, (margin, margin))
    return out


def verify_on_screen(im: Image.Image, labels, table, rep, view: str,
                     axis, camera_at_low, rows_flip, cols_flip, transpose) -> dict:
    """在**成品畫面**上量幾個方位明確的腦區落在哪一列哪一行，跟解剖常識比對。

    用眼睛看一張果蠅腦投影圖，上下顛倒是看不出來的——所以這一步是算，不是看。
    """
    def screen_pos(name):
        c = centroid(labels, table, name)
        kept = [a for a in (0, 1, 2) if a != axis]
        rc = [c[kept[0]], c[kept[1]]]
        if transpose:
            rc = rc[::-1]
        shape = [labels.shape[kept[0]], labels.shape[kept[1]]]
        if transpose:
            shape = shape[::-1]
        if rows_flip:
            rc[0] = shape[0] - 1 - rc[0]
        if cols_flip:
            rc[1] = shape[1] - 1 - rc[1]
        return rc[0] / shape[0], rc[1] / shape[1]      # 都正規化成 0–1

    names = [n for n in ("ME_R", "ME_L", "MB_CA_R", "GNG", "AL_R")
             if (labels == next(k for k, v in table.items()
                                if v["name"] == n)).any()]
    out = {n: screen_pos(n) for n in names}
    checks = {}
    if view == "front":                       # 背在上、右腦在左
        checks["背側在上"] = out["MB_CA_R"][0] < out["GNG"][0]
        checks["右腦在左"] = out["ME_R"][1] < out["ME_L"][1]
    elif view == "side":                      # 背在上、前在左
        checks["背側在上"] = out["MB_CA_R"][0] < out["GNG"][0]
        checks["前側在左"] = out["AL_R"][1] < out["MB_CA_R"][1]
    elif view == "top":                       # 前在上、右腦在右
        checks["前側在上"] = out["AL_R"][0] < out["MB_CA_R"][0]
        checks["右腦在右"] = out["ME_R"][1] > out["ME_L"][1]
    bad = [k for k, v in checks.items() if not v]
    if bad:
        sys.exit(f"{view} 視圖擺錯了：{'、'.join(bad)} 不成立。")
    print(f"    {view} 畫面驗證通過：{'、'.join(checks)}")
    return {k: bool(v) for k, v in checks.items()}


# ══════════════════════════════════════════════════════════════════
# 三張視圖
# ══════════════════════════════════════════════════════════════════
# view → (投影軸, 攝影機在低索引端, 列反轉, 行反轉, 對調兩軸)
VIEWS = {
    # 站在前方（前=axis2 的低端）往後看。留下 axis0（左右）與 axis1（背腹），
    # 對調成「列=背腹」；背腹低=背 → 不必反轉列；左右低=右 → 右腦落在左行，不必反轉。
    "front": dict(axis=2, camera_at_low=True, rows_flip=False, cols_flip=False,
                  transpose=True),
    # 矢狀視圖：**先把左半腦拿掉**，再站在中線往外（往果蠅的右側）看。
    # 不這樣做的話，最靠近攝影機的視葉會把整顆腦擋光，看不到任何中央腦區。
    # 留下 axis1（背腹）與 axis2（前後），列=背腹（低=背，不反轉），
    # 行=前後（低=前 → 前在左，不反轉）。axis0 低=右，所以右半腦是低索引那一半，
    # 攝影機擺在這一半的高索引端（也就是中線）。
    "side": dict(axis=0, camera_at_low=False, rows_flip=False, cols_flip=False,
                 transpose=False, right_half_only=True),
    # 站在背側（背=axis1 的低端）往腹側看。留下 axis0（左右）與 axis2（前後），
    # 對調成「列=前後」（低=前 → 前在上，不反轉）；行=左右，低=右 → 要反轉才會右腦在右。
    "top": dict(axis=1, camera_at_low=True, rows_flip=False, cols_flip=True,
                transpose=True),
}


def make_views(labels, table, rep) -> dict:
    info = {}
    for view, cfg in VIEWS.items():
        vol = labels
        if cfg.get("right_half_only"):
            # axis0 低=右：取中線以右那一半（中線由 ME_R／ME_L 的中點定）
            mid = int(round((centroid(labels, table, "ME_R")[0]
                             + centroid(labels, table, "ME_L")[0]) / 2))
            vol = labels[:mid + 1]
        lab2d, depth = project(vol, cfg["axis"], cfg["camera_at_low"])
        img = colourise(lab2d, depth, table)
        im = crop_pad(to_image(img, cfg["rows_flip"], cfg["cols_flip"], cfg["transpose"]))
        path = ASSETS / f"p1-view-{view}.png"
        im.save(path)
        checks = verify_on_screen(im, vol, table, rep, view,
                                  cfg["axis"], cfg["camera_at_low"],
                                  cfg["rows_flip"], cfg["cols_flip"], cfg["transpose"])
        info[view] = {"file": path.name, "size": list(im.size),
                      "visible_regions": int(len(np.unique(lab2d)) - 1),
                      "right_half_only": bool(cfg.get("right_half_only")),
                      "checks": checks}
        print(f"  {path.name}  {im.size[0]}×{im.size[1]}　"
              f"看得見 {info[view]['visible_regions']} 個分區")
    return info


# ══════════════════════════════════════════════════════════════════
# 兩個座標框
# ══════════════════════════════════════════════════════════════════
def make_frames(labels_fcwb, labels_fc12, table) -> dict:
    """同一份分區、兩個座標框，用**同一套**繪圖慣例畫——差別就自己現形。"""
    out = {}
    for tag, vol in (("fcwb", labels_fcwb), ("fc12", labels_fc12)):
        cfg = VIEWS["front"]
        lab2d, depth = project(vol, cfg["axis"], cfg["camera_at_low"])
        img = colourise(lab2d, depth, table)
        im = crop_pad(to_image(img, cfg["rows_flip"], cfg["cols_flip"], cfg["transpose"]))
        path = ASSETS / f"p1-frame-{tag}.png"
        im.save(path)
        # 兩個座標系的體素邊長都是 1 µm，但腦在裡面佔的範圍不同——
        # 圖在網頁上被縮到同寬，所以這件事看不出來，得寫在圖說裡。
        occ = np.argwhere(vol > 0)
        extent = [int(occ[:, a].ptp()) + 1 for a in (0, 1, 2)]
        out[tag] = {"file": path.name, "size": list(im.size), "shape": list(vol.shape),
                    "labelled_extent_um": extent}
        print(f"  {path.name}  {im.size[0]}×{im.size[1]}　體積 {vol.shape}"
              f"　標到的範圍 {extent[0]}×{extent[1]}×{extent[2]} µm")
    return out


# ══════════════════════════════════════════════════════════════════
# bridging 殘差
# ══════════════════════════════════════════════════════════════════
def make_residual(aff: dict) -> dict:
    """515 組質心對應，套上解出來的 affine，量每一組差多少。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cen_fc = np.load(D03 / "work" / "fig_cenFC.npy")
    cen_fw = np.load(D03 / "work" / "fig_cenFW.npy")
    M = np.array(aff["M"], float)
    t = np.array(aff["t"], float)
    pred = cen_fc @ M.T + t
    res = np.linalg.norm(pred - cen_fw, axis=1)

    # 這 515 組裡有 80% 被拿去解那 12 個參數、20% 留著不用。
    # 兩組要分開報：整體的中位數含被擬合過的點，留出那組才是「對沒見過的神經元有多準」。
    # 切法與亂數種子跟 D03/scripts/fit_transform.py 一致，所以留出的數字對得回那支程式。
    idx = list(range(len(res)))
    random.Random(5).shuffle(idx)
    cut = int(len(idx) * 0.8)
    tr = np.array(idx[:cut])
    te = np.array(idx[cut:])

    XMAX = 40.0                      # 主體畫到 40 µm；再往外只有零星幾顆，會把柱子壓扁
    over = int((res > XMAX).sum())
    fig, ax = plt.subplots(figsize=(6.4, 3.5), dpi=170)
    ax.hist(np.clip(res, 0, XMAX), bins=40, range=(0, XMAX),
            color="#2563eb", alpha=.85, edgecolor="white", linewidth=.5)
    ax.set_xlim(0, XMAX)
    for v, c, ls in ((np.median(res), "#dc2626", "-"),
                     (np.percentile(res, 90), "#d97706", "--")):
        ax.axvline(v, color=c, linestyle=ls, linewidth=1.6)
    ax.set_xlabel("residual after bridging  (micrometre)", fontsize=10)
    ax.set_ylabel("neurons", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=9)
    fig.tight_layout()
    path = ASSETS / "p1-bridge-residual.png"
    fig.savefig(path, facecolor="white")
    plt.close(fig)

    stats = {
        "file": path.name,
        "n_pairs": int(len(res)),
        "median_um": round(float(np.median(res)), 2),
        "p90_um": round(float(np.percentile(res, 90)), 2),
        "max_um": round(float(res.max()), 2),
        "frac_under_10um": round(float((res < 10).mean()), 3),
        "xmax_um": XMAX,
        "n_over_xmax": over,
        "n_heldout": int(len(te)),
        "heldout_median_um": round(float(np.median(res[te])), 2),
        "heldout_p90_um": round(float(np.percentile(res[te], 90)), 2),
        "fitted_median_um": round(float(np.median(res[tr])), 2),
    }
    print(f"  {path.name}　n={stats['n_pairs']}　全體中位數 {stats['median_um']} µm、"
          f"p90 {stats['p90_um']} µm、10 µm 以內佔 {stats['frac_under_10um']:.1%}")
    print(f"    其中解參數用的 {len(tr)} 顆中位數 {stats['fitted_median_um']} µm、"
          f"留出的 {stats['n_heldout']} 顆 {stats['heldout_median_um']} µm"
          f"（D03 記錄的是後者）")
    return stats


# ══════════════════════════════════════════════════════════════════
def main() -> int:
    ASSETS.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    table = load_table()

    print("讀 FCWB 座標框的分區標籤：")
    lab_fcwb, _ = nrrd.read(str(D03 / "D03_FCWBNP_labels_1um.nrrd"))
    rep_fcwb = axis_report(lab_fcwb, table, "FCWB")
    if not (rep_fcwb["low_is_right"] and rep_fcwb["low_is_dorsal"]
            and rep_fcwb["low_is_anterior"]
            and (rep_fcwb["axis_leftright"], rep_fcwb["axis_dorsoventral"],
                 rep_fcwb["axis_anteroposterior"]) == (0, 1, 2)):
        sys.exit("FCWB 的軸序或方向跟本腳本的假設不符，先確認再產圖。")

    print("讀 FC12_warp 座標框的同一份分區：")
    lab_fc12, _ = nrrd.read(str(D03 / "D03_FCWBNP_labels_in_FC12warp_1um.nrrd"))
    rep_fc12 = axis_report(lab_fc12, table, "FC12_warp")

    print("三張視圖：")
    views = make_views(lab_fcwb, table, rep_fcwb)
    print("兩個座標框：")
    frames = make_frames(lab_fcwb, lab_fc12, table)
    print("bridging 殘差：")
    aff = json.loads((D03 / "D03_fc_to_fcwb_affine.json").read_text("utf-8"))
    resid = make_residual(aff)

    n_regions = len(table)
    bases = {v["base_name"] for v in table.values()}
    payload = {
        "source": "本機 D03（FCWB CC0；FCWBNP natverse GPL-3／Ito et al. 2014）",
        "script": "scripts/make_part1_figures.py",
        "regions": {"labels": n_regions, "base_names": len(bases),
                    "paired": len([v for v in table.values() if v["side"] in ("L", "R")]) // 2,
                    "midline_only": len([v for v in table.values()
                                         if v["side"] == "M"])},
        "axes": {"FCWB": rep_fcwb, "FC12_warp": rep_fc12},
        "views": views,
        "frames": frames,
        "bridge": {**resid,
                   "singular_values": [round(v, 3) for v in aff["singular_values"]],
                   "det": round(aff["det"], 4),
                   "midline_from_fit_um": round(aff["t"][0], 1),
                   "midline_measured_um": aff["midline_fcwb_um"],
                   "pointcloud_holdout_median_um": round(
                       aff["pointcloud_holdout_median_um"], 2)},
    }
    (OUT / "part1_figures.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n寫好 out/part1_figures.json（圖說要用的數字都在裡面）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
