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
PDB = "https://pdb.virtualflybrain.org/db/neo4j/tx/commit"  # 唯讀，不需認證
ROOT = Path("/home/wanjuli/claude_linux/BSC_plan/specific_topics/VFB")
OUT = ROOT / "out"

TIMEOUT = 300
RETRIES = 3
UA = "bsc-vfb-teaching-probe/1.0 (+https://github.com/marginli/bsc-vfb)"

# 教材裡固定拿來當例子的幾個 id。改這裡就會改掉整份教材的例子，
# 所以一旦頁面開始引用，就不要再動。
EX_REGION = "FBbt_00003748"      # medulla：分區清楚、EM 與 LM 兩種來源都有
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


# ── PART 4：連線體 ──────────────────────────────────────────────
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
