#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paper_target.py — 把 PART 7–9 要重算的那篇論文的「靶」抓下來，存成 out/nern2025_target.json。

論文：Nern et al., 2025, Nature 641(8065): 1225–1237
      〈Connectome-driven neural inventory of a complete visual system〉
      doi:10.1038/s41586-025-08746-0　PMID 40140576　PMC12119369　FlyBase FBrf0262545
      **CC-BY**（Unpaywall 查過：正式版 hybrid、bioRxiv 預印本 green，兩者都 cc-by）

**為什麼要有這一支。** 這門課的硬條件是「頁面上每個數字都要有一份存下來的輸出可以對回去」。
論文的數字也一樣——732、52,827 這些數字如果只寫在頁面上，就沒有東西可以對回去，
而 PART 8 要拿它們當比對的靶。

靶的來源是補充表 Supplementary Table 1，欄位是
`cell type` / `instance` / `no. of cells` / `main groups` / `bodyId in figures` / `predicted neurotransmitter`。

**下載網址有一個坑**：PMC 那條路（`pmc.ncbi.nlm.nih.gov/articles/instance/…/bin/…`）
回 200 但只有 1.8 KB，是一個空殼。要從出版社的靜態內容站抓，見 SUPP_URL。
"""
from __future__ import annotations

import io
import json
import re
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path("/home/wanjuli/claude_linux/BSC_plan/specific_topics/VFB")
OUT = ROOT / "out"

DOI = "10.1038/s41586-025-08746-0"
SUPP_URL = ("https://static-content.springer.com/esm/"
            "art%3A10.1038%2Fs41586-025-08746-0/MediaObjects/"
            "41586_2025_8746_MOESM4_ESM.zip")
TABLE = "Sup_Table_1_Cell-types_and_counts_final.xlsx"
UA = "bsc-vfb-teaching/1.0 (+https://github.com/marginli/bsc-vfb)"

# 正文裡跟這張表有關的句子，逐字抄下來當對照（PART 7 第 1 節引用的就是第一句）
QUOTES = {
    "n_types": "We classified around 53,000 visual system neurons into 732 cell types",
    "vcn": "We identified 104 VCN types across about 270 cells",
    "concentration": ("The number of neurons that constitute a type varied widely, "
                      "with 60 cell types accounting for >50% of the synaptic connections "
                      "and about 75% of the neurons."),
}


def fetch_table() -> list[tuple]:
    req = urllib.request.Request(SUPP_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        blob = r.read()
    if len(blob) < 100_000:
        raise SystemExit(f"補充表只抓到 {len(blob)} 位元組——八成是抓到空殼了，檢查 SUPP_URL")
    import openpyxl
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        with z.open(TABLE) as f:
            wb = openpyxl.load_workbook(io.BytesIO(f.read()), data_only=True)
    ws = wb[wb.sheetnames[0]]
    return [r for r in ws.iter_rows(min_row=2, values_only=True) if r and r[0]]


def main() -> int:
    rows = fetch_table()

    def n(x):
        try:
            return int(str(x).replace(",", "").strip())
        except Exception:
            return 0

    types = {r[0] for r in rows}
    cells = sum(n(r[2]) for r in rows)
    by_group, cells_by_group, nt = {}, {}, {}
    for r in rows:
        by_group[r[3]] = by_group.get(r[3], 0) + 1
        cells_by_group[r[3]] = cells_by_group.get(r[3], 0) + n(r[2])
        nt[r[5]] = nt.get(r[5], 0) + 1
    multi = sorted(t for t in types if sum(1 for r in rows if r[0] == t) > 1)
    # instance 欄的左右：論文做的是右視葉，所以 _R 應該佔絕大多數
    side = {"_R": 0, "_L": 0, "其他": 0}
    for r in rows:
        i = str(r[1] or "")
        side["_R" if i.endswith("_R") else "_L" if i.endswith("_L") else "其他"] += 1

    payload = {
        "paper": {"doi": DOI, "pmid": "40140576", "pmcid": "PMC12119369",
                  "flybase": "FBrf0262545",
                  "citation": ("Nern et al., 2025, Nature 641(8065): 1225-1237, "
                               "Connectome-driven neural inventory of a complete visual system"),
                  "licence": "CC-BY",
                  "oa_checked_with": "Unpaywall api.unpaywall.org/v2/<doi>"},
        "supplementary_table": {"url": SUPP_URL, "file": TABLE,
                                "columns": ["cell type", "instance", "no. of cells",
                                            "main groups", "bodyId in figures",
                                            "predicted neurotransmitter"]},
        "quotes_from_main_text": QUOTES,
        "target": {
            "rows": len(rows),
            "distinct_cell_types": len(types),
            "total_cells": cells,
            "rows_by_group": by_group,
            "cells_by_group": cells_by_group,
            "rows_by_predicted_neurotransmitter": nt,
            "n_types_with_more_than_one_row": len(multi),
            "instance_side": side,
        },
        "vfb_side": {
            "dataset": "Nern2024",
            "link_relation": "has_reference",
            "linked_to_paper_by": ("知識庫裡 DataSet 的 has_reference 關係指向 "
                                   "FBrf0262545"),
            "site": "neuprint_JRC_OpticLobe_v1_0_1",
        },
        "note": ("正文說 732 cell types、around 53,000 neurons；這張表算出來是 "
                 f"{len(types)} 個型、{cells:,} 顆——兩者對得起來，所以這張表可以當靶。"
                 "PART 8 的比對就是拿 VFB 的資料跟 target 這一段逐列比。"),
    }
    (OUT / "nern2025_target.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    t = payload["target"]
    print(f"  {t['rows']} 列　{t['distinct_cell_types']} 個型　{t['total_cells']:,} 顆")
    print(f"  分組：{t['rows_by_group']}")
    print(f"  instance 左右：{t['instance_side']}")
    print("  → out/nern2025_target.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
