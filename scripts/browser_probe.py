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
QUERY_LABEL = "Neurons with some part in medulla"   # PART 3 主要示範的那一支現成查詢
EX_NEURON_LM = "VFB_00005010"           # Cha-F-100205：PART 5 的主例（FlyCircuit 那一顆）
NBLAST_LABEL = "Neurons with similar morphology to Cha-F-100205 [NBLAST]"
EX_CONNECTOME_NEURON = "VFB_jrmc375t"   # Cm7_L (MaleCNS:41280)：PART 4 的例子，
                                        # 它的 Source 欄同時列著 male-cns 的兩個版本

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


@probe("query_results", "PART 3",
       "跑一支現成查詢，結果表長什麼樣：幾欄、欄名、列裡有什麼、底下有哪些動作")
def _query_results(pw):
    """PART 3 的主體。這一支要回答的是「結果表怎麼讀」，而那是畫面的事——
    API 回的 `headers` 鍵名（id／label／tags／template／technique）
    **跟畫面上的欄名不是同一組**（畫面是 Name／Gross_Type／Template_Space／
    Imaging_Technique／Images）。照 API 寫欄名，學員在畫面上一欄都對不到。
    """
    b, pg = new_page(pw, 1700, 1050)
    try:
        pg.goto(f"{V2}?id={EX_REGION}", wait_until="domcontentloaded", timeout=90000)
        pg.wait_for_timeout(32000)
        # 這一列在 Term Info 面板裡，Playwright 的可見性判定會卡住
        # （面板有捲動容器），所以捲進畫面後用 JS 直接派送 click。
        clicked = pg.evaluate(
            """(label) => {
                const el = [...document.querySelectorAll('*')].filter(
                    e => e.children.length === 0 && (e.innerText || '').trim().includes(label));
                if (!el.length) return false;
                const e = el[el.length - 1];
                e.scrollIntoView({block: 'center'}); e.click(); return true; }""",
            QUERY_LABEL)
        if not clicked:
            raise RuntimeError(f"找不到查詢「{QUERY_LABEL}」——Query For 區的標籤可能改了")
        pg.wait_for_timeout(22000)
        shot(pg, "query_results")

        title = pg.evaluate(
            """() => { const e = [...document.querySelectorAll('*')].find(
                x => x.getClientRects().length
                  && /^[0-9]+ Neurons with some part/.test((x.innerText||'').trim()));
               return e ? e.innerText.trim().split(String.fromCharCode(10))[0] : null; }""")
        cols = pg.evaluate(
            """() => [...document.querySelectorAll('th,[class*=griddle-header],[class*=column]')]
                 .filter(e => e.getClientRects().length)
                 .map(e => (e.innerText || '').trim())
                 .filter(t => t && t.length < 30)""")
        actions = pg.evaluate(
            """() => [...document.querySelectorAll('*')]
                 .filter(e => e.getClientRects().length && e.children.length === 0)
                 .map(e => (e.innerText || '').trim())
                 .filter(t => /Refine|New query|Delete results|Download/.test(t))""")
        # 結果表最關鍵的一件事：**一列是一個「種類」，而 Images 那一欄是一個輪播**，
        # 裡面是好幾個「個體」（一張一張重建出來的神經元）。
        # 這正是 471 與 226,524 在畫面上接起來的地方，所以要專門把它抓出來。
        images_cells = pg.evaluate(
            """() => { const out = [], seen = new Set();
                const NL = String.fromCharCode(10);
                for (const e of document.querySelectorAll('*')) {
                    if (!e.getClientRects().length) continue;
                    // 這一格的文字被拆在好幾個子節點裡，所以不能要求 children.length === 0；
                    // 改成「整個元素只有一行」來擋掉祖先。
                    const t = (e.innerText || '').trim();
                    if (!t || t.indexOf(NL) >= 0 || t.length > 90) continue;
                    if (t.indexOf('aligned to') < 0) continue;
                    if (seen.has(t)) continue; seen.add(t); out.push(t);
                    if (out.length >= 6) break; }
                return out; }""")
        carousel = pg.evaluate(
            """() => document.querySelectorAll('[class*=carousel],[class*=slider]').length""")
        # 篩選是在本地篩已經回來的那些，還是回去問伺服器？這件事決定了
        # 「篩完剩下的數字」能不能拿來當結論，所以要量，不要猜：
        # 打字前後各數一次網路請求。
        net: list[str] = []
        pg.on("request", lambda r: net.append(r.url))
        n_before = len(net)
        count_rows = """() => { const NL = String.fromCharCode(10); let k = 0;
            const seen = new Set();
            for (const e of document.querySelectorAll('*')) {
                if (!e.getClientRects().length) continue;
                const t = (e.innerText || '').trim();
                if (!t || t.indexOf(NL) >= 0 || t.length > 90) continue;
                if (t.indexOf('aligned to') < 0 || seen.has(t)) continue;
                seen.add(t); k++; }
            return k; }"""
        rows_before = pg.evaluate(count_rows)
        # **要 `Filter Results`，不是 `Filter`**：Layers 面板也有一個 placeholder 是
        # `Filter` 的輸入框，`placeholder*='Filter'` 會先抓到它，
        # 於是量到「篩了沒變化」——那是篩錯框，不是篩選沒作用。
        fbox = pg.locator("input[placeholder='Filter Results']").first
        fbox.wait_for(state="visible", timeout=15000)
        fbox.click()
        fbox.type("Cm7", delay=180)      # 這個框吃的是按鍵事件，fill() 不會觸發篩選
        assert fbox.input_value() == "Cm7", f"篩選框內容不符：{fbox.input_value()!r}"
        pg.wait_for_timeout(7000)
        n_after = len(net)
        rows_after = pg.evaluate(count_rows)
        filter_title = pg.evaluate(
            """() => { const e = [...document.querySelectorAll('*')].find(
                   x => x.getClientRects().length
                     && /^[0-9]+ Neurons with some part/.test((x.innerText||'').trim()));
               return e ? e.innerText.trim().split(String.fromCharCode(10))[0] : null; }""")
        for _ in range(3):
            fbox.press("Backspace")
        pg.wait_for_timeout(3000)

        return {
            "site": V2, "region": EX_REGION, "query_label": QUERY_LABEL,
            "url": f"{V2}?id={EX_REGION}",
            "title_bar": title,
            "filter_test": {
                "typed": "Cm7",
                "requests_fired_while_filtering": n_after - n_before,
                "visible_result_rows_before": rows_before,
                "visible_result_rows_after": rows_after,
                "title_bar_while_filtering": filter_title,
                "note": ("打字期間送出的請求數 = 0，就表示篩選是在本地做的"
                         "——篩的是**已經回來的那些**，不是回去重問。"),
            },
            # cols 裡的 Name 會出現兩次（一次來自結果表、一次來自 Layers 面板），去重
            "columns_on_screen": list(dict.fromkeys(
                c for c in cols if c in ("Name", "Gross_Type", "Template_Space",
                                         "Imaging_Technique", "Images ▼", "Images"))),
            "all_header_texts": cols,
            "actions_at_bottom": actions,
            "images_cells_first_rows": images_cells,
            "n_carousel_elements": carousel,
            # 頁面上會逐字引用這個 placeholder，所以要把原文存下來，
            # 不能只存一個 True——`field_audit.py` 對不回去就會叫。
            "filter_box_placeholder": pg.evaluate(
                """() => { const e = [...document.querySelectorAll('input')].find(
                       x => /Filter/i.test(x.placeholder || '') && x.getClientRects().length
                            && (x.placeholder || '').length > 6);
                   return e ? e.placeholder : null; }"""),
        }
    finally:
        b.close()


