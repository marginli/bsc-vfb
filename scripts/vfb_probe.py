#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vfb_probe.py — 把教材會用到的 VFB 查詢跑一遍，存進 out/*.json。

這支程式是這個專題的「原文」。types/tool.md 的硬條件是：
**頁面上每一個數字，都要有一支存下來的 API 輸出可以對回去。**
所以每一個 out/*.json 都帶著產生它的完整網址——把那個網址貼進瀏覽器，
看到的東西要跟檔案裡的一樣。

用法：
    python3 vfb_probe.py            # 跑全部（不含 --full 的重探針）
    python3 vfb_probe.py --list     # 只列出有哪些探針
    python3 vfb_probe.py --only templates connectome_datasets
    python3 vfb_probe.py --full     # 連要翻頁幾萬列的那幾支一起跑

設計上的兩個決定：

1. **資料檔裡不放時間戳。** 抓取時間、耗時、雜湊放在 out/_manifest.json。
   這樣 VFB 換版之後重跑，`diff` 出來的就只有真正變動的內容，
   不會每一個檔案都因為時間不同而全部標成「改了」。
2. **每一支探針只做一件事，而且自己講得出自己是誰**：
   檔案裡有 probe 名、對應的 PART、完整網址、以及一句「這支在教材裡用來回答什麼」。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://v3-cached.virtualflybrain.org"
# 網站的搜尋框打的**不是** BASE 那一支，而是 SOLR，而且參數跟說明文件寫的也不一樣
# （參數是從 v2.virtualflybrain.org 的 main.bundle.js 裡抄出來的）。見 worksheet 探針。
SOLR = "https://solr.virtualflybrain.org/solr/ontology/select"
PDB = "https://pdb.virtualflybrain.org/db/neo4j/tx/commit"  # 唯讀，不需認證
ROOT = Path("/home/wanjuli/claude_linux/BSC_plan/specific_topics/VFB")
OUT = ROOT / "out"

TIMEOUT = 300
RETRIES = 3
UA = "bsc-vfb-teaching-probe/1.0 (+https://github.com/marginli/bsc-vfb)"

# 教材裡固定拿來當例子的幾個 id。改這裡就會改掉整份教材的例子，
# 所以一旦頁面開始引用，就不要再動。
EX_REGION = "FBbt_00003748"      # medulla：分區清楚、EM 與 LM 兩種來源都有
EX_REGION_INDIV = "VFB_00102107"  # 同一塊 medulla 畫在 JRC2018Unisex 上的那一個個體
EX_NEURON_LM = "VFB_00005010"    # Cha-F-100205：FlyCircuit 的一顆，有 NBLAST 可跑
EX_DATASET_LM = "Chiang2010"     # FlyCircuit 1.0
EX_UP = "LPLC2"                  # 連線例子的上游
EX_DOWN = "giant fiber neuron"   # 連線例子的下游


# ══════════════════════════════════════════════════════════════════
# 取資料
# ══════════════════════════════════════════════════════════════════
def url_of(path: str, params: dict | None = None) -> str:
    if not params:
        return BASE + path
    return BASE + path + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def fetch(path: str, params: dict | None = None):
    """回傳 (完整網址, 解析後的內容)。非 JSON 的回應原樣當字串回傳。"""
    url = url_of(path, params)
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read().decode("utf-8", errors="replace")
            try:
                return url, json.loads(raw)
            except json.JSONDecodeError:
                return url, raw.strip()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if attempt < RETRIES:
                time.sleep(2 * attempt)
    raise SystemExit(f"抓不到 {url}\n  {last}")


def paged(path: str, params: dict, page: int = 5000, cap: int = 200_000):
    """把 run_query 的結果整批翻完。回傳 (第一頁的網址, count, 所有列, 是否被截斷)。

    **這支 API 有一個不會報錯的翻頁上限**：offset 超過某個值之後，
    它回的是空的 rows 而不是錯誤。所以「翻完了」與「被擋住了」要分得出來——
    拿到的列數少於 count 就是被擋住，回傳的 truncated 會是 True。
    """
    first_url = url_of(path, dict(params, limit=page, offset=0))
    rows, count, offset = [], None, 0
    while True:
        _, d = fetch(path, dict(params, limit=page, offset=offset))
        count = d.get("count")
        got = d.get("rows") or []
        rows.extend(got)
        offset += len(got)
        if not got or offset >= min(count or 0, cap):
            break
    truncated = count is not None and len(rows) < count
    return first_url, count, rows, truncated


def solr_site_search(term: str, rows: int = 500):
    """照**網站主搜尋框實際送出的參數**問 SOLR。

    這些參數不是從說明文件抄的——文件站 /docs/apis/solr/ 寫的 bq、pf、fq
    跟前端實際送的不一樣（文件沒有 pf=label^250、也沒有 facets_annotation:Class^200）。
    這裡抄的是 v2.virtualflybrain.org 的 main.bundle.js 裡那組。
    """
    params = {
        "q": term, "q.op": "OR", "defType": "edismax", "mm": "45%",
        "qf": ("label^110 synonym^100 label_autosuggest "
               "synonym_autosuggest shortform_autosuggest"),
        "indent": "true",
        "fl": "short_form,label,synonym,id,facets_annotation,unique_facets",
        "start": "0", "pf": "label^250 synonym^120", "ps": "0",
        "fq": ["(short_form:VFB* OR short_form:FB* OR facets_annotation:DataSet "
               "OR facets_annotation:pub) AND NOT short_form:VFBc_*",
               "NOT facets_annotation:Deprecated"],
        "rows": str(rows), "wt": "json",
        "bq": ("short_form:VFBexp*^10.0 short_form:VFB*^50.0 "
               "facets_annotation:Class^200.0 short_form:FBbt*^150.0 "
               "short_form:FBbt_00003982^2 facets_annotation:Deprecated^0.001 "
               "facets_annotation:DataSet^500.0 facets_annotation:pub^100.0"),
    }
    url = SOLR + "?" + urllib.parse.urlencode({"json": json.dumps({"params": params})})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return url, json.loads(r.read().decode("utf-8", errors="replace"))


def solr_docsite_palette(term: str):
    """照**文件站首頁那個搜尋框**（命令面板）實際送出的參數問 SOLR。

    參數與兩個常數都是從 www.virtualflybrain.org 的 /js/app.*.js 抄出來的：
        let Z = 8,  q = 40;
    也就是：跟 SOLR 要 40 筆（rows=40），畫面上只顯示 **8 筆**（slice(0, Z)）。
    拿回來之後前端再依「跟你打的字**完全相同**」分四級重排：
        0 = 編號相同、1 = 正式名相同、2 = 某個同義詞相同、3 = 其餘（維持 SOLR 的順序）

    **第三個常數是 `.toLowerCase()`，而它才是關鍵的那一個。**
    前端在送出之前一律把字串轉小寫，所以學員打什麼大小寫都到不了 SOLR。
    這件事讀 bundle 讀不出來（轉小寫的那一行跟送出的那一行隔得很遠），
    是用真的瀏覽器攔請求才看到的——見 scripts/browser_probe.py 與 out/ui/palette.json。

    補上這一行之後，這支重建**跟畫面完全一致**（8 筆、全是分區、沒有 template 本身）。
    在此之前它少了這一行，於是預測「打大寫就排第一」，跟畫面對不起來，
    連累 _notes 第 18、20 兩條各錯一次。
    """
    fq = ["(short_form:VFB* OR short_form:FB* OR facets_annotation:DataSet "
          "OR facets_annotation:pub) AND NOT short_form:VFBc_*",
          "NOT facets_annotation:Deprecated"]
    bq = ("short_form:VFBexp*^10.0 short_form:VFB*^50.0 "
          "facets_annotation:Class^200.0 short_form:FBbt*^150.0 "
          "short_form:FBbt_00003982^2 facets_annotation:Deprecated^0.001 "
          "facets_annotation:DataSet^500.0 facets_annotation:pub^100.0")
    pairs = [("q", term.lower()), ("q.op", "OR"), ("defType", "edismax"), ("mm", "45%"),
             ("qf", "label^110 synonym^100 label_autosuggest "
                    "synonym_autosuggest shortform_autosuggest"),
             ("pf", "label^250 synonym^120"), ("ps", "0"),
             ("fl", "short_form,label,synonym,unique_facets"), ("bq", bq),
             ("rows", "40"), ("start", "0"), ("wt", "json")]
    pairs += [("fq", f) for f in fq]
    url = SOLR + "?" + urllib.parse.urlencode(pairs)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        d = json.loads(r.read().decode("utf-8", errors="replace"))
    docs = (d.get("response") or {}).get("docs") or []

    # 前端拿回來之後才做重排，而重排比對的是**使用者原本打的字**（沒轉小寫）。
    # 送出去的是小寫、比對的是原字，兩者不同——這是這個框最反直覺的地方。
    def norm(x):
        return " ".join(str(x or "").lower().split())

    typed = norm(term)

    def tier(doc):
        if norm(doc.get("short_form")) == typed:
            return 0
        if norm(doc.get("label")) == typed:
            return 1
        if any(norm(sy) == typed for sy in doc.get("synonym") or []):
            return 2
        return 3

    ranked = sorted(((tier(x), i, x) for i, x in enumerate(docs)),
                    key=lambda z: (z[0], z[1]))
    return url, docs, [x for _, _, x in ranked[:8]]


def fetch_raw_json(url: str):
    """照現成的完整網址取 JSON。給 search_case 用：它要把同一支查詢多要一個 score 欄位。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def cypher(statement: str):
    """對 VFB 的知識庫（Neo4j）下一句唯讀查詢。

    為什麼要有第二支 API：REST 那支的 run_query 回傳的 count 是**列數**，
    而且翻頁到 offset 50,000 就會停——不報錯，只回空陣列（見 flycircuit_images）。
    要拿「不重複的神經元有幾顆」這種數字，只能用 Cypher 算。
    """
    body = json.dumps({"statements": [{"statement": statement}]}).encode()
    req = urllib.request.Request(PDB, data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": UA})
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                d = json.loads(r.read().decode("utf-8"))
            if d.get("errors"):
                raise SystemExit(f"Cypher 出錯：{d['errors'][0].get('message')}\n  {statement}")
            res = d["results"][0]
            return res["columns"], [row["row"] for row in res["data"]]
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if attempt < RETRIES:
                time.sleep(2 * attempt)
    raise SystemExit(f"連不上 {PDB}\n  {last}")


def cypher_src(statement: str) -> dict:
    """存進 JSON 的「出處」：端點加上那一句查詢，讀者可以原樣重跑。"""
    return {"endpoint": PDB, "cypher": " ".join(statement.split())}


def strip_markup(s: str) -> str:
    """VFB 的欄位常寫成 `[標籤](id)`，只留標籤。"""
    if not isinstance(s, str):
        return s
    if s.startswith("[") and "](" in s:
        return s[1:s.index("](")]
    return s


def licences_of(term: dict) -> list[dict]:
    return [{"label": v.get("label"), "source": v.get("source"), "iri": v.get("iri")}
            for v in (term.get("Licenses") or {}).values()]


# ══════════════════════════════════════════════════════════════════
# 探針
# ══════════════════════════════════════════════════════════════════
PROBES: dict[str, dict] = {}


def probe(name, part, question, full=False, needs=()):
    def deco(fn):
        PROBES[name] = {"part": part, "question": question, "fn": fn,
                        "full": full, "needs": tuple(needs)}
        return fn
    return deco


# ── PART 1：template ────────────────────────────────────────────
@probe("templates", "PART 1", "VFB 一共有幾套 template？分別是哪些？")
def _templates():
    # 搜尋會把同一套 template 的正式名與同義詞各回一列，所以要自己收斂成
    # 不重複的 short_form；「有幾套」這個數字就是從這裡來的。
    url, d = fetch("/search", {"query": "*", "filter_types": "Template", "limit": 100})
    seen: dict[str, str] = {}
    for r in d.get("rows", []):
        seen.setdefault(r["short_form"], r.get("original_label") or r.get("label"))
    return {
        "url": url,
        "data": {
            "search_rows": len(d.get("rows", [])),
            "distinct_templates": len(seen),
            "templates": [{"id": k, "label": v} for k, v in sorted(seen.items())],
        },
        "note": "搜尋回傳的列數比 template 的套數多，因為同義詞各佔一列。",
    }


@probe("template_detail", "PART 1", "每一套 template 的 ID、描述、畫了幾個分區、授權是什麼？",
       needs=("templates",))
def _template_detail():
    ids = [t["id"] for t in json.loads((OUT / "templates.json").read_text("utf-8"))
           ["data"]["templates"]]

    # 授權**不要**用 REST 那一欄。實測同一個 id 連問五次，VFB_00110000 回過三次
    # CC-BY_4.0、兩次 CC-BY-SA_4.0——那一欄是不穩定的。知識庫裡每一套 template
    # 只連到一個 License 節點，而且連問三次都一樣，所以以知識庫為準。
    lic_stmt = ("MATCH (t:Template) WHERE NOT t.short_form STARTS WITH 'VFBc' "
                "MATCH (t)-[*1..2]-(l:License) "
                "RETURN t.short_form AS id, collect(DISTINCT l.label) AS lics")
    _, lic_rows = cypher(lic_stmt)
    kb_lic = {r[0]: r[1] for r in lic_rows}

    rows, urls = [], {}
    for tid in ids:
        url, d = fetch("/get_term_info", {"id": tid})
        urls[tid] = url
        meta = d.get("Meta") or {}
        domains = d.get("Domains") or {}
        imgs_list = (d.get("Images") or {}).get(tid) or []
        imgs = imgs_list[0] if imgs_list else {}
        # 「畫了幾個分區」有兩種算法，兩個都算、對不上就報出來——不要挑一個順眼的寫進教材。
        #
        # 算法一：Domains 欄裡**扣掉代表 template 自己那一格**的筆數。
        #   注意不能寫成「筆數減一」：十套裡有兩套（JRCFIB2018Fum、Kuan2020）
        #   根本沒有那一格，減一就少算一個。要比對的是 id 而不是位置。
        # 算法二：直接跑 PaintedDomains 查詢拿它的 count。
        painted = None
        if any(q["query"] == "PaintedDomains" for q in d.get("Queries", [])):
            _, pd = fetch("/run_query", {"id": tid, "query_type": "PaintedDomains",
                                         "limit": 1})
            painted = pd.get("count")
        own_excluded = sum(1 for v in domains.values() if v.get("id") != tid)
        rows.append({
            "id": tid,
            "name": d.get("Name"),
            "symbol": strip_markup(meta.get("Symbol", "")),
            "description": meta.get("Description", ""),
            "types": strip_markup(meta.get("Types", "")),
            # Domains 的第 0 格是 template 自己，其餘才是畫上去的分區
            "domain_entries": len(domains),
            "painted_domains": own_excluded,
            "painted_domains_query": painted,
            "two_counts_agree": painted is None or painted == own_excluded,
            "licence": (kb_lic.get(tid) or [None])[0],
            "licence_count_in_kb": len(kb_lic.get(tid) or []),
            "licence_reported_by_rest": [x["label"] for x in licences_of(d)],
            "has_nrrd": bool(imgs.get("nrrd")),
            "has_obj": bool(imgs.get("obj")),
        })
    disagree = [r["id"] for r in rows if not r["two_counts_agree"]]
    lic_diff = [r["id"] for r in rows
                if r["licence"] and r["licence"] not in r["licence_reported_by_rest"]]
    return {"url": {**urls, "licences": cypher_src(lic_stmt)}, "data": rows,
            "note": ("painted_domains 是 Domains 欄的筆數減一（扣掉代表 template 自己的那格）；"
                     "painted_domains_query 是直接跑 PaintedDomains 查詢拿到的 count。"
                     "兩個算法互為交叉檢查。"
                     + (f"　**對不上的：{disagree}**" if disagree
                        else "　這一輪十套全部一致。")
                     + "　授權以知識庫（licence 欄）為準，REST 那一欄不穩定；"
                     + (f"這一輪 {lic_diff} 兩邊不同。" if lic_diff
                        else "這一輪兩邊一致。"))}


@probe("worksheet", "PART 1", "作業單那四步，學員照著做實際會看到什麼？",
       needs=("templates",))
def _worksheet():
    """把作業單的每一步照學員的做法跑一次。

    **為什麼要有這一支**：作業單第一版寫「在搜尋框輸入 JRC2018Unisex，
    資訊面板裡會出現它的編號 VFB_00101567」。使用者照著做，得到一長串結果、
    找不到那個編號。原因有三個，全都在這支探針的輸出裡看得到：
      1. 正式名（Term Info 的 `Name` 欄）是 **JRC2018Unisex**，
         **JRC2018U** 是它的 `Symbol`；而查詢標籤與搜尋框認的是後者；
      2. 搜尋回的一百多列裡，九成以上是**畫在這顆腦上的分區**，
         名字都長成「某某 on JRC2018Unisex adult brain」；
      3. 編號不在結果清單裡，要點進去才看得到——
         所以「找不到編號」的學員根本不知道該點哪一列。
    作業單的每一個數字都要對得回這裡，跟正文的數字同一個標準。
    """
    steps, urls = [], {}
    for tid, typed in [("VFB_00101567", "JRC2018Unisex"), ("VFB_00017894", "JFRC2")]:
        u_s, sr = fetch("/search", {"query": typed, "limit": 300})
        rows = sr.get("rows") or []
        urls[f"search:{typed}"] = u_s

        # 學員在畫面上看到的是 label；目標詞可能因為同義詞佔了不只一列。
        hits = [(i, r.get("label")) for i, r in enumerate(rows)
                if r.get("short_form") == tid]
        # 學員在畫面上唯一能用的線索是名字，所以照名字分類，不要照型別分類：
        # 「某某 on <template 的名字>」的那些，是畫在這套 template 上的東西。
        # （用型別分會少算——例如顎神經節的型別是 Ganglion 不是 Synaptic_neuropil，
        #   但它的名字一樣長成「… on JRC2018Unisex adult brain」，學員看到的是名字。）
        def facets(r):
            return r.get("facets_annotation") or []
        named_on = [r for r in rows if " on " in (r.get("label") or "")]
        rest = [r for r in rows if " on " not in (r.get("label") or "")]
        # 剩下的幾列要能逐列交代完，否則就是還有沒想到的東西混在裡面
        other_templates = sorted({r["short_form"] for r in rest
                                  if r["short_form"] != tid})
        domains = [r for r in rows
                   if any(f.startswith("Synaptic_neuropil") for f in facets(r))]

        u_t, ti = fetch("/get_term_info", {"id": tid})
        urls[f"term_info:{tid}"] = u_t
        pq = next((q for q in ti.get("Queries") or []
                   if q.get("query") == "PaintedDomains"), None)
        painted = None
        if pq:
            u_p, pd = fetch("/run_query", {"id": tid, "query_type": "PaintedDomains",
                                           "limit": 1})
            urls[f"painted:{tid}"] = u_p
            painted = pd.get("count")

        # 同一個字串，網站的搜尋框問的是 SOLR，跟上面那支 REST 是兩回事。
        # 兩邊的筆數本來就不一樣，而且都不等於學員螢幕上看到的筆數。
        u_solr, sd = solr_site_search(typed)
        urls[f"solr_site:{typed}"] = u_solr
        docs = (sd.get("response") or {}).get("docs") or []
        solr_found = (sd.get("response") or {}).get("numFound")
        # 前端會把每一筆 explode 成「label 一列、short_form 一列、每個同義詞各一列」
        exploded = []
        for d in docs:
            sf, lab = d.get("short_form"), d.get("label")
            exploded.append((sf, lab))
            exploded.append((sf, f"{sf} ({lab})"))
            for sy in d.get("synonym") or []:
                exploded.append((sf, f"{sy} ({lab})"))

        steps.append({
            "typed_into_search_box": typed,
            "id": tid,
            "display_name": ti.get("Name"),
            "typed_string_is_the_display_name": ti.get("Name") == typed,
            "search_rows": sr.get("count"),
            "search_distinct_terms": sr.get("distinct_terms"),
            "target_rows": [{"rank": i, "label": lab} for i, lab in hits],
            "rows_named_on_this_template": len(named_on),
            "rows_not_named_on_it": len(rest),
            "rows_not_named_on_it_detail": [
                {"id": r["short_form"], "label": r.get("label")} for r in rest],
            "other_templates_in_results": other_templates,
            "neuropil_typed_rows": len(domains),
            "all_rows_accounted_for": len(named_on) + len(rest) == len(rows),
            "painted_domains_query_label": pq.get("label") if pq else None,
            "painted_domains_count": painted,
            "report_url": f"https://virtualflybrain.org/reports/{tid}",
            # ── 網站那一路（SOLR）──────────────────────────────
            "solr_num_found": solr_found,
            "solr_exploded_rows": len(exploded),
            "solr_target_first_ranks": [i for i, (sf, _) in enumerate(exploded)
                                        if sf == tid][:4],
            "solr_top8_as_displayed": [t for _, t in exploded[:8]],
        })

    # 文件站首頁那個搜尋框：它跟 SOLR 要 40 筆、只顯示 8 筆，
    # 而且送出前一律轉小寫——所以目標一旦掉出前 40 名就等於不存在，
    # 學員也沒有任何打法可以救它（改大小寫沒用，那一步在前端就被抹掉了）。
    spellings, sp_urls = [], {}
    # 最後一個是**唯一找得到目標的打法**——它是 Term Info 的 `Symbol` 欄那個短名。
    for typed in ["JRC2018Unisex", "JRC2018unisex", "JRC2018Uni", "JRC2018", "JRC2018U"]:
        u_p, docs, top8 = solr_docsite_palette(typed)
        sp_urls[typed] = u_p
        rank = next((i for i, x in enumerate(docs)
                     if x.get("short_form") == "VFB_00101567"), None)
        spellings.append({
            "typed": typed,
            "sent_to_solr": typed.lower(),
            "is_exact_label": typed == "JRC2018Unisex",
            "target_rank_within_40": rank,
            "target_visible_in_top8": any(x.get("short_form") == "VFB_00101567"
                                          for x in top8),
            "top8_labels": [x.get("label") for x in top8],
        })
    urls["docsite_palette"] = sp_urls

    # 第 4 步：一顆神經元同時掛在兩套 template 上（＝橋接的產物）
    u_n, n = fetch("/get_term_info", {"id": EX_NEURON_LM})
    urls[f"term_info:{EX_NEURON_LM}"] = u_n
    aligned = sorted((n.get("Images") or {}).keys())

    # 作業單每一步都指名「去 Term Info 的哪一欄看」。那些欄位名一旦改掉，
    # 學員就會照著找不到——所以把每一欄的現值存下來，重跑時 diff 得出來。
    def meta_name(d):
        return (d.get("Meta") or {}).get("Name")

    ti_t = fetch("/get_term_info", {"id": "VFB_00101567"})[1]
    ti_j = fetch("/get_term_info", {"id": "VFB_00017894"})[1]
    lic0 = (n.get("Licenses") or {}).get("0") or {}
    fields = {
        "第1步：Term Info 的 Name 欄（用來確認到對地方了）": {
            "VFB_00101567": meta_name(ti_t)},
        "第1步：另一個較短的名字（頂層 Name，查詢標籤用它）": {
            "VFB_00101567": ti_t.get("Name")},
        "第2、3步：Term Info 的 Queries 區裡那支查詢的標籤": {
            "VFB_00101567": next((q["label"] for q in ti_t.get("Queries") or []
                                  if q.get("query") == "PaintedDomains"), None),
            "VFB_00017894": next((q["label"] for q in ti_j.get("Queries") or []
                                  if q.get("query") == "PaintedDomains"), None)},
        "第4步：Term Info 的 Aligned To 欄（＝Images 的鍵；畫面上列的是短名）": {
            EX_NEURON_LM: sorted((n.get("Images") or {}).keys())},
        "授權方框：Term Info 的 Licenses 欄": {
            "VFB_00101567": [x["label"] for x in licences_of(ti_t)]},
        "結尾：Licenses 欄同時標出來源資料集（名字裡帶版本）": {
            EX_NEURON_LM: lic0.get("source")},
    }

    return {
        "url": urls,
        "data": {
            "steps": steps,
            "term_info_fields_pointed_at": fields,
            "docsite_search_box": {
                "where": "www.virtualflybrain.org 首頁的搜尋框（命令面板）",
                # 下面三項抄自該站的 js（Z=8, q=40 與重排函式）
                "asks_solr_for": 40,
                "shows_on_screen": 8,
                "lowercases_before_sending": True,
                "reranks_by": "跟你打的字是否完全相同（編號→正式名→同義詞→其餘）",
                # ── 用真的瀏覽器確認過的（out/ui/palette.json）──
                "confirmed_in_browser": {
                    "shows_8_rows": True,
                    "template_itself_absent_from_those_8": True,
                    "typed_JRC2018Unisex_sent_jrc2018unisex": True,
                    "JRC2018U_returns_exactly_one": True,
                    "when": "2026-09-14",
                    "probe": "scripts/browser_probe.py → out/ui/palette.json",
                },
                # 補上轉小寫之後，這個重建跟畫面一致了。
                "reconstruction_matches_screen": True,
                "reconstruction_note": (
                    "這支算的是「SOLR 對這組參數會怎麼排」。它跟畫面一致，"
                    "但**要描述畫面請引 out/ui/palette.json**——那支是真的瀏覽器拍的。"),
                "spellings_reconstructed": spellings,
            },
            "example_neuron": {
                "id": EX_NEURON_LM,
                "name": n.get("Name"),
                "aligned_to_templates": aligned,
                "n_templates": len(aligned),
            },
        },
        "note": ("作業單第 1、4 步：學員打進去的字串不一定是該詞的正式名字，"
                 "而且搜尋結果絕大多數是「畫在這套 template 上的東西」而不是 template 本身——"
                 "所以作業單要給 report_url 當保險，不能只寫「點進結果」。"
                 "rows_named_on_this_template 是照**名字**分的（學員在畫面上只有名字可用），"
                 "neuropil_typed_rows 是照型別分的，兩個數字本來就不同："
                 "顎神經節那種的型別不是 Synaptic_neuropil，名字卻一樣帶「on …」。"
                 "rows_not_named_on_it_detail 要能逐列交代完——"
                 "搜尋 JRC2018Unisex 會連 JRC2018UnisexVNC（另一套 template）一起撈回來。"
                 "第 5 步：example_neuron 對位到 n_templates 套 template。"
                 "　**三條路三個數字**：REST /search 的 search_rows、"
                 "網站搜尋框打的 SOLR 的 solr_num_found、以及前端 explode 後的 "
                 "solr_exploded_rows，同一個字串三個都不一樣。"
                 "所以頁面上**不要寫學員會看到幾筆**——我們量得到的沒有一個是螢幕上那個數字。"
                 "　term_info_fields_pointed_at 記的是作業單叫學員去看的每一欄的現值："
                 "欄位改名或內容變了，學員就會照著找不到，重跑時要當成必修項。"),
    }


# ── PART 2：名字與本體論 ────────────────────────────────────────
@probe("facets", "PART 2", "搜尋可以用哪些類別來篩選？各有多少筆？")
def _facets():
    url, d = fetch("/facets")
    return {"url": url, "data": d,
            "note": "facets 的 docs 數是全站統計，會隨資料更新而變動——不要寫死在正文裡。"}


@probe("search_medulla", "PART 2", "在搜尋框打 medulla 會拿到什麼？")
def _search_medulla():
    url, d = fetch("/search", {"query": "medulla", "limit": 10})
    return {"url": url, "data": d,
            "note": "同一個 FBbt 會因為正式名與同義詞各出現一次——這就是「搜尋的是詞不是字串」。"}


@probe("terminfo_region", "PART 2", "一個腦區的 Term Info 面板裡有哪些東西？")
def _terminfo_region():
    url, d = fetch("/get_term_info", {"id": EX_REGION})
    return {"url": url, "data": d,
            "note": f"{EX_REGION} = medulla。整包原樣存下來，頁面上講到的每一欄都對得回這裡。"}


@probe("search_case", "PART 2",
       "同一組搜尋參數，只差大小寫，目標會排到第幾名？")
def _search_case():
    """PART 2 的核心例子：打 template 的正式名字，找不到 template 本身。

    這一支問的是「為什麼」。同一組參數、同一個字串，只差大小寫：
    大寫版目標排第一，全小寫版排最後一名——而**前端在送出前一律轉小寫**，
    所以學員永遠走在小寫那一條路上（那件事由 out/ui/palette.json 證實）。

    排在它前面的那些，是**它自己的分區**：每一塊分區的名字裡都帶著母體的名字。
    """
    out = {}
    for typed in ("JRC2018Unisex", "jrc2018unisex"):
        url, d = solr_site_search(typed, rows=100)
        docs = (d.get("response") or {}).get("docs") or []
        rank = next((i for i, x in enumerate(docs)
                     if x.get("short_form") == "VFB_00101567"), None)
        # 要分數就得請 SOLR 把 score 也給出來
        u2 = url.replace("short_form%2Clabel", "short_form%2Clabel%2Cscore")
        scored = fetch_raw_json(u2)
        sdocs = ((scored.get("response") or {}).get("docs") or []) if scored else []
        named_on = [x for x in docs if " on " in (x.get("label") or "")]
        out[typed] = {
            "url": url,
            "numFound": (d.get("response") or {}).get("numFound"),
            "target_rank_1based": None if rank is None else rank + 1,
            "n_rows_named_on_something": len(named_on),
            "top_score": (sdocs[0].get("score") if sdocs else None),
            "target_score": (sdocs[rank].get("score")
                             if sdocs and rank is not None and rank < len(sdocs) else None),
        }
    return {"url": {k: v["url"] for k, v in out.items()}, "data": out,
            "note": ("大小寫只在 SOLR 端有效；學員碰不到它——"
                     "文件站那個框送出前一律轉小寫，見 out/ui/palette.json。")}


@probe("template_names", "PART 2",
       "十套 template 在畫面上的 Name 與 Symbol 各是什麼？兩者何時不一樣？")
def _template_names():
    """PART 2 的主軸之一是「一個東西有三個名字」。這一支把十套 template 的
    三個名字並排存下來，因為**它們的關係不是一對一的**：

      畫面上的 `Name`   ＝ REST 的 `Meta.Name`（去掉 markdown 連結語法）
      畫面上的 `Symbol` ＝ REST **頂層**的 `Name`  ← 名字一樣、意思相反，很容易抄錯
      畫面上的 `ID`     ＝ `short_form`

    十套裡有五套的 Symbol 跟 Name 不同，其中 `JRC_FlyEM_Hemibrain` 與它的 Symbol
    `JRCFIB2018Fum` **一個字都不重疊**——拿其中一個去站上找另一個會找不到。
    """
    ids = [t["id"] for t in json.loads(
        (OUT / "template_detail.json").read_text("utf-8"))["data"]]
    rows, urls = [], {}
    for i in ids:
        url, d = fetch("/get_term_info", {"id": i})
        urls[i] = url
        name = strip_markup((d.get("Meta") or {}).get("Name") or "")
        sym = d.get("Name")
        rows.append({"id": i, "name_on_screen": name, "symbol_on_screen": sym,
                     "differs": name != sym,
                     "symbol_appears_inside_name": bool(sym) and sym in name})
    return {"url": urls, "data": {
                "rows": rows,
                "n_differs": sum(r["differs"] for r in rows),
                "n_symbol_not_in_name": sum(
                    r["differs"] and not r["symbol_appears_inside_name"] for r in rows)},
            "note": ("畫面上的欄位名對回 out/ui/terminfo_v2_template.json 與 "
                     "terminfo_v3_template.json（那兩支是用真的瀏覽器拍的）。")}


@probe("terminfo_individual", "PART 2",
       "同一塊腦區，「類別」與「畫在某顆腦上的那一個」的面板差在哪？")
def _terminfo_individual():
    """EX_REGION 是類別（medulla 這個概念），這一支問的是它的其中一個個體。

    **為什麼要成對存**：PART 2 的主軸是「FBbt_ 是類別、VFB_ 是個體」，
    而這件事最好的證據就是把兩邊的 Term Info 並排——
    類別有 Examples、沒有授權也沒有下載；個體反過來。
    授權掛在個體上這件事尤其重要（types/tool.md〈著作權：逐筆，不是整站〉）。
    """
    url, d = fetch("/get_term_info", {"id": EX_REGION_INDIV})
    cls = fetch("/get_term_info", {"id": EX_REGION})[1]

    def shape(x):
        return {"Name": x.get("Name"),
                "Id": x.get("Id"),
                "IsClass": x.get("IsClass"),
                "IsIndividual": x.get("IsIndividual"),
                "IsPaintedDomain": x.get("IsPaintedDomain"),
                "SuperTypes": x.get("SuperTypes"),
                "n_Examples": len(x.get("Examples") or {}),
                "n_Synonyms": len(x.get("Synonyms") or []),
                "n_Queries": len(x.get("Queries") or []),
                "has_Licenses": bool(x.get("Licenses")),
                "licences": [l.get("label") for l in licences_of(x)],
                "aligned_to": sorted((x.get("Images") or {}).keys()),
                "source": ((x.get("Licenses") or {}).get("0") or {}).get("source")}

    # 第二條路：知識庫算「這個類別底下到底有幾個個體」。
    # REST 的 Examples 欄**不穩定**——同一個 id 連問五次，回三套與四套交替出現，
    # 所以個數一律用 Cypher 算（types/tool.md〈稽核〉那條交叉檢查）。
    cy = ("MATCH (i:Individual)-[:INSTANCEOF]->(:Class {short_form:'%s'}) "
          "RETURN count(i) AS total, "
          "count(CASE WHEN i.short_form STARTS WITH 'VFB_internal' THEN 1 END) AS anonymous, "
          "count(CASE WHEN NOT i.short_form STARTS WITH 'VFB_internal' THEN 1 END) AS named"
          % EX_REGION)
    cy_url, counts = cypher(cy)
    cy2 = ("MATCH (i:Individual)-[:INSTANCEOF]->(:Class {short_form:'%s'}) "
           "WHERE NOT i.short_form STARTS WITH 'VFB_internal' "
           "RETURN i.short_form AS id, i.label AS label ORDER BY id" % EX_REGION)
    _, named = cypher(cy2)

    return {"url": {"rest": url, "kb": cy_url}, "data": {"individual": d, "compare": {
                "class": shape(cls), "individual": shape(d)},
                "instances_in_kb": {
                    "total": counts[0][0], "anonymous": counts[0][1], "named": counts[0][2],
                    "named_list": [{"id": r[0], "label": r[1]} for r in named],
                    "note": ("anonymous 那些是 VFB_internal…，沒有名字也沒有影像，"
                             "用來承載「某一個表現模式與某一隻果蠅的這塊腦區重疊」這類陳述。"
                             "要算「有影像的有幾個」請用 ListAllAvailableImages（見 counts_region）。")},},
            "note": (f"{EX_REGION_INDIV} 是 {EX_REGION}（medulla）畫在 JRC2018Unisex 上的那一塊。"
                     "compare 兩欄並排，用來支持頁面上「類別與個體是兩種東西」那一節。")}


@probe("hierarchy_region", "PART 2", "part_of 與 subclass_of 是兩張不同的圖，差在哪？")
def _hierarchy_region():
    out, urls = {}, {}
    for rel in ("part_of", "subclass_of"):
        url, d = fetch("/get_hierarchy",
                       {"id": EX_REGION, "max_depth": 1, "relationship": rel})
        urls[rel] = url
        # html 欄位是整頁 HTML，存下來只會讓 diff 沒法看
        out[rel] = {k: v for k, v in d.items() if k not in ("html", "display_full")}
    return {"url": urls, "data": out,
            "note": "已去掉回應裡的 html 欄位（整頁 HTML，會把 diff 淹掉）。"}


# ── PART 3：查詢 ────────────────────────────────────────────────
@probe("queries_for_region", "PART 3", "一個腦區的面板會給你哪些現成查詢？",
       needs=("terminfo_region",))
def _queries_for_region():
    d = json.loads((OUT / "terminfo_region.json").read_text("utf-8"))["data"]
    qs = [{"query": q["query"], "label": q["label"], "function": q["function"]}
          for q in d.get("Queries", [])]
    return {"url": url_of("/get_term_info", {"id": EX_REGION}), "data": qs,
            "note": "這張表就是 PART 3 要教的「入口」——它由資料決定，不是寫死的功能表。"}


@probe("counts_region", "PART 3", "那些現成查詢各自會回傳幾筆？",
       needs=("queries_for_region",))
def _counts_region():
    qs = json.loads((OUT / "queries_for_region.json").read_text("utf-8"))["data"]
    rows, urls = [], {}
    for q in qs:
        params = {"id": EX_REGION, "query_type": q["query"], "limit": 3}
        url, d = fetch("/run_query", params)
        urls[q["query"]] = url
        rows.append({
            "query": q["query"],
            "label": q["label"],
            "count": d.get("count"),
            "columns": list((d.get("headers") or {}).keys()),
            "sample": [{k: strip_markup(v) for k, v in r.items()
                        if k in ("id", "label", "name", "template", "technique")}
                       for r in (d.get("rows") or [])],
        })
    return {"url": urls, "data": rows,
            "note": "count 是這支查詢的總列數。注意它是列數不是個數——見 flycircuit_images。"}


@probe("query_overlaps", "PART 3",
       "NeuronsPartHere／NeuronsSynaptic／Neurons(Pre|Post)synapticHere 回的是同一群東西嗎？",
       needs=("counts_region",))
def _query_overlaps():
    """PART 3 的核心警告：**這幾支查詢是巢狀的，但不能相加。**

    站上把它們並排列在同一個 Query For 區，數字一個比一個小。
    實測的包含關係確實成立（前突觸、後突觸 ⊆ 有突觸終端 ⊆ 有一部分在裡面），
    **但這不表示可以把數字加減來回**：前突觸與後突觸重疊 230 種，
    而且兩者合起來也填不滿「有突觸終端」——還差 99 種。

    **一律用集合運算，不要用加減法。** 這一支把每一支的 id 全部取回來算好，
    頁面直接引用結果。
    """
    Q = ["NeuronsPartHere", "NeuronsSynaptic",
         "NeuronsPresynapticHere", "NeuronsPostsynapticHere"]
    sets, urls, counts, trunc_any = {}, {}, {}, False
    for q in Q:
        url, count, rows, trunc = paged("/run_query",
                                        {"id": EX_REGION, "query_type": q}, page=2000)
        urls[q] = url
        counts[q] = count
        trunc_any = trunc_any or trunc
        sets[q] = {strip_markup(r.get("id", "")) for r in rows}
        # 取回的列數要等於它自己報的 count，否則下面的集合運算是在半份資料上做的
        assert len(rows) == count, f"{q}：取回 {len(rows)} 列，但 count 說 {count}"

    part, syn = sets["NeuronsPartHere"], sets["NeuronsSynaptic"]
    pre, post = sets["NeuronsPresynapticHere"], sets["NeuronsPostsynapticHere"]
    return {"url": urls, "data": {
        "counts": counts,
        "truncated": trunc_any,
        "n_unique": {q: len(sets[q]) for q in Q},
        "pre_plus_post_naive_sum": len(pre) + len(post),
        "in_both_pre_and_post": len(pre & post),
        "union_pre_post": len(pre | post),
        "synaptic_minus_union_pre_post": len(syn - pre - post),
        "part_minus_synaptic": len(part - syn),
        "synaptic_is_subset_of_part": syn <= part,
        "pre_is_subset_of_synaptic": pre <= syn,
        "post_is_subset_of_synaptic": post <= syn,
        "example_ids_part_not_synaptic": sorted(part - syn)[:8],
        "example_ids_synaptic_not_pre_or_post": sorted(syn - pre - post)[:8],
    }, "note": (
        "包含關係成立（見 *_is_subset_of_*），但數字不能相加："
        "前突觸與後突觸重疊 230 種，兩者聯集 365 也小於「有突觸終端」的 464。"
        "頁面上凡是講『多少種神經元』的句子，都要說明是哪一支查詢問出來的。")}


# ── PART 4：連線體 ──────────────────────────────────────────────
@probe("connectome_overview", "PART 4",
       "站上那八套連線資料是怎麼被選出來的？版本與棄用長什麼樣？",
       needs=("connectome_datasets",))
def _connectome_overview():
    """PART 4 的骨幹。三件事都用知識庫算，因為 REST 只給得出那八套的名字。

    **八套的判準是實測出來的，不是猜的**：知識庫裡的 Site 節點有三個旗標——
    `dense`（整幅密集重建）、`is_data_source`（現行版本）、`deprecated`（明確退役）。
    `dense ∧ is_data_source` 算出來**剛好就是 REST 回的那八套，不多不少**。
    這一支每次重跑都會再驗一次那個等式（`eight_equals_dense_and_current`）。

    由此分得出三種狀態，而它們在頁面上要分開講：
      · 現行     dense ＋ is_data_source
      · 舊版還在 dense、沒有 is_data_source（連線**還在**：BANC626、male-cns v0.9）
      · 明確退役 deprecated（連線**被拿掉**：只有 hemibrain v1.0.1）
    """
    listed = {d["short_form"] for d in json.loads(
        (OUT / "connectome_datasets.json").read_text("utf-8"))["data"]}

    def sites(cond):
        return {r[0]: r[1] for r in cypher(
            "MATCH (s:Site) WHERE %s RETURN s.short_form, s.label ORDER BY s.short_form"
            % cond)[1]}

    dense_current = sites("s.is_data_source AND s.dense")
    dense_all = sites("s.dense")
    deprecated = sites("s.deprecated")

    # 把旗標的**名字與逐站的值**存下來。頁面上會指名這三個旗標，
    # 不存的話那個宣稱就無從追回（`field_audit.py` 會叫）。
    flags = {}
    for sf in sorted(set(dense_all) | set(deprecated) | {"catmaid_fanc"}):
        r = cypher("MATCH (s:Site {short_form:'%s'}) "
                   "RETURN s.dense, s.is_data_source, s.deprecated" % sf)[1]
        d_, i_, x_ = (r[0] if r else (None, None, None))
        flags[sf] = {"dense": bool(d_), "is_data_source": bool(i_),
                     "deprecated": bool(x_)}

    # 每一套資料集：神經元、有連線的神經元、連線邊
    def ds_stats(short_forms):
        lit = "[" + ",".join(f"'{x}'" for x in short_forms) + "]"
        q = ("MATCH (n:Individual)-[:has_source]->(d:DataSet) WHERE d.short_form IN %s "
             "OPTIONAL MATCH (n)-[c:synapsed_to]->() "
             "RETURN d.short_form AS ds, d.label AS label, count(DISTINCT n) AS neurons, "
             "count(DISTINCT CASE WHEN c IS NOT NULL THEN n END) AS with_conn, "
             "count(c) AS out_edges ORDER BY neurons DESC" % lit)
        return [{"dataset": r[0], "label": r[1], "neurons": r[2],
                 "neurons_with_connectivity": r[3], "outgoing_edges": r[4]}
                for r in cypher(q)[1]]

    versions = ds_stats(["Xu2020Neurons", "Xu2020NeuronsV1point2point1",
                         "Berg2025", "Berg2025a", "Bates2025", "Bates2026",
                         "Takemura2023", "Dorkenwald2023", "Nern2024",
                         "Maniates_Selvin2020"])

    # 知識庫裡到底有幾套資料集帶連線——跟那八套的落差是 PART 4 第 2 節
    n_with_conn = cypher(
        "MATCH (:Individual)-[:synapsed_to]->(:Individual) "
        "WITH 1 AS x LIMIT 1 "
        "MATCH (n:Individual)-[:has_source]->(d:DataSet) WHERE (n)-[:synapsed_to]-() "
        "RETURN count(DISTINCT d)")[1][0][0]

    # PART 3 那份 medulla 清單，底下的個體來自哪幾套
    rows = json.loads((OUT / "query_overlaps.json").read_text("utf-8"))["data"]
    _, _, r2, _ = paged("/run_query",
                        {"id": EX_REGION, "query_type": "NeuronsPartHere"}, page=2000)
    ids = sorted({strip_markup(x.get("id", "")) for x in r2})
    lit = "[" + ",".join(f"'{i}'" for i in ids) + "]"
    by_ds = [{"dataset": r[0], "label": r[1], "individuals": r[2]} for r in cypher(
        "MATCH (c:Class) WHERE c.short_form IN %s "
        "MATCH (i:Individual)-[:INSTANCEOF]->(c)-[:SUBCLASSOF*0..0]->(c) "
        "MATCH (i)-[:has_source]->(d:DataSet) "
        "RETURN d.short_form, d.label, count(DISTINCT i) AS n ORDER BY n DESC LIMIT 12"
        % lit)[1]]

    return {"url": {"rest_list": url_of("/list_connectome_datasets"), "kb": PDB},
            "data": {
                "listed_by_rest": sorted(listed),
                "dense_and_current": dense_current,
                "dense_including_old_versions": dense_all,
                "old_versions_still_dense": sorted(set(dense_all) - set(dense_current)),
                "explicitly_deprecated": deprecated,
                "site_flags": flags,
                "flag_meanings": {
                    "dense": "整幅密集重建（不是挑幾條描繪）",
                    "is_data_source": "現行版本",
                    "deprecated": "明確退役"},
                "eight_equals_dense_and_current": set(dense_current) == listed,
                "n_datasets_with_connectivity_in_kb": n_with_conn,
                "version_pairs": versions,
                "medulla_individuals_by_dataset": by_ds,
                "n_neuron_classes_in_medulla": len(ids)},
            "note": ("八套 = dense ∧ is_data_source（每次重跑都會重驗這個等式）。"
                     "『舊版還在』與『明確退役』是兩種不同的狀態，連線在不在是關鍵差別。")}


@probe("connectome_datasets", "PART 4", "VFB 現在有哪幾套連線資料？版本是多少？")
def _connectome_datasets():
    url, d = fetch("/list_connectome_datasets")
    return {"url": url, "data": d,
            "note": "label 裡帶著版本號（例：FlyWire v783）——頁面上每個連線數字都要標它。"}


@probe("connectivity_example", "PART 4", "同一對細胞型的連線，在不同資料集裡長什麼樣？")
def _connectivity_example():
    url, d = fetch("/query_connectivity",
                   {"upstream_type": EX_UP, "downstream_type": EX_DOWN})
    conns = d.get("connections") or d if isinstance(d, dict) else d
    if isinstance(conns, dict):
        conns = conns.get("connections") or []
    by_src: dict[str, dict] = {}
    for c in conns:
        key = f"{c.get('up_data_source')}→{c.get('down_data_source')}"
        s = by_src.setdefault(key, {"pairs": 0, "total_weight": 0, "max_weight": 0})
        s["pairs"] += 1
        s["total_weight"] += c.get("weight") or 0
        s["max_weight"] = max(s["max_weight"], c.get("weight") or 0)
    return {
        "url": url,
        "data": {"upstream_type": EX_UP, "downstream_type": EX_DOWN,
                 "pair_count": len(conns), "by_data_source": by_src,
                 "sample": conns[:5]},
        "note": "by_data_source 分開統計，就是為了讓「不同資料集不是同一個數字」看得見。",
    }


# ── PART 5：形態比對與 FlyCircuit ──────────────────────────────
@probe("flycircuit_dataset", "PART 5", "FlyCircuit 這套資料在 VFB 上的授權與引用要求是什麼？")
def _flycircuit_dataset():
    url, d = fetch("/get_term_info", {"id": EX_DATASET_LM})
    return {"url": url,
            "data": {"name": d.get("Name"), "id": d.get("Id"),
                     "meta": d.get("Meta"), "licences": licences_of(d),
                     "publications": d.get("Publications"),
                     "queries": [q["query"] for q in d.get("Queries", [])]},
            "note": "授權是逐筆掛在資料上的，不是全站一句話——types/tool.md 的〈著作權〉。"}


@probe("flycircuit_images", "PART 5",
       "FlyCircuit 在 VFB 上有幾顆神經元？API 回報的「幾筆」又是什麼？", full=True)
def _flycircuit_images():
    url, count, rows, truncated = paged(
        "/run_query", {"id": EX_DATASET_LM, "query_type": "DatasetImages"})
    ids = {r["id"] for r in rows}
    tpl: dict[str, int] = {}
    typ: dict[str, int] = {}
    for r in rows:
        tpl[strip_markup(r.get("template", ""))] = tpl.get(strip_markup(r.get("template", "")), 0) + 1
        typ[strip_markup(r.get("type", ""))] = typ.get(strip_markup(r.get("type", "")), 0) + 1

    stmt = ("MATCH (i:Individual)-[:has_source]->(:DataSet {short_form: '%s'}) "
            "RETURN count(DISTINCT i) AS n" % EX_DATASET_LM)
    _, crows = cypher(stmt)
    exact = crows[0][0]

    return {
        "url": {"rest": url, "pdb": cypher_src(stmt)},
        "data": {
            "neurons_exact": exact,
            "rest_reported_count": count,
            "rest_rows_fetched": len(rows),
            "rest_truncated": truncated,
            "distinct_ids_in_fetched_rows": len(ids),
            "rows_per_neuron": round(count / exact, 3) if exact else None,
            "rows_by_template": dict(sorted(tpl.items(), key=lambda kv: -kv[1])),
            "rows_by_type_top15": dict(sorted(typ.items(), key=lambda kv: -kv[1])[:15]),
        },
        "note": ("兩件事要分開：**neurons_exact 才是神經元數**（Cypher 算的）；"
                 "REST 的 count 是列數——同一顆神經元對位到兩套 template、又掛在好幾個類別底下，"
                 "所以一顆佔了四列多。而且 REST 翻頁到五萬列就停，不報錯只回空陣列，"
                 "所以 distinct_ids_in_fetched_rows 只是「前五萬列裡的」，不是總數。"),
    }


@probe("dataset_sizes", "PART 4", "每一套資料集實際有幾顆神經元？哪些是同一套的不同版本？")
def _dataset_sizes():
    stmt = ("MATCH (i:Individual)-[:has_source]->(d:DataSet) "
            "RETURN d.short_form AS id, d.label AS label, count(DISTINCT i) AS n "
            "ORDER BY n DESC LIMIT 25")
    cols, rows = cypher(stmt)
    return {"url": cypher_src(stmt),
            "data": [dict(zip(cols, r)) for r in rows],
            "note": ("同一套資料的新舊版本會各佔一列（BANC 626 與 888、hemibrain 1.0.1 與 1.2.1、"
                     "male CNS 0.9 與 1.0）——**這些數字不能相加**，"
                     "而且重疊組織的資料集（FAFB／FlyWire／hemibrain）也不能相加。")}


@probe("templates_pdb", "PART 1", "知識庫裡登記為 template 的有幾個？跟搜尋看到的一樣嗎？",
       needs=("templates",))
def _templates_pdb():
    stmt = "MATCH (t:Template) RETURN t.short_form AS id, t.label AS label ORDER BY id"
    cols, rows = cypher(stmt)
    listed = json.loads((OUT / "templates.json").read_text("utf-8"))["data"]
    listed_ids = {x["id"] for x in listed["templates"]}
    all_ids = {r[0] for r in rows}
    return {"url": cypher_src(stmt),
            "data": {"pdb_total": len(rows),
                     "search_total": listed["distinct_templates"],
                     "only_in_pdb": sorted(all_ids - listed_ids),
                     "templates": [dict(zip(cols, r)) for r in rows]},
            "note": ("兩個數字不一樣，而且兩個都對——差的是 VFBc_ 開頭那幾個，"
                     "它們是同一套 template 的附屬影像，搜尋不會把它們當成可選的 template。"
                     "頁面上要講「有幾套 template」時，用搜尋看得到的那一組。")}


@probe("nblast_example", "PART 5", "NBLAST 的相似度查詢回傳什麼？分數怎麼看？")
def _nblast_example():
    url, d = fetch("/run_query", {"id": EX_NEURON_LM,
                                  "query_type": "SimilarMorphologyTo", "limit": 10})
    return {"url": url,
            "data": {"count": d.get("count"),
                     "columns": list((d.get("headers") or {}).keys()),
                     "rows": d.get("rows")},
            "note": f"{EX_NEURON_LM} = Cha-F-100205，FlyCircuit 的一顆。分數的門檻是人訂的。"}


# ── PART 6：服務本身 ────────────────────────────────────────────
@probe("service", "PART 6", "這兩支 API 現在活著嗎？")
def _service():
    u1, health = fetch("/health")
    u2, status = fetch("/status")
    _, ping = cypher("RETURN 1 AS ok")
    # /status 裡大半是佇列、快取、連線數這類每秒都在動的遙測，
    # 留著會讓每一次重跑都被標成「內容變了」，把真正的變動蓋掉。
    # 只留「活著沒有」與「接到哪台上游」。
    return {"url": {"health": u1, "status": u2, "pdb": cypher_src("RETURN 1 AS ok")},
            "data": {"health": health,
                     "status_health": (status or {}).get("health"),
                     "upstream": (status or {}).get("upstream"),
                     "pdb_reachable": ping == [[1]]},
            "note": "已刻意丟掉 /status 裡的快取與連線計數——那是遙測，不是教材要引的數字。"}


# ══════════════════════════════════════════════════════════════════
# 主程式
# ══════════════════════════════════════════════════════════════════
def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser(description="跑一遍 VFB 的查詢，存進 out/*.json")
    ap.add_argument("--only", nargs="+", metavar="NAME", help="只跑這幾支")
    ap.add_argument("--full", action="store_true", help="連要翻幾萬列的重探針一起跑")
    ap.add_argument("--list", action="store_true", help="列出所有探針就結束")
    args = ap.parse_args()

    if args.list:
        for name, p in PROBES.items():
            mark = "  [--full]" if p["full"] else ""
            mark += ("  需要：" + "、".join(p["needs"])) if p["needs"] else ""
            print(f"{name:22} {p['part']}  {p['question']}{mark}")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    man_path = OUT / "_manifest.json"
    old = json.loads(man_path.read_text("utf-8")) if man_path.exists() else {}
    old_probes = old.get("probes", {})

    names = args.only or [n for n, p in PROBES.items() if args.full or not p["full"]]
    unknown = [n for n in names if n not in PROBES]
    if unknown:
        raise SystemExit(f"沒有這幾支探針：{unknown}　（--list 看清單）")

    for name in names:
        for dep in PROBES[name]["needs"]:
            if dep not in names and not (OUT / f"{dep}.json").exists():
                raise SystemExit(
                    f"{name} 要先有 out/{dep}.json——把 {dep} 一起跑，或先跑一次完整的。")

    manifest, changed, t0 = {}, [], time.time()
    for name in names:
        p = PROBES[name]
        print(f"  {name} …", end="", flush=True)
        t = time.time()
        r = p["fn"]()
        payload = {
            "probe": name,
            "part": p["part"],
            "question": p["question"],
            "url": r["url"],
            "note": r.get("note", ""),
            "data": r["data"],
        }
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                                   sort_keys=False) + "\n", encoding="utf-8")
        digest = sha(path)
        elapsed = round(time.time() - t, 1)
        prev = old_probes.get(name, {}).get("sha256")
        if prev and prev != digest:
            changed.append(name)
        manifest[name] = {"sha256": digest, "seconds": elapsed,
                          "fetched_at": datetime.now(timezone.utc)
                          .isoformat(timespec="seconds"),
                          "bytes": path.stat().st_size}
        print(f" {elapsed}s{'　← 內容變了' if prev and prev != digest else ''}")

    man_path.write_text(json.dumps(
        {"base": BASE,
         "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "probes": {**old_probes, **manifest}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    write_fetched_at()
    print(f"\n跑完 {len(names)} 支，用時 {round(time.time() - t0)} 秒。")
    if changed:
        print("內容跟上一次不同的：" + "、".join(changed))
        print("→ 這些數字在頁面上出現過的地方都要複查（types/tool.md 的〈時效〉）。")
    return 0


def write_fetched_at() -> None:
    """把「頁面上會用到的那幾個數字」連同版本寫成一份人看的清單。"""
    def load(name):
        p = OUT / f"{name}.json"
        return json.loads(p.read_text("utf-8")) if p.exists() else None

    man = json.loads((OUT / "_manifest.json").read_text("utf-8"))
    lines = ["VFB 探針抓取紀錄",
             "=" * 60,
             f"API   {BASE}",
             f"執行  {man['run_at']}（UTC）",
             ""]

    ds = load("connectome_datasets")
    if ds:
        lines += ["連線資料集與版本（label 裡的版本號就是要標在頁面上的）："]
        for r in ds["data"]:
            lines.append(f"  {r['symbol']:6} {r['short_form']:34} {r['label']}")
        lines.append("")

    t = load("templates")
    if t:
        lines += [f"template：{t['data']['distinct_templates']} 套"
                  f"（搜尋回傳 {t['data']['search_rows']} 列，同義詞各佔一列）"]
        td = load("template_detail")
        if td:
            for r in td["data"]:
                lic = r.get("licence") or "—"
                lines.append(f"  {r['id']:14} {(r['symbol'] or r['name'])[:26]:28} "
                             f"分區 {r['painted_domains']:>3}　授權 {lic}")
        lines.append("")

    tp = load("templates_pdb")
    if tp:
        d = tp["data"]
        lines += [f"（知識庫裡的 Template 節點有 {d['pdb_total']} 個，"
                  f"比搜尋看得到的 {d['search_total']} 套多——"
                  f"多的是 {'、'.join(d['only_in_pdb'])} 這類附屬影像。"
                  "頁面上講「有幾套」時用搜尋那一組。）", ""]

    dsz = load("dataset_sizes")
    if dsz:
        lines += ["資料集實際的神經元數（Cypher 算的不重複顆數，前 12 名）：",
                  "  ※ 同一套資料的新舊版本各佔一列，重疊組織的資料集也各佔一列——都不能相加。"]
        for r in dsz["data"][:12]:
            lines.append(f"  {r['id']:30} {r['n']:>8}　{(r['label'] or '')[:46]}")
        lines.append("")

    fc = load("flycircuit_images")
    if fc:
        d = fc["data"]
        lines += ["FlyCircuit（Chiang2010）——「幾筆」跟「幾顆」不是同一件事：",
                  f"  神經元（Cypher 算的不重複顆數）　{d['neurons_exact']:,}",
                  f"  REST 回報的列數　　　　　　　　　{d['rest_reported_count']:,}"
                  f"（平均每顆 {d['rows_per_neuron']} 列）",
                  f"  REST 實際翻得到的列數　　　　　　{d['rest_rows_fetched']:,}"
                  f"{'（被翻頁上限擋住）' if d['rest_truncated'] else ''}",
                  ""]

    cr = load("counts_region")
    if cr:
        lines += [f"腦區例子 {EX_REGION} 的現成查詢與筆數："]
        for r in cr["data"]:
            lines.append(f"  {r['query']:28} {str(r['count']):>8}　{r['label']}")
        lines.append("")

    lines += ["各探針最後一次成功抓取的時間："]
    for name, m in man["probes"].items():
        lines.append(f"  {name:22} {m['fetched_at']}  {m['sha256']}")
    lines.append("")
    lines += ["頁面上引用這裡的任何數字時，要一併標明「哪一套資料、哪一版、哪一天抓的」。",
              "重跑本程式後若有檔案內容變動，程式會列出來——那就是要回頭複查的清單。"]
    (OUT / "fetched_at.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
