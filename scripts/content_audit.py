#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""內容稽核：規範第 10 節那幾道「要人看、程式只負責抽出來」的檢查。

    10  每個術語的第一次出現，那個位置有沒有定義        → terms
    11  列著多個可選值的表，有沒有標「我們用哪一個」    → tables
    12  口語與擬人的說法（判準：它在不在「白話」框裡）  → slang
     5  指涉詞有沒有指名對象                            → refs

  `refs` 是 2026-09-14 補的，來源是 _notes 第 45 條：使用者抓到
  「那四支『神經元』查詢」沒指名是哪四支——而**六道稽核一道都沒響**，
  因為規範第 10 節第 5 道當時完全沒有程式在守。

  **為什麼自己複查抓不到**：寫的人腦子裡有那張表，「那四支」讀起來完全清楚。
  所以這一道的定位是**抽出來給人看**，不判對錯——跟上面三道一樣。

  **同一輪還試過第二種抽法「未綁定的簡稱」，兩種設計都失敗，已移除**（_notes 第 46 條）。
  不要再做一次：失敗的原因不是實作，是這個專題的頁面本來就會在表格裡
  用中文描述每一列，所以簡稱其實早就鬆散地綁住了。

  用法：
    python3 scripts/content_audit.py terms     part3-queries.html
    python3 scripts/content_audit.py tables    part3-queries.html
    python3 scripts/content_audit.py slang     part3-queries.html
    python3 scripts/content_audit.py refs      part3-queries.html
    python3 scripts/content_audit.py nums      part3-queries.html   （第 4 節：抽數字與上下文）

  換一個專題時，改 TERMS 與 SLANG 兩份清單即可。
"""
import io, re, sys, glob, os

# 這個專題會用到的術語（換專題時改這一份）
TERMS = ["template", "registration", "對位", "painted domain", "分區", "體素", "神經氈",
         "剛體", "仿射", "非剛體", "參考頻道", "nc82", "Bruchpilot", "CMTK", "自由度",
         "bridging", "橋接", "質心", "殘差", "中位數", "百分位", "座標系", "座標框",
         "視葉", "蕈狀體", "觸角葉", "顎神經節", "中線", "半腦", "突觸", "神經突", "膨大處",
         "知識庫", "本體論", "連線體", "平均腦", "標準腦", "電子顯微鏡", "螢光顯微鏡",
         "資料集", "版本", "授權", "投影", "背側", "腹側", "矢狀",
         # PART 2 新增
         "類別", "個體", "別名", "同義詞", "完全同義", "相關同義", "萬用字元",
         "詞條", "永久編號", "解剖本體論"]

# 會被讀成字面的口語／擬人詞（換專題時視領域增刪）
SLANG = ["餵進去", "爆掉", "一堆", "沒有身分", "隨手", "擋光", "吞下", "亂寫",
         "跑掉", "搬過去", "撈", "死掉", "活著", "長出來", "抓一把", "看圖說話"]

MARK = re.compile(r"本專題採用|我們用的|論文的字面|指令指定用這個|← ")

# 指涉詞：這些話把讀者指向「別的地方」，而讀者在長頁面上找不到那個地方。
# 規矩是一律寫成「上面〈某某小標〉那張表」這種指得到的形式。
# **阿拉伯數字那一支是 2026-09-15 補的**：使用者問「那 21 筆是哪 21 筆？
# 距離上次提到已經很遠了」——而原本的字元集只收中文數字、單位也只收
# 支個張條節處，所以「那 21 筆」整個漏掉。回指跟數字是用哪一種字寫的無關。
REFS = [r"那\s*[一二三四五六七八九十百幾兩]+\s*[支個張條節處張筆列項顆組]",
        r"那\s*[\d][\d,]*\s*[支個張條節處筆列項顆組]",
        r"這\s*[一二三四五六七八九十百幾兩]+\s*[支個張條節處]",
        r"上面那", r"下面那", r"前面那", r"剛剛那", r"上一節", r"下一節",
        r"上表", r"下表", r"上圖", r"下圖", r"這張表", r"那張表", r"這一段"]

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


def refs(path):
    t = text_of(path)
    n = 0
    for pat in REFS:
        for m in re.finditer(pat, t):
            print(f"【{m.group(0)}】…{t[max(0, m.start() - 60):m.end() + 60]}…")
            n += 1
    print(f"\n（{n} 處。逐條問一次：**它指的那個東西，在這一句裡叫得出名字嗎？**"
          f"叫不出來就寫成「上面〈某某小標〉那張表」。）")

    # ── 節標題裡的回指：這一種不是「給人看」，是錯 ──
    # h2 會被抽進本頁章節，跟上下文完全分開；讀者在目錄上看到「那 21 筆」，
    # 沒有任何東西可以讓他知道那是哪 21 筆。**節標題必須自己站得住。**
    # **只管 h2**：h3 是讀在它的 h2 底下的，不會被單獨抽出來。
    src = io.open(path, encoding="utf-8").read()
    heads = [re.sub(r"<[^>]+>", "", h) for h in
             re.findall(r"<h2[^>]*>(.*?)</h2>", src, flags=re.S)]
    # **判準是「量詞後面有沒有接上名字」，不是「有沒有出現量詞」。**
    # 第一版只比對形式，結果把三個已經指名的標題也叫出來——
    # 一道會喊狼的稽核，跟沒有那道稽核是同一件事。
    #   那 21 筆差在哪裡            筆後面接「差」，沒說是什麼的 21 筆 → 錯
    #   這十條指令其實是一份規格書   接了「指令」                      → 沒問題
    #   讀旁證那一支 cross_check.py  接了檔名                          → 沒問題
    UNBOUND_NEXT = "的差為是在就而，、：。？！」）)"

    def unbound(h):
        for pat in REFS:
            for m in re.finditer(pat, h):
                tail = h[m.end():].lstrip()
                if (not tail) or tail[0] in UNBOUND_NEXT:
                    return m.group(0)
        return None

    bad = [(h.strip(), u) for h in heads if (u := unbound(h))]
    for h, u in bad:
        print(f"[標題回指] 「{h}」——「{u}」後面沒有接上名字，"
              f"而標題會被抽進目錄，那裡沒有上下文")
    print(f"（節標題 {len(heads)} 個，其中 {len(bad)} 個帶回指"
          f"{'。這一種是錯，不是「給人看」' if bad else ''}）")


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
        {"terms": terms, "tables": tables, "slang": slang, "nums": nums,
         "refs": refs}[mode](f)