@probe("viewer_state", "PART 3",
       "把結果表裡的一列載進檢視器之後，畫面上究竟疊著哪幾樣東西")
def _viewer_state(pw):
    """§「三維／切片檢視」那一節只教一件事：**你看到的是什麼**。

    而「看到什麼」在這個介面上有一個可以逐字比對的答案——`Layers` 面板。
    它列出目前載入檢視器的每一樣東西，所以拿它來驗「疊著什麼」比描述畫面可靠。

    這一支同時回答「縮圖與實際載入是兩件事」：結果表裡每一列都有縮圖，
    但 `Layers` 只會多出你**勾選**的那一個。
    """
    b, pg = new_page(pw, 1700, 1050)

    def layers():
        """只取 Layers 面板本身。**不要用「第一個含 Controls 的元素」**——
        那會抓到祖先，把整頁都收進來（實測 14 KB 的雜訊）。取最小的那一個。"""
        return pg.evaluate(
            """() => { const c = [...document.querySelectorAll('div,table,tbody')].filter(x => {
                   const t = x.innerText || '';
                   return x.getClientRects().length && t.length < 700
                          && t.indexOf('Controls') >= 0 && t.indexOf('Thumbnail') >= 0; });
               if (!c.length) return null;
               c.sort((a, b) => a.innerText.length - b.innerText.length);
               return c[0].innerText.split(String.fromCharCode(10))
                        .map(s => s.trim()).filter(Boolean); }""")

    try:
        pg.goto(f"{V2}?id={EX_REGION}", wait_until="domcontentloaded", timeout=90000)
        pg.wait_for_timeout(32000)
        before = layers()
        clicked = pg.evaluate(
            """(label) => {
                const el = [...document.querySelectorAll('*')].filter(
                    e => e.children.length === 0 && (e.innerText || '').trim().includes(label));
                if (!el.length) return false;
                const e = el[el.length - 1];
                e.scrollIntoView({block: 'center'}); e.click(); return true; }""",
            QUERY_LABEL)
        if not clicked:
            raise RuntimeError(f"找不到查詢「{QUERY_LABEL}」")
        pg.wait_for_timeout(22000)
        mid = layers()

        # 勾第一列。Playwright 的 check() 判定這些方塊不可見（它們疊在縮圖上），
        # 所以用 JS 直接勾並派送 change 事件。
        ticked = pg.evaluate(
            """() => { const cb = [...document.querySelectorAll('input[type=checkbox]')]
                        .filter(e => e.getClientRects().length && !e.checked);
                if (!cb.length) return false;
                cb[0].click(); return true; }""")
        pg.wait_for_timeout(25000)
        after = layers()
        # 頁面上會指名 `Slice Viewer`、`3D Viewer` 這些分頁，所以把可見的分頁名存起來
        tabs = pg.evaluate(
            """() => { const seen = new Set();
                for (const e of document.querySelectorAll('*')) {
                    if (!e.getClientRects().length || e.children.length) continue;
                    const t = (e.innerText || '').trim();
                    if (/^(Slice Viewer|3D Viewer|3D Canvas|Layers|Term Info|Term Context"""
            """|Template ROI Browser|Circuit Browser|Neuroglass Viewer)$/.test(t)) seen.add(t); }
                return [...seen].sort(); }""")
        shot(pg, "viewer_state")
        return {
            "site": V2, "region": EX_REGION, "query_label": QUERY_LABEL,
            "layers_on_load": before,
            "layers_after_running_query": mid,
            "ticked_a_row": ticked,
            "viewer_tabs_on_screen": tabs,
            "layers_after_ticking_one_row": after,
            "note": ("Layers 面板列的就是「檢視器裡現在有什麼」。"
                     "跑完查詢它不會變——**結果表的縮圖不等於載入**；"
                     "勾選之後才多一列。"),
        }
    finally:
        b.close()


