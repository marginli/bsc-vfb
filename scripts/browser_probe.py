#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""browser_probe.py — 用真的瀏覽器把「學員會看到的畫面」抓一遍，存進 out/ui/。

這支跟 vfb_probe.py 是一對，分工很清楚：

    vfb_probe.py     問 API  →  資料庫裡有什麼        →  out/*.json
    browser_probe.py 看畫面  →  學員螢幕上有什麼      →  out/ui/*.json

**為什麼需要兩支。** types/tool.md〈滑鼠那一層〉第四條寫著「讀 API 回傳、
讀前端原始碼，都不等於看過畫面」。這條規矩之前沒有程式可以執行——
所有介面描述都是從 API 回傳或從 bundle 推出來的，而 _notes 第 16～20 條
（連續五條）全部是這樣推錯的。這支程式就是那條規矩的執行者。

**它證明過一次自己有用。** 文件站搜尋框那個「打 JRC2018Unisex 找不到
JRC2018Unisex」的現象，靜態分析追了三輪都重現不出來（_notes 第 17 條寫
「我重現不出來」）。這支跑一次就拍到了，原因是前端送出前把字串轉小寫
——那是讀 bundle 讀不出來的，因為轉小寫的那一行跟送出的那一行隔得很遠。

用法：
    python3 scripts/browser_probe.py              # 跑全部（約 3 分鐘）
    python3 scripts/browser_probe.py --list
    python3 scripts/browser_probe.py --only palette terminfo_v2_template

設計上的四個決定：

1. **資料檔裡不放時間戳**，放 out/ui/_manifest.json。跟 vfb_probe.py 同一條理由：
   否則每次重跑每個檔案都被標成「變了」，真的變動反而看不見。
2. **絕不繼承 DISPLAY。** 第一行就 `os.environ.pop("DISPLAY")`。
   這台機器是從 Windows 用 MobaXterm 連進來的，DISPLAY 指向使用者的螢幕；
   繼承它會讓瀏覽器視窗跳到使用者臉上。要看畫面就開 Xvfb（--display :99）。
3. **用系統的 Google Chrome，不跑 `playwright install`。**
   後者會再下載一整份瀏覽器，而且要 sudo 裝系統相依套件（這台 sudo 要密碼）。
4. **每一支探針都存截圖。** JSON 會漏掉版面（例如「只顯示 8 列」這件事），
   而截圖是唯一看得出「學員眼睛看到什麼」的東西。截圖不進版控，見 .gitignore。

**這支程式自己踩過的坑，寫在這裡免得重踩：**

- `type(delay=…)` 對命令面板**會掉字**：面板開啟後還會重新聚焦一次，
  前幾個字被吃掉，於是搜尋的是 `C2018Unisex` 而不是 `JRC2018Unisex`，
  畫面顯示 No match。一律用 `fill()` 再 assert 輸入框的內容。
- v2／v3 是重量級前端（geppetto ＋ WebGL），`networkidle` 永遠等不到。
  用固定等待，並且**用畫面上該出現的字串當完成條件**（`expect_text`）。
- 無頭模式要開 swiftshader，否則 3D 那兩格是空的（不影響 Term Info，但截圖會難看）。
"""
from __future__ import annotations

import os

os.environ.pop("DISPLAY", None)  # ← 必須在 import playwright 之前

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("需要 playwright：pip install --user playwright\n"
             "（不必跑 playwright install，本程式用系統的 /usr/bin/google-chrome）")

ROOT = Path("/home/wanjuli/claude_linux/BSC_plan/specific_topics/VFB")
OUT = ROOT / "out" / "ui"
SHOTS = OUT / "shots"

CHROME = "/usr/bin/google-chrome"
ARGS = ["--no-sandbox", "--disable-dev-shm-usage",
        "--use-gl=swiftshader", "--enable-unsafe-swiftshader"]

# 三個網站。它們是三個不同的東西，這件事本身就是 PART 2 的教材。
DOCS = "https://www.virtualflybrain.org/"
V2 = "https://v2.virtualflybrain.org/org.geppetto.frontend/geppetto"
V3 = "https://v3.virtualflybrain.org/"

# 教材固定的例子，跟 vfb_probe.py 用同一組，不要各用各的
EX_TEMPLATE = "VFB_00101567"   # JRC2018Unisex；PART 1 作業單第 1 步
EX_NEURON = "VFB_00005010"     # Cha-F-100205；PART 1 作業單第 4 步
EX_REGION_NAME = "medulla"     # PART 2 的主例
EX_REGION = "FBbt_00003748"    # medulla 這個「類別」本身（跟 vfb_probe.py 同一個例子）
EX_REGION_INDIV = "VFB_00102107"  # 它畫在 JRC2018Unisex 上的那一個「個體」

PROBES: dict[str, dict] = {}


def probe(name: str, part: str, question: str):
    def deco(fn):
        PROBES[name] = {"fn": fn, "part": part, "question": question}
        return fn
    return deco


# ══════════════════════════════════════════════════════════════════
# 共用
# ══════════════════════════════════════════════════════════════════
def new_page(pw, width=1600, height=1000):
    b = pw.chromium.launch(executable_path=CHROME, headless=True, args=ARGS)
    return b, b.new_page(viewport={"width": width, "height": height})


def open_palette(pg):
    """把文件站的命令面板叫出來，回傳輸入框。

    它不是 <input>，是 header 上一顆寫著 `Search VFB… ⌘K` 的按鈕；
    點下去才長出 #palette-input。第一版探針就是在這裡回報「找不到輸入框」的。
    """
    pg.locator("button:has-text('Search'), [aria-label*='earch'], [class*='earch']").first.click(timeout=8000)
    inp = pg.locator("#palette-input")
    inp.wait_for(state="visible", timeout=15000)
    pg.wait_for_timeout(2000)   # 面板開啟後還會重新聚焦一次，等它穩
    return inp


def type_exact(pg, inp, term: str):
    """填字串並確認真的填進去了。see module docstring：type() 會掉字。"""
    inp.fill(term)
    got = inp.input_value()
    if got != term:
        raise RuntimeError(f"輸入框內容不符：想打 {term!r}，實際是 {got!r}")
    pg.wait_for_timeout(6000)


def panel_lines(pg, selector: str) -> list[str]:
    """把一個面板的 innerText 拆成非空行。欄位名與值都在裡面，順序就是畫面順序。"""
    txt = pg.locator(selector).first.inner_text()
    return [ln.strip() for ln in txt.splitlines() if ln.strip()]


def smallest_containing(pg, markers: list[str], cap: int = 4000) -> list[str]:
    """回傳「同時包含這幾個字串的最小元素」的 innerText 行序列。

    **為什麼不用 CSS 選擇器**：v3 是 MUI，class 名長成 `css-1p5s0j1`，
    是編譯時產生的，改版就換一組。用畫面上看得到的字去定位才撐得過改版。
    """
    txt = pg.evaluate(
        """([markers, cap]) => {
            const all = [...document.querySelectorAll('div,section,aside,main')]
              .filter(e => { const t = e.innerText || '';
                             return t.length < cap && markers.every(m => t.includes(m)); });
            if (!all.length) return null;
            all.sort((a, b) => (a.innerText||'').length - (b.innerText||'').length);
            return all[0].innerText; }""", [markers, cap])
    if txt is None:
        raise RuntimeError(f"找不到同時包含 {markers} 的元素（畫面可能還沒載完，或介面改版了）")
    return [ln.strip() for ln in txt.splitlines() if ln.strip()]


def fields_from_lines(lines: list[str], names: list[str], stop_re: str | None = None) -> dict:
    """從 innerText 的行序列裡，把指定欄位名後面那幾行收成它的值。

    v2／v3 的面板都是「欄位名一行、值接在後面」的排法，所以下一個欄位名出現
    就是上一個欄位的結束。**不要改成用 CSS 選擇器抓**——兩版的 DOM 結構
    完全不同，而行序列兩版通用。
    """
    idx = {n: i for i, ln in enumerate(lines) for n in names if ln == n}
    # 區塊標題（例如 v3 的 `Queries (4)`）也是結束點，否則上一欄會把後面整段吞進來
    stops = set(idx.values())
    if stop_re:
        stops |= {i for i, ln in enumerate(lines) if re.fullmatch(stop_re, ln)}
    out = {}
    for n, i in idx.items():
        stop = min([j for j in stops if j > i], default=len(lines))
        out[n] = lines[i + 1:stop]
    return out


# 這段 JS 刻意一個反斜線都不用（換行用 String.fromCharCode(10)、括號用字元比較）。
# 理由：它要穿過 Python 字串 → 檔案 → Playwright → JS 四層，
# 每多一個反斜線就多一次跳脫錯誤，而錯了只會得到一句 SyntaxError。
_RESULT_ROWS_JS = """(term) => {
  const seen = new Set(), out = [], NL = String.fromCharCode(10);
  for (const e of document.querySelectorAll('div,span,a,li,p')) {   // p 不能漏，v3 的結果列就在 <p> 裡
    if (e.getClientRects().length === 0) continue;   // 浮層是 position:fixed，offsetParent 會是 null
    const t = (e.innerText || '').trim();
    if (!t) continue;
    // 取第一行：v2 把標題與類別徽章放在同一個 <li> 裡（標題 ⏎ Visual_system ⏎ …），
    // 要求「整個元素只有一行」會把 v2 的每一列都篩掉。
    const first = (t.split(NL)[0] || '').trim();
    if (!first || first.length > 90) continue;
    if (first.toLowerCase().indexOf(term.toLowerCase()) < 0) continue;
    if (first.indexOf('(') < 0 || first.charAt(first.length - 1) !== ')') continue;
    if (seen.has(first)) continue;
    seen.add(first); out.push(first);
  }
  return out; }"""


def result_rows(pg, term: str) -> list[str]:
    """抓搜尋結果列。三個框的列都長成 `名字 (別名或編號)`，所以共用一支。

    **不要改成用標籤名抓**：v2 那個應用程式的 DOM 裡有一千五百個 `<li>`，
    用 `li` 當選擇器等於把整個頁面抓回來（實測 159 KB）。

    兩個踩過的坑：
    - **可見性不能用 `offsetParent`**。三個框的結果清單都是 `position: fixed` 的浮層，
      浮層裡每一個元素的 `offsetParent` 都是 `null`，整份結果會被判成看不見。
      用 `getClientRects().length`。
    - **選擇器裡不能漏掉 `p`**。v3 的結果列文字就在 `<p>` 裡，漏掉它回傳 0 列——
      而且 0 列不會報錯，只會讓頁面上少一張表。
    """
    return pg.evaluate(_RESULT_ROWS_JS, term)


def solr_crosscheck(url: str | None) -> dict:
    """把畫面上的列數跟它自己那支查詢對一次。

    types/tool.md〈稽核〉那條「有沒有第二條路可以問到同一個數字」的程式版：
    畫面上有幾列、SOLR 回了幾個詞、資料庫裡符合的有幾個——**這是三個數字**，
    而教材最容易寫錯的就是拿其中一個去講另一個。
    """
    if not url:
        return {}
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            d = json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        return {"error": str(e)[:120]}
    resp = d.get("response") or {}
    docs = resp.get("docs") or []
    return {"solr_numFound": resp.get("numFound"),
            "solr_rows_returned": len(docs),
            "solr_distinct_terms": len({x.get("short_form") for x in docs}),
            "rows_param": urllib.parse.parse_qs(
                urllib.parse.urlparse(url).query).get("rows", [None])[0]}


def shot(pg, name: str, **kw):
    SHOTS.mkdir(parents=True, exist_ok=True)
    pg.screenshot(path=str(SHOTS / f"{name}.png"), **kw)


# ══════════════════════════════════════════════════════════════════
# 探針
# ══════════════════════════════════════════════════════════════════
@probe("palette", "PART 2",
       "文件站的搜尋框：打一個字串，前端實際送出什麼、畫面上實際出現幾列")
def _palette(pw):
    """這一支回答 _notes 第 16～20 條追了五輪的那個問題。

    三個受測字串是有理由的：
      JRC2018Unisex  學員照 PART 1 的表抄下來的正式名 → 找不到目標
      jrc2018unisex  全小寫 → 證明前端本來就轉小寫，大小寫不在學員手上
      JRC2018U       Symbol 欄那個短名 → 唯一找得到的打法
    """
    b, pg = new_page(pw, 1500, 950)
    res = {}
    sent: list[str] = []
    pg.on("request", lambda r: sent.append(r.url) if "solr" in r.url else None)
    try:
        for term in ("JRC2018Unisex", "jrc2018unisex", "JRC2018U", EX_REGION_NAME):
            sent.clear()
            pg.goto(DOCS, wait_until="domcontentloaded", timeout=90000)
            pg.wait_for_timeout(8000)
            inp = open_palette(pg)
            type_exact(pg, inp, term)

            rows = [t.strip() for t in pg.locator("#palette-results > li").all_inner_texts()
                    if t.strip()]
            # 面板把結果分組，組標題自己也是一個 <li>（例如
            # `ANATOMY TERMS · OPENS IN THE 3D BROWSER`）。組標題只有一行，
            # 結果列有兩行以上。**算「幾筆」的時候不要把組標題算進去。**
            groups, items = [], []
            for r in rows:
                ln = r.splitlines()
                if len(ln) == 1:
                    groups.append(ln[0])
                    continue
                m = re.match(r"^([A-Za-z]+_\d+|VFB[A-Za-z_]*\d+) — (.*)$", ln[1].strip())
                items.append({"title": ln[0].strip(),
                              "id": m.group(1) if m else None,
                              "facets": m.group(2).split(" · ") if m else None,
                              "second_line": None if m else ln[1].strip(),
                              "badge": ln[-1].strip() if len(ln) > 2 else None,
                              "group": groups[-1] if groups else None})
            q = None
            if sent:
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(sent[-1]).query)
                q = (qs.get("q") or [None])[0]
            res[term] = {
                "typed": term,
                "q_sent_to_solr": q,
                "solr_url": sent[-1] if sent else None,
                "n_requests_while_typing": len(sent),
                "group_headings": groups,
                "results_on_screen": items,
                "n_results_on_screen": len(items),
                # 分組標題只有一個（ANATOMY TERMS…），但列尾的徽章分兩種：
                # `term` 是本體論的詞、`docs` 是說明文件的頁面。**這兩種是不同的東西**，
                # 而畫面上的 8 筆上限只管 term 那一種。
                "n_results_by_badge": {b: sum(1 for it in items if it["badge"] == b)
                                       for b in dict.fromkeys(it["badge"] for it in items)},
                "target_on_screen": any(EX_TEMPLATE == (it["id"] or "") for it in items),
                "rows_raw": rows,
            }
            shot(pg, f"palette_{re.sub(r'[^A-Za-z0-9]+', '_', term)}")
    finally:
        b.close()
    return {
        "site": DOCS,
        "what_it_is": ("文件站 header 的 `Search VFB… ⌘K`。它不是 <input>，是命令面板的觸發鈕；"
                       "打的是 solr.virtualflybrain.org/solr/ontology/select，rows=40，畫面顯示 8 列。"),
        "by_term": res,
    }


@probe("terminfo_v2_template", "PART 1 作業單第 1–2 步 / PART 2",
       "v2 的 Term Info 面板上，這顆 template 的每一欄叫什麼、值是什麼")
def _terminfo_v2_template(pw):
    b, pg = new_page(pw)
    try:
        pg.goto(f"{V2}?id={EX_TEMPLATE}", wait_until="domcontentloaded", timeout=90000)
        pg.wait_for_timeout(32000)
        lines = panel_lines(pg, "#vfbterminfowidget")
        shot(pg, "terminfo_v2_template")
        names = ["Symbol", "Name", "Classification", "Thumbnail", "Query For",
                 "Graphs For", "Description", "Source", "License", "Licenses",
                 "Aligned To", "Aligned to", "Downloads"]
        return {
            "site": V2, "id": EX_TEMPLATE,
            "url": f"{V2}?id={EX_TEMPLATE}",
            "panel": "Term Info 分頁",
            "field_order_on_screen": [ln for ln in lines if ln in names],
            "fields": fields_from_lines(lines, names),
            "all_lines": lines,
        }
    finally:
        b.close()


@probe("terminfo_v3_template", "PART 1 作業單第 1–2 步 / PART 2",
       "v3 的左側資訊欄上，同一顆 template 的每一欄叫什麼、值是什麼")
def _terminfo_v3_template(pw):
    b, pg = new_page(pw)
    try:
        pg.goto(f"{V3}?id={EX_TEMPLATE}", wait_until="domcontentloaded", timeout=90000)
        pg.wait_for_timeout(35000)
        lines = smallest_containing(pg, ["General Information", "Metadata", "Aligned To"])
        shot(pg, "terminfo_v3_template")
        names = ["General Information", "Metadata", "Graphs", "Name", "Symbol", "ID",
                 "Licenses", "License", "Tags", "Description", "Types",
                 "Aligned To", "Aligned to"]
        qre = r"Queries \(\d+\)"
        keep = [ln for ln in lines if ln in names or re.fullmatch(qre, ln)]
        return {
            "site": V3, "id": EX_TEMPLATE,
            "url": f"{V3}?id={EX_TEMPLATE}",
            "panel": "左側資訊欄（分成 General Information／Metadata／Queries (n)／Graphs 四區）",
            "field_order_on_screen": keep,
            "fields": fields_from_lines(lines, names, stop_re=qre),
            "all_lines": lines,
        }
    finally:
        b.close()


@probe("terminfo_v2_region", "PART 2",
       "一個腦區（類別）的 Term Info 面板有哪些欄？跟 template（個體）差在哪？")
def _terminfo_v2_region(pw):
    """PART 2 的作業單要叫學員去看同義詞那一欄，所以得先確認那一欄在畫面上叫什麼。

    類別與個體的面板欄位**不一樣**——這一支就是拿來跟 terminfo_v2_template
    並排的：類別有 Synonyms 與 Examples，沒有 License 也沒有 Downloads。
    """
    b, pg = new_page(pw)
    try:
        pg.goto(f"{V2}?id={EX_REGION}", wait_until="domcontentloaded", timeout=90000)
        pg.wait_for_timeout(32000)
        lines = panel_lines(pg, "#vfbterminfowidget")
        shot(pg, "terminfo_v2_region")
        names = ["Symbol", "Name", "Synonyms", "Alternative Names", "Classification",
                 "Relationships", "Thumbnail", "Query For", "Graphs For", "Description",
                 "Source", "License", "Licenses", "Aligned To", "Downloads",
                 "Examples", "References", "Cross References", "Comment"]
        return {
            "site": V2, "id": EX_REGION,
            "url": f"{V2}?id={EX_REGION}",
            "field_order_on_screen": [ln for ln in lines if ln in names],
            "fields": fields_from_lines(lines, names),
            "all_lines": lines,
        }
    finally:
        b.close()


@probe("terminfo_v2_individual", "PART 2 作業單第 3 步",
       "同一塊腦區的「個體」，畫面上比「類別」多了哪幾欄、值是什麼")
def _terminfo_v2_individual(pw):
    """作業單第 3 步叫學員比較類別與個體的面板，所以兩邊都得親眼拍過。

    **不要用 API 的值去寫這一步**：`Aligned To` 這一欄在畫面上列的是短名
    （Symbol），而 API 回的是編號——PART 1 就是這樣寫錯過一次（_notes 第 31 條）。
    """
    b, pg = new_page(pw)
    try:
        pg.goto(f"{V2}?id={EX_REGION_INDIV}", wait_until="domcontentloaded", timeout=90000)
        pg.wait_for_timeout(32000)
        lines = panel_lines(pg, "#vfbterminfowidget")
        shot(pg, "terminfo_v2_individual")
        names = ["Symbol", "Name", "Alternative Names", "Classification", "Relationships",
                 "Query For", "Graphs For", "Description", "Source", "License", "Licenses",
                 "Aligned To", "Downloads", "Examples", "References", "Cross References"]
        return {
            "site": V2, "id": EX_REGION_INDIV,
            "url": f"{V2}?id={EX_REGION_INDIV}",
            "field_order_on_screen": [ln for ln in lines if ln in names],
            "fields": fields_from_lines(lines, names),
            "all_lines": lines,
        }
    finally:
        b.close()


@probe("terminfo_v2_neuron", "PART 1 作業單第 4 步",
       "作業單叫學員看的 Aligned To 欄，畫面上實際列出哪幾套 template")
def _terminfo_v2_neuron(pw):
    b, pg = new_page(pw)
    try:
        pg.goto(f"{V2}?id={EX_NEURON}", wait_until="domcontentloaded", timeout=90000)
        pg.wait_for_timeout(32000)
        lines = panel_lines(pg, "#vfbterminfowidget")
        shot(pg, "terminfo_v2_neuron")
        names = ["Symbol", "Name", "Classification", "Query For", "Description",
                 "Source", "License", "Licenses", "Aligned To", "Aligned to", "Downloads"]
        return {
            "site": V2, "id": EX_NEURON,
            "url": f"{V2}?id={EX_NEURON}",
            "field_order_on_screen": [ln for ln in lines if ln in names],
            "fields": fields_from_lines(lines, names),
            "all_lines": lines,
        }
    finally:
        b.close()


@probe("search_v3", "PART 2",
       "v3 的 `Find something...` 搜尋框：送出什麼、畫面上出現什麼")
def _search_v3(pw):
    b, pg = new_page(pw)
    try:
        sent: list[str] = []
        pg.on("request", lambda r: sent.append(r.url) if "solr" in r.url else None)
        pg.goto(V3, wait_until="domcontentloaded", timeout=90000)
        pg.wait_for_timeout(30000)
        inp = pg.locator("#customized-hook")
        inp.wait_for(state="visible", timeout=20000)
        inp.click()
        type_exact(pg, inp, EX_REGION_NAME)
        shot(pg, "search_v3")
        q = None
        if sent:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(sent[-1]).query)
            q = (qs.get("q") or [None])[0]
            if q is None and "json=" in sent[-1]:
                q = json.loads((qs.get("json") or ["{}"])[0]).get("params", {}).get("q")
        rows = result_rows(pg, EX_REGION_NAME)
        return {
            "site": V3, "box": "`Find something...`（id=customized-hook）",
            "typed": EX_REGION_NAME,
            "q_sent_to_solr": q,
            "solr_url": sent[-1] if sent else None,
            "note": ("v3 把你打的字**展開成萬用字元查詢**再送出——打 medulla，送出的是 "
                     "`medulla OR medulla* OR *medulla*`。文件站那個框不展開。"),
            # 只存前 60 列。v2 打一個 medulla 就有一千四百多列，
            # 整份存下來會讓這個檔案變成 80 KB 的雜訊；要引用的是列數，不是每一列。
            "rows_on_screen": rows[:60],
            "rows_truncated": len(rows) > 60,
            "n_rows_on_screen": len(rows),
            "crosscheck": solr_crosscheck(sent[-1] if sent else None),
        }
    finally:
        b.close()


@probe("search_v2", "PART 2",
       "v2 的搜尋框（頂列放大鏡）：送出什麼、畫面上出現什麼")
def _search_v2(pw):
    """v2 的搜尋框藏在頂列一顆放大鏡圖示後面（`title="Search"` 的 <i>），
    點下去才長出 `#searchInput`。三個框裡只有這一個要先點圖示。
    """
    b, pg = new_page(pw)
    try:
        sent: list[str] = []
        pg.on("request", lambda r: sent.append(r.url) if "solr" in r.url else None)
        pg.goto(V2, wait_until="domcontentloaded", timeout=90000)
        pg.wait_for_timeout(30000)
        # 不帶 ?id= 進來時，v2 會跳一個 Quick Help 對話框蓋住結果，先關掉
        try:
            pg.get_by_text("SKIP INTRO", exact=False).first.click(timeout=5000)
            pg.wait_for_timeout(1500)
        except Exception:
            pass
        pg.locator("[title='Search']").first.click(timeout=10000)
        inp = pg.locator("#searchInput")
        inp.wait_for(state="visible", timeout=15000)
        pg.wait_for_timeout(1500)
        type_exact(pg, inp, EX_REGION_NAME)
        shot(pg, "search_v2")
        q = None
        if sent:
            u = sent[-1]
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
            q = (qs.get("q") or [None])[0]
            if q is None and "json" in qs:
                q = json.loads(qs["json"][0]).get("params", {}).get("q")
        rows = result_rows(pg, EX_REGION_NAME)
        return {
            "site": V2, "box": "頂列放大鏡圖示（`title=\"Search\"`）→ `#searchInput`",
            "typed": EX_REGION_NAME,
            "q_sent_to_solr": q,
            "solr_url": sent[-1] if sent else None,
            "note": ("v2 的結果是**整頁覆蓋的清單**，不是下拉選單，右邊還有一個 Filters 面板。"
                     "同一個詞會因為正式名與同義詞各佔一列"
                     "（`medulla (FBbt_00003748)` 與 `optic medulla (medulla)` 是同一個 FBbt）。"),
            # 只存前 60 列。v2 打一個 medulla 就有一千四百多列，
            # 整份存下來會讓這個檔案變成 80 KB 的雜訊；要引用的是列數，不是每一列。
            "rows_on_screen": rows[:60],
            "rows_truncated": len(rows) > 60,
            "n_rows_on_screen": len(rows),
            "crosscheck": solr_crosscheck(sent[-1] if sent else None),
        }
    finally:
        b.close()


# ══════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════
def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", nargs="+", metavar="NAME")
    a = ap.parse_args()

    if a.list:
        for n, m in PROBES.items():
            print(f"  {n:24s} {m['part']:28s} {m['question']}")
        return 0

    names = a.only or list(PROBES)
    bad = [n for n in names if n not in PROBES]
    if bad:
        return print(f"沒有這幾支探針：{bad}") or 2

    OUT.mkdir(parents=True, exist_ok=True)
    man_path = OUT / "_manifest.json"
    man = json.loads(man_path.read_text("utf-8")) if man_path.exists() else {"probes": {}}
    old = {n: (OUT / f"{n}.json").exists() and sha(OUT / f"{n}.json") for n in names}

    changed, failed = [], []
    with sync_playwright() as pw:
        for n in names:
            m = PROBES[n]
            print(f"  {n:24s} …", end="", flush=True)
            t0 = time.time()
            try:
                data = m["fn"](pw)
            except Exception as e:
                failed.append((n, str(e)[:160]))
                print(f" 失敗：{str(e)[:60]}")
                continue
            secs = round(time.time() - t0, 1)
            payload = {"probe": n, "part": m["part"], "question": m["question"], **data}
            p = OUT / f"{n}.json"
            p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
            h = sha(p)
            if old.get(n) and old[n] != h:
                changed.append(n)
            man["probes"][n] = {"sha256": h, "seconds": secs,
                                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            print(f" {secs:5.1f}s  {len(json.dumps(payload))/1024:5.1f} KB")

    man["run_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    man["note"] = ("這裡記的是**畫面**，不是資料庫。介面改版時這些檔案會變，"
                   "而那正是要回頭複查介面描述的信號（types/tool.md〈這一型的時效〉）。")
    man_path.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", "utf-8")

    print()
    if changed:
        print("⚠ 內容變了（介面可能改版，回頭複查頁面上的介面描述）：", ", ".join(changed))
    if failed:
        print("✗ 失敗：")
        for n, e in failed:
            print(f"    {n}: {e}")
        return 1
    print("完成。截圖在 out/ui/shots/（不進版控）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
