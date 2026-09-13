#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quote_audit.py — 把頁面上的英文引文逐條對回 VFB 說明文件的原文。

這是論文型專題那支 quote_audit.py 的工具型版本：論文型對回 `pdftotext` 的全文，
這裡對回說明文件頁面的純文字。**動機是同一個**——摘要工具（包括我自己）
很會把原文改寫成看起來像原文的句子，而改寫過的引文讀起來完全通順。
本專題第一次跑這道稽核就抓到一條：頁面上寫成
「The only way to put a FlyWire neuron…」，原文其實是一個更長的句子的後半，
開頭的大寫 The 是改寫時加上去的。

用法：
    python3 scripts/quote_audit.py                 # 掃所有 *.html
    python3 scripts/quote_audit.py part1-templates.html
    python3 scripts/quote_audit.py --refresh       # 重抓說明文件（預設用快取）

引文怎麼標：頁面上寫成 <p lang="en">…</p>，本程式只認這個標記。
引文中間允許用 … 省略，省略的兩段要**依序**都出現在原文裡。
"""
from __future__ import annotations

import glob
import html
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path("/home/wanjuli/claude_linux/BSC_plan/specific_topics/VFB")
CACHE = ROOT / "out" / "_quotes"
UA = "bsc-vfb-teaching-probe/1.0 (+https://github.com/marginli/bsc-vfb)"

# 本專題引用到的說明文件。新增引文來源時加在這裡。
DOCS = {
    "registration": "https://www.virtualflybrain.org/docs/concepts/registration/",
    "bridging": "https://www.virtualflybrain.org/docs/concepts/bridging/",
    "templates": "https://www.virtualflybrain.org/docs/concepts/templates/",
    "overview": "https://www.virtualflybrain.org/docs/overview/",
}


def fetch(name: str, url: str, refresh: bool) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{name}.html"
    if refresh or not path.exists():
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            path.write_bytes(r.read())
        print(f"  抓了 {url}")
    return path.read_text("utf-8", errors="replace")


def flatten(s: str) -> str:
    """HTML → 一行純文字。

    行內標籤換成**空白**而不是空字串——換成空字串會讓 <b>Overlap</b> is 之類的
    黏成一個字；換行標籤也換成空白，因為原文的句子常被 <p> 切開。
    """
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    return normalise(html.unescape(s))


def normalise(s: str) -> str:
    """統一引號、破折號與空白，讓「同一句話」不會因為排版差異而對不上。"""
    s = unicodedata.normalize("NFKC", s)
    for a, b in [("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
                 ("—", "-"), ("–", "-"), ("−", "-"), (" ", " ")]:
        s = s.replace(a, b)
    s = re.sub(r"\s*-\s*", " - ", s)          # 破折號兩側一律留一個空白
    s = re.sub(r"\s+", " ", s)
    # 說明文件常把句末的句點放在另一個元素裡，剝完標籤會變成「template .」。
    # 不把標點前的空白去掉，每一條引文都會被誤判成對不到——第一版就是這樣，
    # 四條真引文全被標成紅字。
    s = re.sub(r"\s+([.,;:!?%])", r"\1", s)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    return s.strip()


def quotes_in(path: Path) -> list[tuple[int, str]]:
    s = path.read_text("utf-8")
    out = []
    for m in re.finditer(r'<p lang="en">(.*?)</p>', s, flags=re.S):
        line = s[:m.start()].count("\n") + 1
        raw = html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))
        # 先按 … 切段再正規化：NFKC 會把 … 轉成三個句點，切在後面就切不到了
        parts = [normalise(x) for x in raw.split("…") if normalise(x)]
        out.append((line, parts))
    return out


def main() -> int:
    refresh = "--refresh" in sys.argv
    files = [a for a in sys.argv[1:] if a.endswith(".html")]
    paths = [ROOT / f for f in files] if files else sorted(ROOT.glob("*.html"))

    docs = {n: flatten(fetch(n, u, refresh)).lower() for n, u in DOCS.items()}
    bad = 0
    for path in paths:
        qs = quotes_in(path)
        if not qs:
            continue
        print(f"══════ {path.name}　{len(qs)} 條引文 ══════")
        for line, parts in qs:
            q = " … ".join(parts)
            hit = None
            for name, text in docs.items():
                pos, ok = 0, True
                for part in parts:
                    i = text.find(part.lower(), pos)
                    if i < 0:
                        ok = False
                        break
                    pos = i + len(part)
                if ok:
                    hit = name
                    break
            if hit:
                print(f"  [OK  ] 第 {line} 行　← {hit}　{q[:58]}…")
            else:
                bad += 1
                print(f"  [對不到] 第 {line} 行　{q[:88]}")
                # 指出是從哪個字開始對不上，方便修
                for name, text in docs.items():
                    head = parts[0][:40].lower()
                    if head and text.find(head) >= 0:
                        i = text.find(head)
                        print(f"      {name} 裡有開頭，原文是：…{text[i:i + 150]}…")
                        break
    print()
    print("全部對得上。" if not bad else f"有 {bad} 條對不上——逐條回原文改，不要憑印象。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