@probe("painted_domains", "PART 1 作業單第 2–3 步",
       "作業單叫學員點的那兩支 Painted domains 查詢：標籤、徽章、以及真的點下去回幾列")
def _painted_domains(pw):
    """PART 1 作業單第 2、3 步一直只驗到「徽章上寫幾」，**沒有人真的點過**
    （_notes 第 31 條掛到第 43 條的那條待辦）。這一支就是去點。

    兩步一起做，因為它們是同一個形狀：開 template 的頁面 → 在 `Query For` 區
    找到 `Painted domains for <短名>` → 點它 → 看結果表標題寫幾列。

    **注意查詢標籤用的是 `Symbol`（短名）**，不是 `Name`：
    JRC2018Unisex 那一套的查詢叫 `Painted domains for JRC2018U`。
    """
    out = {}
    for tid, symbol in (("VFB_00101567", "JRC2018U"), ("VFB_00017894", "JFRC2")):
        label = f"Painted domains for {symbol}"
        b, pg = new_page(pw, 1700, 1050)
        try:
            pg.goto(f"{V2}?id={tid}", wait_until="domcontentloaded", timeout=90000)
            pg.wait_for_timeout(32000)
            # 徽章與標籤黏在同一段文字裡（例如 "58Painted domains for JFRC2"）
            # 徽章數字跟標籤在同一段文字裡，但**不在同一個葉節點**
            # （Term Info 的 innerText 會黏成 "58Painted domains for JFRC2"）。
            # 所以要找「最小的、整段文字剛好是 數字＋標籤」的那個元素。
            badge_line = pg.evaluate(
                """(label) => { const NL = String.fromCharCode(10);
                   const c = [...document.querySelectorAll('*')].filter(x => {
                       if (!x.getClientRects().length) return false;
                       const t = (x.innerText || '').trim();
                       return t.indexOf(NL) < 0 && t.endsWith(label) && t !== label; });
                   if (!c.length) return null;
                   c.sort((a, b) => a.innerText.trim().length - b.innerText.trim().length);
                   return c[0].innerText.trim(); }""", label)
            clicked = pg.evaluate(
                """(label) => { const el = [...document.querySelectorAll('*')].filter(
                       e => e.children.length === 0 && (e.innerText || '').trim().includes(label));
                   if (!el.length) return false;
                   const e = el[el.length - 1];
                   e.scrollIntoView({block: 'center'}); e.click(); return true; }""", label)
            if not clicked:
                raise RuntimeError(f"{tid}：Query For 區找不到「{label}」")
            pg.wait_for_timeout(22000)
            shot(pg, f"painted_domains_{symbol}")
            # 點下去之後，結果表的標題**不是查詢的標籤**，是另一句話
            # （`Painted domains for JFRC2` → `58 List all painted anatomy available…`）。
            # 所以不能拿標籤去比對，只能找「數字 ＋ 空格 ＋ 一句話」的那一行。
            title = pg.evaluate(
                """() => { const NL = String.fromCharCode(10);
                   const c = [...document.querySelectorAll('*')].filter(x => {
                       if (!x.getClientRects().length) return false;
                       const t = (x.innerText || '').trim().split(NL)[0];
                       return /^[0-9]+ [A-Z]/.test(t) && t.length < 90
                              && t.toLowerCase().indexOf('painted') >= 0; });
                   if (!c.length) return null;
                   c.sort((a, b) => a.innerText.length - b.innerText.length);
                   return c[0].innerText.trim().split(NL)[0]; }""")
            out[tid] = {
                "symbol": symbol,
                "query_label": label,
                "badge_line_in_query_for": badge_line,
                "results_title_after_clicking": title,
                "title_matches_query_label": bool(title) and label in (title or ""),
                "result_columns": pg.evaluate(
                    """() => [...document.querySelectorAll('[class*=griddle-header],th')]
                         .filter(e => e.getClientRects().length)
                         .map(e => (e.innerText || '').trim())
                         .filter(t => t && t.length < 30)"""),
                "url": f"{V2}?id={tid}",
            }
        finally:
            b.close()
    return {"site": V2, "by_template": out,
            "note": ("這一支是「作業單每一步都要有人照著做一次」那條規矩的執行者："
                     "它不只讀徽章，而是真的把查詢點下去，再讀結果表的標題。")}


