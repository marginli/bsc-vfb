#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""機械稽核（第九道）：頁面上那些「資料集／站台／來源」的**值**，是不是逐字。

  **為什麼要有這一道**：2026-09-15 連兩頁抓到同一型的錯——
    PART 5：三個並排的來源名，兩個逐字、一個寫成 `Optic Lobe v1.0.1`
            （探針存的是 `Neuprint web interface - JRC_Optic-Lobe:v1.0.1`）
    PART 4：八個站台名裡有四個寫成 `Neuprint — X`，連破折號都換了
  **前八道一道都抓不到**：`field_audit` 查的是 `<code>` 包起來的**介面名字**，
  這些是表格儲存格裡的**值**；`number_audit` 只管數字。

  **第一版的設計是反的，而破壞測試當場就證明了。**
  那一版從頁面上的錨詞（Neuprint、FlyWire…）出發往外抽片段，結果：
    · `Neuprint — JRC_Optic-Lobe:v1.0.1` 的破折號不在「名字字元」裡，
      片段被切成「Neuprint」，沒有識別記號 → 跳過
    · `Optic Lobe v1.0.1` 一個錯詞都沒有 → 根本沒被抽出來
  **拿修好之前的頁面去跑，五處真錯一個都沒抓到，兩個假警報倒是報了。**

  **現在的判準反過來，從版本號出發**——因為改寫的人幾乎不會動版本號：
    1. 在頁面上找每一個版本 token（`v1.0.1`、`v783`、`:v1.2.1`…）
    2. 找出探針裡含同一個 token 的名字（有幾個都列）
    3. 把 token 前後那一整段「名字」抽出來，**逐字出現在其中一個名字裡就過**
    4. 不逐字 → 並排印出來給人看

  `ACCEPTED` 是頁面自己的簡寫（例如第 4 節那張表的「資料集」欄用
  `BANC v626` 指版本、不是站台名）——**一筆一個理由，而且是最後才查**，
  逐字對得上的絕不會走到這裡（`number_audit` 的 EXEMPT 犯過相反的錯，見第 106 條）。

  用法：
      python3 scripts/value_audit.py                 掃所有 *.html
      python3 scripts/value_audit.py part4-connectomes.html
"""
import glob
import html
import io
import json
import os
import re
import sys

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 只看這些來源的名字（探針裡含這些字的字串值才當參考名）
ANCHORS = ["Neuprint", "neuPrint", "FlyWire", "BANC", "CATMAID", "hemibrain",
           "MANC", "male-cns", "JRC_", "FlyCircuit", "optic_lobe", "optic-lobe",
           "FAFB", "L1 CNS"]

# 版本 token：改寫的人幾乎不會動它，所以拿它當定位點
VER = re.compile(r"(?<![\w.])v\d+(?:\.\d+)*(?![\w.])")

# 名字裡容許的字元。**破折號要收進來**——第一版漏了它，
# 於是「Neuprint — X」被切成兩半，整個錯就看不見了。
NAME_CH = r"[A-Za-z0-9 _:.()\-–—]"

# 頁面自己的簡寫：一筆一個理由。**最後才查。**
ACCEPTED = {
    "BANC v626": "第 4 節那張表的「資料集」欄用的是資料集＋版本，不是站台名；"
                 "同一欄的 male-cns v0.9、hemibrain v1.2.1 是同一種寫法。",
    "BANC v888": "同上。",
    "BANC 連線體　v626": "第 1 節那張表的「是什麼」欄，中文描述＋版本。",
    "BANC 連線體　v888": "同上。",
    "male-cns v0.9": "同 BANC v626：資料集＋版本，不是站台名。",
    "male-cns v1.0": "同上。",
    "hemibrain v1.0.1": "同上。",
    "hemibrain v1.2.1": "同上。",
}


def probe_names() -> set:
    """out/ 裡所有含錨詞的字串**值**。鍵不算——鍵是探針自己取的名字。"""
    out = set()

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and any(a in o for a in ANCHORS):
            out.add(" ".join(o.split()))

    for f in sorted(glob.glob(os.path.join(D, "out", "*.json"))
                    + glob.glob(os.path.join(D, "out", "ui", "*.json"))
                    + glob.glob(os.path.join(D, "out", "recompute", "*.json"))):
        try:
            walk(json.load(io.open(f, encoding="utf-8")))
        except Exception:
            pass
    return out


def page_text(path: str) -> str:
    s = io.open(path, encoding="utf-8").read()
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", s, flags=re.S)
    # 行內標籤拿掉（名字常被 <b> 切開，要接回去）；其餘換成換行，
    # 免得片段跨過 </td> 跟隔壁儲存格黏成一串。
    s = re.sub(r"</?(b|i|em|strong|code|a|span|sup|sub)\b[^>]*>", "", s)
    return html.unescape(re.sub(r"<[^>]+>", "\n", s))


def main() -> int:
    names = probe_names()
    files = [os.path.join(D, a) for a in sys.argv[1:]] or sorted(
        glob.glob(os.path.join(D, "*.html")))
    bad = 0
    for f in files:
        t = page_text(f)
        hits, ok, acc, seen = [], 0, 0, set()
        for m in VER.finditer(t):
            cands = [n for n in names if m.group(0) in n]
            if not cands:
                continue                       # 探針裡沒有這個版本，不是在引名字
            i, j = m.start(), m.end()
            while i > 0 and re.match(NAME_CH, t[i - 1]):
                i -= 1
            while j < len(t) and re.match(NAME_CH, t[j]):
                j += 1
            sp = " ".join(t[i:j].split()).strip(" .,;:()")
            if not sp or sp in seen:
                continue
            seen.add(sp)
            if any(sp in n for n in cands):
                ok += 1
            elif sp in ACCEPTED:
                acc += 1
            else:
                # **候選要挑重疊最多的**，不是最短的——最短的常常只是
                # 某句話裡剛好帶著同一個版本號，印出來會誤導。
                def score(n):
                    w = set(re.findall(r"[A-Za-z0-9]+", n.lower()))
                    return len(w & set(re.findall(r"[A-Za-z0-9]+", sp.lower())))
                hits.append((sp, sorted(cands, key=lambda n: (-score(n), len(n)))[:2]))
        tail = ""
        if acc:
            tail += f"，頁面自己的簡寫 {acc} 段（列在 ACCEPTED）"
        if hits:
            tail += f"，⚠ {len(hits)} 段跟探針不一樣"
        print(f"══════ {os.path.basename(f)}　逐字 {ok} 段{tail}")
        for sp, cs in hits:
            bad += 1
            print(f"  ⚠ 頁面寫　{sp}")
            for c in cs:
                print(f"     探針存　{c}")
    print("\n=== 稽核：引用的值 ===",
          "全部逐字" if bad == 0 else
          f"{bad} 段跟探針存的不一樣——逐字改掉，或列進 ACCEPTED 並寫理由")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
