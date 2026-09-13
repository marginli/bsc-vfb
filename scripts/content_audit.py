#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""內容稽核：規範第 10 節的第 10、11、12 道——這三道要人看，程式只負責「抽出來」。

    10  每個術語的第一次出現，那個位置有沒有定義
    11  列著多個可選值的表，有沒有標「我們用哪一個／論文說的是哪一個」
    12  口語與擬人的說法（判準：它在不在「白話」框裡）

  用法：
    python3 scripts/content_audit.py terms  how-to-draw-lpu.html
    python3 scripts/content_audit.py tables how-to-draw-lpu.html
    python3 scripts/content_audit.py slang  how-to-draw-lpu.html
    python3 scripts/content_audit.py nums   how-to-draw-lpu.html   （第 4 節：抽出所有數字與上下文）

  換一個專題時，改 TERMS 與 SLANG 兩份清單即可。
"""
import io, re, sys, glob, os

# 這個專題會用到的術語（換專題時改這一份）
TERMS = ["template", "registration", "對位", "painted domain", "分區", "體素", "神經氈",
         "剛體", "仿射", "非剛體", "參考頻道", "nc82", "Bruchpilot", "CMTK", "自由度",
         "bridging", "橋接", "質心", "殘差", "中位數", "百分位", "座標系", "座標框",
         "視葉", "蕈狀體", "觸角葉", "顎神經節", "中線", "半腦", "突觸", "神經突", "膨大處",
         "知識庫", "本體論", "連線體", "平均腦", "標準腦", "電子顯微鏡", "螢光顯微鏡",
         "資料集", "版本", "授權", "投影", "背側", "腹側", "矢狀"]

# 會被讀成字面的口語／擬人詞（換專題時視領域增刪）
SLANG = ["餵進去", "爆掉", "一堆", "沒有身分", "隨手", "擋光", "吞下", "亂寫",
         "跑掉", "搬過去", "撈", "死掉", "活著", "長出來", "抓一把", "看圖說話"]

MARK = re.compile(r"本專題採用|我們用的|論文的字面|指令指定用這個|← ")


def text_of(path, keep_pre=False):
    s = io.open(path, encoding="utf-8").read()
    s = re.sub(r"<svg.*?</svg>", " ［SVG］ ", s, flags=re.S)
    if not keep_pre:
        s = re.sub(r"<(script|style)\b.*?</\1>", " ", s, flags=re.S)
    t = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", re.sub(r"&[a-z]+;", " ", t))


def terms(path):
    t = text_of(path)
    hits = sorted((t.find(w), w) for w in TERMS if t.find(w) >= 0)
    for i, w in hits:
        print(f"【{w}】…{t[max(0, i - 70):i + 70]}…\n")
    print(f"（{len(hits)} 個術語。逐條看「這個位置有沒有定義」——"
          f"目錄與『對照表型』的圖說不算，那是索引不是內文。）")


def tables(path):
    s = io.open(path, encoding="utf-8").read()
    for k, m in enumerate(re.finditer(r"<table>(.*?)</table>", s, re.S), 1):
        rows = re.findall(r"<tr>(.*?)</tr>", m.group(1), re.S)
        cell = lambda r: [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip()[:30]
                          for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
        tag = "有標記" if MARK.search(m.group(1)) else "—    "
        print(f"表 {k:>2}（{len(rows) - 1} 列）{tag} 表頭：{' ｜ '.join(cell(rows[0]))}")
        for r in rows[1:3]:
            print(f"        {' ｜ '.join(cell(r))}")
    print("\n（凡是『一欄列著多個可選值』的，都要標出我們用哪一列、論文說的是哪一列。）")


def slang(path):
    t = text_of(path)
    n = 0
    for w in SLANG:
        for m in re.finditer(re.escape(w), t):
            print(f"【{w}】…{t[max(0, m.start() - 55):m.end() + 55]}…")
            n += 1
    print(f"\n（{n} 處。判準：它在不在「白話」框裡——在框裡是刻意的比喻，在正文裡讀者會照字面讀。）")


def nums(path):
    t = text_of(path)
    for m in re.finditer(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?%?)", t):
        if len(re.sub(r"[^\d]", "", m.group(1))) < 3:
            continue
        print(f"{m.group(1):>12}  …{t[max(0, m.start() - 55):m.end() + 40]}…")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "terms"
    files = sys.argv[2:] or sorted(glob.glob(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "*.html")))
    for f in files:
        print(f"══════ {os.path.basename(f)} ══════")
        {"terms": terms, "tables": tables, "slang": slang, "nums": nums}[mode](f)