@probe("csv_export", "PART 3 第 6 節與作業單第 4 步",
       "按 Download results (CSV) 拿到的是畫面上那幾列，還是整份結果？")
def _csv_export(pw):
    """作業單第 3 步叫學員把結果篩成一列，第 4 步叫他按下載——
    **那他拿到的是 1 列還是 471 列？** 這件事推不出來，只能真的按下去看。

    答案是 471：**篩選不影響下載**，連檔名都還是 `471_…csv`。
    順帶照出第三組欄名——CSV 的表頭跟畫面上的欄名又不一樣。
    """
    out = {}
    for tag, filt in (("no_filter", None), ("filtered", "Cm7")):
        b = pw.chromium.launch(executable_path=CHROME, headless=True, args=ARGS)
        pg = b.new_page(viewport={"width": 1700, "height": 1050}, accept_downloads=True)
        try:
            pg.goto(f"{V2}?id={EX_REGION}", wait_until="domcontentloaded", timeout=90000)
            pg.wait_for_timeout(32000)
            pg.evaluate(
                """(label) => { const el = [...document.querySelectorAll('*')].filter(
                       e => e.children.length === 0 && (e.innerText || '').trim().includes(label));
                   const e = el[el.length - 1];
                   e.scrollIntoView({block: 'center'}); e.click(); }""", QUERY_LABEL)
            pg.wait_for_timeout(22000)
            if filt:
                fb = pg.locator("input[placeholder='Filter Results']").first
                fb.wait_for(state="visible", timeout=15000)
                fb.click()
                fb.type(filt, delay=180)
                pg.wait_for_timeout(7000)
            with pg.expect_download(timeout=60000) as dl:
                pg.evaluate(
                    """() => { const el = [...document.querySelectorAll('*')].filter(
                           e => e.children.length === 0 && /Download/.test(e.innerText || ''));
                       const e = el[el.length - 1];
                       e.scrollIntoView({block: 'center'}); e.click(); }""")
            d = dl.value
            tmp = SHOTS.parent / f"_tmp_{tag}.csv"
            SHOTS.mkdir(parents=True, exist_ok=True)
            d.save_as(str(tmp))
            lines = [ln for ln in tmp.read_text("utf-8", errors="replace").splitlines()
                     if ln.strip()]
            tmp.unlink()
            out[tag] = {
                "filter_typed": filt,
                "suggested_filename": d.suggested_filename,
                "header": lines[0] if lines else None,
                "n_data_rows": max(0, len(lines) - 1),
                "first_row": lines[1] if len(lines) > 1 else None,
            }
        finally:
            b.close()
    same = out["no_filter"]["n_data_rows"] == out["filtered"]["n_data_rows"]
    return {"site": V2, "query_label": QUERY_LABEL, "by_case": out,
            "filter_changes_download": not same,
            "note": ("篩選**不影響**下載：兩次拿到的列數一樣，檔名也一樣。"
                     "CSV 的表頭是第三組欄名——跟畫面上的欄名、跟 API 回的鍵名都不同。")}


