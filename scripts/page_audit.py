#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""機械稽核：規範第 10 節的第 1、2、3、6 道。

     1. 標籤平衡（p/div/table/tr/td/th/figure/figcaption/ul/li/a/pre/code）
     2. 連結與錨點（href 的檔案存在、#frag 對得到 id）、圖檔路徑存在
     3. 中文句子裡夾雜英文單字
     6. SVG 內不得出現 <b>

   另外一道（不在規範的編號裡）：**佔位字樣**。
   寫「（尚未發布）」的那一頁，後來發布了卻沒有人回頭改——
   因為佔位是 <span> 不是 <a>，第 2 道連結稽核**看不到它**。
   PART 7 的上下兩個 pager 就這樣掛了一天。

   用法：python3 scripts/page_audit.py            （掃專題根目錄所有 *.html）
   換一個專題時只要改 D 這一行。
"""
import io, re, os, sys, glob
D = "/home/wanjuli/claude_linux/BSC_plan/specific_topics/VFB"
files = sorted(glob.glob(D + "/*.html"))
ids = {}
for f in files:
    s = io.open(f, encoding="utf-8").read()
    ids[os.path.basename(f)] = set(re.findall(r'\bid="([^"]+)"', s))
# PART 編號 → 檔名，給「佔位字樣」那一道用
parts = {m.group(1): os.path.basename(f) for f in files
         if (m := re.match(r"part(\d+)-", os.path.basename(f)))}
bad = 0
for f in files:
    b = os.path.basename(f)
    s = io.open(f, encoding="utf-8").read()
    # 1 標籤平衡
    for t in ["p","div","table","tr","td","th","figure","figcaption","ul","li","a","pre","code"]:
        o = len(re.findall(r'<%s\b' % t, s)); c = len(re.findall(r'</%s>' % t, s))
        if o != c:
            print(f"[標籤] {b} {t}: 開 {o} 關 {c}"); bad += 1
    # 2 連結與錨點、圖檔
    for href in re.findall(r'href="([^"]+)"', s):
        if href.startswith(("http://", "https://", "mailto:")): continue
        path, _, frag = href.partition("#")
        tgt = b if path == "" else path
        if path and not os.path.exists(os.path.join(D, path)):
            print(f"[連結] {b} → 檔案不存在 {href}"); bad += 1; continue
        if frag and tgt.endswith(".html") and frag not in ids.get(tgt, set()):
            print(f"[錨點] {b} → {href} 對不到 id"); bad += 1
    for src in re.findall(r'src="([^"]+)"', s):
        if not src.startswith("http") and not os.path.exists(os.path.join(D, src)):
            print(f"[圖檔] {b} → {src} 不存在"); bad += 1
    # 3 中文句子夾雜英文
    txt = re.sub(r'<(script|style|pre|code)\b.*?</\1>', ' ', s, flags=re.S)
    txt = re.sub(r'<[^>]+>', ' ', txt)
    for m in re.finditer(r'[一-鿿][a-z]{3,}[一-鿿]', txt):
        print(f"[夾雜] {b} … {m.group(0)}"); bad += 1
    # 另一道：佔位字樣指的那一頁，現在存不存在
    # **視窗要用 [^\n] 不能用 [^\s]**：標題裡的是全形空格（U+3000），
    # \s 吃得下它，於是 `PART 8` 會被切在視窗外——第一版就是這樣放行的。
    # 編號取最靠近那句話的那一個（同一行可能有別的 PART）。
    for m in re.finditer(r'[^\n]{0,40}(?:尚未發布|還沒發布|即將推出|待補)[^\n]{0,8}', txt):
        seg = re.sub(r'\s+', ' ', m.group(0)).strip()
        n = re.findall(r'PART\s*(\d+)', seg)
        tgt = parts.get(n[-1]) if n else None
        if tgt:
            print(f"[佔位] {b} 寫著「{seg}」，但 {tgt} 已經有了"); bad += 1
        else:
            print(f"[佔位] {b} … {seg}（指的那一頁還沒有，先留著）")

    # 6 SVG 內不得有 <b>
    for m in re.finditer(r'<svg\b.*?</svg>', s, flags=re.S):
        if "<b>" in m.group(0):
            print(f"[SVG] {b} 內含 <b>"); bad += 1
print("=== 稽核 1/2/3/6：", "全部通過" if bad == 0 else f"{bad} 個問題")
