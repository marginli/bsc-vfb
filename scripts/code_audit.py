#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""機械稽核：規範第 10 節的第 7 道——頁面上引用的程式碼，逐行對回原始碼。

  **這一道列在規範裡很久了，但一直沒有程式。** 2026-09-15 掃 PART 9 時
  臨時寫了一次，當場抓到兩塊過期的引用：
    · §3 的終端輸出停在 ③，而程式早就印到 ⑤（一塊是前一天加的、一塊是當天加的）
    · §3② 的程式碼還是舊寫法，`cypher(...)` 早已被抽成 `generic_rows`

  **為什麼人看不出來**：它長得像程式碼、不像數字，所以複查的眼睛會跳過去；
  而 `number_audit` 只查數字對不對得回 `out/`，引用的那幾行裡根本沒有數字。

  **四種 <pre> 要分開**：
    <pre>            引用的程式碼 → 逐行 grep 回原始碼，對不回就是過期
    <pre class="run"> 終端輸出   → 原始碼裡沒有這些字，程式比不了；
                                  它會提醒你「這一塊要自己跑一次比對」
    <pre class="art"> 自己畫的圖 → 樹狀圖之類，本來就不是引用，跳過
    <pre class="ext"> 外面的東西 → 給讀者自己跑的指令、交給 AI 的提示，跳過
                                  （`.prompt` 框裡的自動視為這一種）

  **預設是「要對得回原始碼」**，不是預設跳過——忘了標類別會被叫出來，
  而「漏標一塊引用、於是它悄悄不受檢查」才是這一道最怕的事。

  用法：
      python3 scripts/code_audit.py                  掃所有 *.html
      python3 scripts/code_audit.py part9-read-code.html
"""
import glob
import html
import io
import os
import re
import sys

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_GLOBS = ["recompute/*.py", "scripts/*.py"]

# 刻意的省略，不是引用不實
ELISION = {"...", "…"}


def sources() -> str:
    out = []
    for g in SRC_GLOBS:
        for f in sorted(glob.glob(os.path.join(D, g))):
            out.append(io.open(f, encoding="utf-8").read())
    return re.sub(r"\s+", " ", "\n".join(out))


def main() -> int:
    src = sources()
    files = [os.path.join(D, a) for a in sys.argv[1:]] or sorted(
        glob.glob(os.path.join(D, "*.html")))
    bad = 0
    for f in files:
        s = io.open(f, encoding="utf-8").read()
        # `.prompt` 框裡的是交給 AI 的提示，不是引用
        s = re.sub(r'<div class="prompt".*?</div>', " ", s, flags=re.S)
        blocks = re.findall(r'<pre([^>]*)>(.*?)</pre>', s, flags=re.S)
        if not blocks:
            continue
        print(f"══════ {os.path.basename(f)}　{len(blocks)} 個 <pre>")
        for i, (attr, b) in enumerate(blocks, 1):
            t = html.unescape(re.sub(r"<[^>]+>", "", b))
            lines = [l for l in t.split("\n") if l.strip()]
            if "art" in attr:
                print(f"  {i:>2}. 自己畫的圖（{len(lines)} 行）——不是引用，跳過")
                continue
            if "ext" in attr:
                print(f"  {i:>2}. 外面的東西（{len(lines)} 行）——不是引用，跳過")
                continue
            if "run" in attr:
                print(f"  {i:>2}. 終端輸出（{len(lines)} 行）"
                      f"——程式比不了，改完管線要自己跑一次貼回來")
                continue
            miss = [l.strip() for l in lines
                    if l.strip() not in ELISION
                    and not l.strip().endswith(("...", "…"))
                    and re.sub(r"\s+", " ", l).strip() not in src]
            if miss:
                bad += len(miss)
                print(f"  {i:>2}. ⚠ {len(miss)}/{len(lines)} 行對不回原始碼")
                for l in miss[:8]:
                    print(f"        {l[:96]}")
            else:
                print(f"  {i:>2}. 全部對得回原始碼（{len(lines)} 行）")
    print("\n=== 稽核：引用的程式碼 ===",
          "全部通過" if bad == 0 else f"{bad} 行對不回——那就是過期的引用")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