@probe("template_symbols", "PART 2 第 4 節",
       "Symbol 跟 Name 不一樣的那五套 template，畫面上的兩欄各寫什麼")
def _template_symbols(pw):
    """PART 2 第 4 節那張表列了十套 template 的 `Name` 與 `Symbol`，
    但那張表是用 API 產的（REST 頂層的 `Name` ＝ 畫面上的 `Symbol`）。
    **那個對應關係只在兩套上親眼驗過**，其餘是外推——
    `field_audit.py` 的 ⚠ 那一桶就是這樣叫出來的。這一支把五套都拍一遍。
    """
    ids = ["VFB_00101567", "VFB_00200000", "VFB_00101384",
           "VFB_00017894", "VFB_00100000"]
    out = {}
    for tid in ids:
        b, pg = new_page(pw)
        try:
            pg.goto(f"{V2}?id={tid}", wait_until="domcontentloaded", timeout=90000)
            pg.wait_for_timeout(30000)
            lines = panel_lines(pg, "#vfbterminfowidget")
            f = fields_from_lines(lines, ["Symbol", "Name", "Classification"])
            out[tid] = {"symbol_on_screen": (f.get("Symbol") or [None])[0],
                        "name_on_screen": (f.get("Name") or [None])[0]}
        finally:
            b.close()
    return {"site": V2, "by_template": out,
            "note": ("`Name` 那一欄的值後面跟著方括號裡的編號，"
                     "例如 `JRC2018Unisex [VFB_00101567]`——那就是畫面上的原樣。")}


@probe("terminfo_v2_connectome_neuron", "PART 4",
       "一顆連線體神經元的 Term Info：同一顆會同時列出資料集的哪幾個版本")
