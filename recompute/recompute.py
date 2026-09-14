#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recompute.py — 只用 VFB 上的資料，重算 Nern et al. 2025 的細胞型普查，並逐列跟論文比對。

論文：Nern et al., 2025, Nature 641(8065): 1225-1237
      Connectome-driven neural inventory of a complete visual system
      doi:10.1038/s41586-025-08746-0   CC-BY
      正文：We classified around 53,000 visual system neurons into 732 cell types

跑法：
    pip install openpyxl
    python3 recompute.py                # 約 40 秒，產出 out/ 底下四個檔案
    python3 make_figure.py              # 需要 matplotlib，畫逐型的散點圖

產出：
    out/target.json      論文那一側的靶（從補充表算出來）
    out/vfb.json         VFB 那一側（從知識庫取回）
    out/compare.json     逐列比對的結果
    out/fetched_at.txt   抓取時間與每一個關鍵數字

這支程式不需要 API key，也不需要登入。
"""
from __future__ import annotations

import collections
import io
import json
import re
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# ══════════════════════════════════════════════════════════════════
# 自己決定的參數：全部集中在這裡。改動這一段就會改動結論。
# ══════════════════════════════════════════════════════════════════
PARAMS = {
    # 用 VFB 的哪一套資料。換一套，下面每個數字都會變。
    "vfb_dataset": "Nern2024",

    # 拿什麼當比對的鍵。兩個選擇實測命中率差很多：
    #   "instance" → 用神經元自己的標籤，取括號前那一段（例如 Dm20_R）
    #   "class"    → 用它所屬類別的標籤，取最後一個詞（例如 Tm3）
    # 預設用 instance；理由與兩者的命中率見 out/compare.json 的 key_choice。
    "match_key": "instance",

    # 「什麼算一個細胞型」：只算沒有下位類別的類別（末端類別）。
    # 設成 False 會把泛稱（例如「膽鹼性神經元」）也算成一個型，
    # 而那會讓型底下的顆數加總超過神經元總數。
    "leaf_classes_only": True,
}

KB = "https://pdb.virtualflybrain.org/db/neo4j/tx/commit"      # 唯讀，不需認證
SUPP = ("https://static-content.springer.com/esm/"
        "art%3A10.1038%2Fs41586-025-08746-0/MediaObjects/"
        "41586_2025_8746_MOESM4_ESM.zip")
SUPP_TABLE = "Sup_Table_1_Cell-types_and_counts_final.xlsx"
UA = "bsc-vfb-recompute/1.0"
OUT = Path(__file__).resolve().parent / "out"


# ══════════════════════════════════════════════════════════════════
def cypher(statement: str) -> list:
    """對 VFB 的知識庫下一句唯讀查詢。

    為什麼用知識庫而不用 REST：REST 的 run_query 回的是**列數**不是個數
    （同一顆神經元可以有好幾張影像），而且翻頁到某個位移就會停、不報錯。
    實測同一個資料集，REST 報 60,002 列並在 50,000 列截斷，知識庫算出 53,402 顆。
    """
    body = json.dumps({"statements": [{"statement": statement}]}).encode()
    req = urllib.request.Request(KB, data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Accept": "application/json;charset=UTF-8",
                                          "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read().decode("utf-8", errors="replace"))
    if d.get("errors"):
        raise SystemExit(f"知識庫回錯誤：{d['errors']}")
    return [row["row"] for row in d["results"][0]["data"]]


def paper_target() -> dict:
    """論文那一側：下載補充表，算出要比對的靶。

    **下載網址有坑**：PMC 那條路回 200 但只有 1.8 KB，是空殼。
    要從出版社的靜態內容站抓。抓到的東西太小就直接停，不要往下做。
    """
    import openpyxl
    req = urllib.request.Request(SUPP, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        blob = r.read()
    if len(blob) < 100_000:
        raise SystemExit(f"補充表只抓到 {len(blob)} 位元組，八成是空殼")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        wb = openpyxl.load_workbook(io.BytesIO(z.open(SUPP_TABLE).read()), data_only=True)
    ws = wb[wb.sheetnames[0]]

    def n(x):
        try:
            return int(str(x).replace(",", "").strip())
        except Exception:
            return 0

    rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if r and r[0]]
    by_instance = {r[1]: {"cell_type": r[0], "cells": n(r[2]), "group": r[3]} for r in rows}

    # 列數比型數多，因為**一列是一個（型, 側別）實例**，不是一個型。
    # 論文正文報的是型；表列的是列。不分清楚，778 與 732 會看起來像矛盾。
    per_type = collections.defaultdict(list)
    for inst, v in by_instance.items():
        per_type[v["cell_type"]].append(inst)
    def side(x):
        return x[-2:] if x[-2:] in ("_L", "_R") else "其他"
    buckets = collections.Counter()
    groups = collections.defaultdict(collections.Counter)
    for ct, insts in per_type.items():
        s = tuple(sorted({side(i) for i in insts}))
        key = {("_L", "_R"): "both", ("_R",): "right_only", ("_L",): "left_only"}.get(s, str(s))
        buckets[key] += 1
        groups[key][by_instance[insts[0]]["group"]] += 1
    sides = {"rows_per_type": dict(sorted(collections.Counter(
                 len(v) for v in per_type.values()).items())),
             "types_by_side": dict(buckets),
             "groups_by_side": {k: dict(v.most_common()) for k, v in groups.items()},
             "note": "778 列 − 732 型 = 46，剛好就是佔兩列的型數；那 46 個全部是 _L／_R 成對。"}

    # 這個分法有一條獨立的旁證：論文正文自己報過 VCN 的型數與顆數。
    # 「型 104、列 110、顆 270」對上正文的 "104 VCN types across about 270 cells"
    # ——論文報型、表列列，兩個單位在這裡同時出現，剛好把上面那件事釘死。
    vcn = [i for ct, insts in per_type.items() for i in insts
           if by_instance[insts[0]]["group"] == "VCN"]
    sides["vcn_check"] = {
        "types": sum(1 for ct, insts in per_type.items()
                     if by_instance[insts[0]]["group"] == "VCN"),
        "rows": len(vcn),
        "cells": sum(by_instance[i]["cells"] for i in vcn),
        "paper_says": "We identified 104 VCN types across about 270 cells"}

    return {"rows": len(rows),
            "distinct_cell_types": len({r[0] for r in rows}),
            "total_cells": sum(n(r[2]) for r in rows),
            "instance_side": dict(collections.Counter(side(i) for i in by_instance)),
            "sides": sides,
            "by_instance": by_instance}


def vfb_side() -> dict:
    """VFB 那一側：取回資料集底下每一顆神經元，以及類別的上下位關係。"""
    ds = PARAMS["vfb_dataset"]
    neurons = cypher(
        "MATCH (n:Individual)-[:has_source]->(:DataSet {short_form:'%s'}) "
        "RETURN n.short_form, n.label" % ds)

    # 每一顆屬於哪些類別
    pairs = cypher(
        "MATCH (n:Individual)-[:has_source]->(:DataSet {short_form:'%s'}) "
        "MATCH (n)-[:INSTANCEOF]->(c:Class) "
        "RETURN n.short_form, c.short_form, c.label" % ds)
    classes = {c: lab for _, c, lab in pairs}

    # 哪些類別是「泛稱」（底下還有別的類別，而那個別的類別也在這一組裡）
    lit = "[" + ",".join(f"'{c}'" for c in classes) + "]"
    generic = {r[0] for r in cypher(
        "MATCH (a:Class)<-[:SUBCLASSOF*1..8]-(b:Class) "
        "WHERE a.short_form IN %s AND b.short_form IN %s "
        "RETURN DISTINCT a.short_form" % (lit, lit))}
    leaf = {c: lab for c, lab in classes.items() if c not in generic}

    # 比對的鍵
    pre = re.compile(r"^(.*?)\s*\(")
    key_of_instance = collections.Counter()
    for _, lab in neurons:
        m = pre.match(lab or "")
        key_of_instance[m.group(1) if m else (lab or "")] += 1
    by_class = collections.Counter()
    for nid, c, lab in pairs:
        if PARAMS["leaf_classes_only"] and c in generic:
            continue
        by_class[(lab or "").split()[-1] if lab else ""] += 1

    return {"dataset": ds,
            "neurons": len(neurons),
            "classes_all": len(classes),
            "classes_generic": len(generic),
            "classes_leaf": len(leaf),
            "keys_instance": dict(key_of_instance),
            "keys_class": dict(by_class)}


def compare(target: dict, vfb: dict) -> dict:
    """逐列比對。**兩個鍵都算一次**，因為命中率的差距本身是結果的一部分。"""
    paper = target["by_instance"]
    out = {"key_choice": {}}
    for key in ("instance", "class"):
        got = vfb["keys_instance"] if key == "instance" else vfb["keys_class"]
        if key == "instance":
            hit = set(paper) & set(got)
            denom = len(paper)
        else:
            # 類別那一組沒有左右，所以拿論文的 cell type 欄比
            ptypes = {v["cell_type"] for v in paper.values()}
            hit = ptypes & set(got)
            denom = len(ptypes)
        out["key_choice"][key] = {"matched": len(hit), "of": denom,
                                  "rate_pct": round(len(hit) / denom * 100, 1)}

    # 這裡才是 PARAMS["match_key"] 真正生效的地方。
    # 選 class 的時候，論文那一側也要換成 cell type 欄，否則比的是兩種東西。
    if PARAMS["match_key"] == "instance":
        got = vfb["keys_instance"]
    else:
        got = vfb["keys_class"]
        paper = {}
        for v in target["by_instance"].values():
            paper.setdefault(v["cell_type"], {"cells": 0})["cells"] += v["cells"]
    both = sorted(set(paper) & set(got))
    diff = [{"instance": k, "paper": paper[k]["cells"], "vfb": got[k],
             "delta": got[k] - paper[k]["cells"]}
            for k in both if got[k] != paper[k]["cells"]]
    only_paper = sorted(set(paper) - set(got))
    only_vfb = sorted(set(got) - set(paper))

    # 論文把一個型拆成 a/b/c，而 VFB 還是合在一起的 —— 這一類可以自動認出來
    def base(x):
        m = re.match(r"^(.*?)([a-z])(_[LR])$", x)
        return (m.group(1) + m.group(3)) if m else None

    split = collections.defaultdict(list)
    for x in only_paper:
        b = base(x)
        if b and b in only_vfb:
            split[b].append(x)

    # 論文自己點名的那一群：R7／R8 光受器（正文圖說說它們被少算了）
    photo = {k: {"paper": paper[k]["cells"], "vfb": got.get(k)}
             for k in sorted(paper) if k.startswith(("R7", "R8"))}
    photo_delta = sum(v["vfb"] - v["paper"] for v in photo.values() if v["vfb"])

    prefix = collections.Counter()
    for k in only_vfb:
        m = re.match(r"^([A-Za-z]+)", k)
        if m:
            prefix[m.group(1)] += 1

    d = [abs(x["delta"]) for x in diff]
    return {**out,
            "only_in_vfb_cells": sum(got[k] for k in only_vfb),
            "only_in_paper_explained_by_split": sum(len(v) for v in split.values()),
            "only_in_paper_unexplained": len(only_paper) - sum(len(v) for v in split.values()),
            "total_cells_delta": vfb["neurons"] - target["total_cells"],
            "photoreceptor_rows": photo,
            "photoreceptor_delta_total": photo_delta,
            "only_in_vfb_prefix_top": dict(prefix.most_common(8)),
            "matched": len(both),
            "same_count": len(both) - len(diff),
            "different_count": len(diff),
            "differences": sorted(diff, key=lambda x: -abs(x["delta"])),
            "delta_max": max(d) if d else 0,
            "delta_is_one": sum(1 for x in d if x == 1),
            "delta_over_ten": sum(1 for x in d if x > 10),
            "only_in_paper": only_paper,
            "only_in_vfb": only_vfb,
            "paper_split_vfb_did_not": {k: sorted(v) for k, v in split.items()},
            "total_cells_paper": target["total_cells"],
            "total_cells_vfb": vfb["neurons"]}


def main() -> int:
    OUT.mkdir(exist_ok=True)
    print("① 取論文的靶…")
    target = paper_target()
    print(f"   {target['rows']} 列　{target['distinct_cell_types']} 個型　"
          f"{target['total_cells']:,} 顆")

    print("② 取 VFB 那一側…")
    vfb = vfb_side()
    print(f"   {vfb['neurons']:,} 顆　類別 {vfb['classes_all']}"
          f"（泛稱 {vfb['classes_generic']}、末端 {vfb['classes_leaf']}）")

    print("③ 逐列比對…")
    cmp = compare(target, vfb)
    for k, v in cmp["key_choice"].items():
        print(f"   鍵={k:9s} 對得上 {v['matched']}/{v['of']}　{v['rate_pct']}%")
    print(f"   顆數相同 {cmp['same_count']}　不同 {cmp['different_count']}"
          f"（最大差 {cmp['delta_max']}）")
    print(f"   只在論文 {len(cmp['only_in_paper'])}　只在 VFB {len(cmp['only_in_vfb'])}")

    for name, obj in (("target", target), ("vfb", vfb), ("compare", cmp)):
        (OUT / f"{name}.json").write_text(
            json.dumps(obj, ensure_ascii=False, indent=1) + "\n", "utf-8")
    (OUT / "fetched_at.txt").write_text(
        f"抓取時間 {datetime.now(timezone.utc).isoformat(timespec='seconds')}（UTC）\n"
        f"參數 {json.dumps(PARAMS, ensure_ascii=False)}\n"
        f"論文 {target['distinct_cell_types']} 型 / {target['total_cells']} 顆\n"
        f"VFB  {vfb['neurons']} 顆 / 末端類別 {vfb['classes_leaf']}\n"
        f"對得上 {cmp['matched']}　顆數相同 {cmp['same_count']}\n", "utf-8")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