def _terminfo_v2_connectome_neuron(pw):
    """PART 4 的作業單要學員親眼看到「版本並排」這件事，而它就在這一頁上：
    同一顆神經元的 `Source` 欄同時列著 v0.9 與 v1.0 兩筆，`License` 也是兩筆。

    **這是「同一隻果蠅在站上出現兩次」最短的證據**——不必比對數字，看一欄就知道。
    """
    b, pg = new_page(pw)
    try:
        pg.goto(f"{V2}?id={EX_CONNECTOME_NEURON}", wait_until="domcontentloaded",
                timeout=90000)
        pg.wait_for_timeout(32000)
        lines = panel_lines(pg, "#vfbterminfowidget")
        shot(pg, "terminfo_v2_connectome_neuron")
        names = ["Symbol", "Name", "Classification", "Relationships", "Query For",
                 "Graphs For", "Description", "Comment", "Cross References",
                 "Source", "License", "Licenses", "Aligned To", "Downloads"]
        f = fields_from_lines(lines, names)
        return {
            "site": V2, "id": EX_CONNECTOME_NEURON,
            "url": f"{V2}?id={EX_CONNECTOME_NEURON}",
            "field_order_on_screen": [ln for ln in lines if ln in names],
            "fields": f,
            "n_sources_listed": len(f.get("Source") or []),
            "n_licenses_listed": len(f.get("License") or []),
            "all_lines": lines,
        }
    finally:
        b.close()


@probe("nblast_results", "PART 5",
       "在畫面上跑一次 NBLAST：結果表有哪些欄、分數怎麼呈現")
def _nblast_results(pw):
    """PART 5 的作業單要學員親手跑一次 NBLAST，所以這一步要先拍過。

    重點在**結果表比 PART 3 那支多一欄 `Score`**——而那一欄就是這一節的主題。
    """
    b, pg = new_page(pw, 1700, 1050)
    try:
        pg.goto(f"{V2}?id={EX_NEURON_LM}", wait_until="domcontentloaded", timeout=90000)
        pg.wait_for_timeout(32000)
        clicked = pg.evaluate(
            """(label) => { const el = [...document.querySelectorAll('*')].filter(
                   e => e.children.length === 0 && (e.innerText || '').includes(label));
               if (!el.length) return false;
               const e = el[el.length - 1];
               e.scrollIntoView({block: 'center'}); e.click(); return true; }""",
            NBLAST_LABEL)
        if not clicked:
            raise RuntimeError(f"Query For 區找不到「{NBLAST_LABEL}」")
        pg.wait_for_timeout(25000)
        shot(pg, "nblast_results")
        title = pg.evaluate(
            """() => { const NL = String.fromCharCode(10);
               const c = [...document.querySelectorAll('*')].filter(x => {
                   if (!x.getClientRects().length) return false;
                   const t = (x.innerText || '').trim().split(NL)[0];
                   return /^[0-9]+ /.test(t) && t.length < 90
                          && t.toLowerCase().indexOf('similar') >= 0; });
               if (!c.length) return null;
               c.sort((a, b) => a.innerText.length - b.innerText.length);
               return c[0].innerText.trim().split(NL)[0]; }""")
        cols = pg.evaluate(
            """() => [...document.querySelectorAll('[class*=griddle-header],th')]
                 .filter(e => e.getClientRects().length)
                 .map(e => (e.innerText || '').trim())
                 .filter(t => t && t.length < 30)""")
        return {
            "site": V2, "id": EX_NEURON_LM, "query_label": NBLAST_LABEL,
            "url": f"{V2}?id={EX_NEURON_LM}",
            "results_title": title,
            "all_header_texts": cols,
            # **不要用白名單篩欄名**：這支查詢的結果表比 PART 3 那支多兩欄
            # （`Type` 與 `Score ▼`），而白名單寫死的話，新出現的欄位會被靜默丟掉
            # ——那正是「欄位是跟著查詢走的」這件事最容易被漏掉的方式。
            # 改成排除掉 Layers 面板固定那四欄，其餘照收。
            "columns_on_screen": [c for c in dict.fromkeys(cols)
                                  if c not in ("Controls", "Thumbnail", "Type", "Name")
                                  or cols.count(c) > 1],
            "actions_at_bottom": pg.evaluate(
                """() => [...document.querySelectorAll('*')]
                     .filter(e => e.getClientRects().length && e.children.length === 0)
                     .map(e => (e.innerText || '').trim())
                     .filter(t => /Refine|New query|Delete results|Download/.test(t))"""),
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
