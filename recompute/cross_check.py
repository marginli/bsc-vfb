#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cross_check.py — 同一個數字，換三條路各問一次。

    python3 cross_check.py          # 約 90 秒（REST 那條要翻五萬列）

問的是同一件事：Nern2024 這個資料集底下有幾顆神經元。
三條路分別是——

  ① 知識庫 Cypher       pdb.virtualflybrain.org        recompute.py 用的就是這條
  ② REST 的 run_query   v3-cached.virtualflybrain.org  網站自己在用的那條
  ③ MCP 的 get_term_info vfb3-mcp.virtualflybrain.org  給 AI 工具用的那條

**這支程式的重點不是「確認三條一樣」，是把不一樣的地方攤開。**
實測 ② 會比 ①③ 多出幾千，而且在五萬列的地方被截掉；原因寫在 out/cross_check.json
的 note 欄裡。一個數字只問過一條路，就沒辦法知道自己站在哪一邊。

產出：out/cross_check.json
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DS = "Nern2024"
KB = "https://pdb.virtualflybrain.org/db/neo4j/tx/commit"
REST = "https://v3-cached.virtualflybrain.org/run_query"
MCP = "https://vfb3-mcp.virtualflybrain.org"
UA = "bsc-vfb-recompute/1.0"
OUT = Path(__file__).resolve().parent / "out"


def post(url: str, payload: dict, accept: str = "application/json") -> bytes:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "Accept": accept,
                 "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def route_kb() -> dict:
    d = json.loads(post(KB, {"statements": [{"statement":
        "MATCH (n:Individual)-[:has_source]->(:DataSet {short_form:'%s'}) "
        "RETURN count(DISTINCT n), count(DISTINCT n.label)" % DS}]}))
    n, lab = d["results"][0]["data"][0]["row"]
    cls, pairs = json.loads(post(KB, {"statements": [{"statement":
        "MATCH (n:Individual)-[:has_source]->(:DataSet {short_form:'%s'}) "
        "MATCH (n)-[:INSTANCEOF]->(c:Class) "
        "RETURN count(DISTINCT c), count(*)" % DS}]})
        )["results"][0]["data"][0]["row"]
    # 一顆神經元可以同時屬於好幾個類別（例如「Dm15」與「麩胺酸性神經元」）。
    # pairs 就是（個體, 類別）配對的數量——下面第二條路數的其實是這個。
    # 一顆掛幾個類別的分布——②多出來的列就是從這裡來的
    rows = json.loads(post(KB, {"statements": [{"statement":
        "MATCH (n:Individual)-[:has_source]->(:DataSet {short_form:'%s'}) "
        "MATCH (n)-[:INSTANCEOF]->(c:Class) WITH n, count(c) AS k "
        "RETURN k, count(n) ORDER BY k" % DS}]})
        )["results"][0]["data"]
    dist = {str(r["row"][0]): r["row"][1] for r in rows}

    # 也確認一件事：一顆是不是只對到一個模板座標框（若不是，列數還有第二個來源）
    triples = json.loads(post(KB, {"statements": [{"statement":
        "MATCH (n:Individual)-[:has_source]->(:DataSet {short_form:'%s'}) "
        "MATCH (n)-[:INSTANCEOF]->(c:Class) "
        "MATCH (n)<-[:depicts]-(:Individual)-[:in_register_with]->(:Template) "
        "RETURN count(*)" % DS}]}))["results"][0]["data"][0]["row"][0]
    return {"neurons": n, "distinct_labels": lab, "classes": cls,
            "instanceof_pairs": pairs,
            "neurons_by_n_classes": dist,
            "individual_class_template_triples": triples}


def route_rest() -> dict:
    """**這條路回的是列數，不是個數**，而且會被截斷。

    `count` 欄是伺服器自己報的總數；實際能翻回來的列數另外數。
    兩者不一致的時候，不一致本身就是要寫進教材的事。
    """
    import urllib.parse
    rows, offset, size, count = [], 0, 10000, None
    while True:
        q = urllib.parse.urlencode({"id": DS, "query_type": "DatasetImages",
                                    "limit": size, "offset": offset},
                                   quote_via=urllib.parse.quote)
        req = urllib.request.Request(REST + "?" + q, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read().decode("utf-8", errors="replace"))
        count = d.get("count", count)
        got = d.get("rows") or []
        rows.extend(got)
        offset += len(got)
        if not got or offset >= min(count or 0, 50_000):
            break
    ids = {r.get("id") or r.get("short_form") for r in rows if isinstance(r, dict)}
    ids.discard(None)
    return {"count_reported": count, "rows_retrieved": len(rows),
            "distinct_ids_in_rows": len(ids),
            "truncated": count is not None and len(rows) < count}


def route_mcp() -> dict:
    """MCP：無認證、無 session id，但**要先 initialize**，不然回 404。"""
    def rpc(payload):
        req = urllib.request.Request(
            MCP, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream",
                     "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=180) as r:
            raw = r.read().decode("utf-8", errors="replace")
        for line in raw.splitlines():          # SSE 的話只有 data: 那行是 JSON
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return json.loads(raw)

    init = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "bsc-vfb", "version": "1.0"}}})
    res = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
               "params": {"name": "get_term_info", "arguments": {"id": DS}}})
    txt = "".join(c.get("text", "")
                  for c in (res.get("result") or {}).get("content", []))
    try:
        info = json.loads(txt)
    except Exception:
        return {"raw_excerpt": txt[:400]}
    q = info.get("Queries") or info.get("queries") or {}
    if isinstance(q, list):
        q = {x.get("query") or x.get("label"): x.get("count") for x in q}
    return {"server": ((init.get("result") or {}).get("serverInfo") or {}).get("version"),
            "queries": q, "dataset_images": q.get("DatasetImages")}


def main() -> int:
    OUT.mkdir(exist_ok=True)
    # **時間戳不寫進這個 JSON**，另外寫一個檔案。
    # 這一包的規矩是「時間只寫在 *_at.txt 裡，其餘檔案不含時間」——
    # 否則重跑一次 git diff 全是時間，看不出哪個數字真的變了。
    # （這一條原本只有 recompute.py 遵守，這裡漏了，乾淨重跑比對時才發現。）
    res = {"asked": f"資料集 {DS} 底下有幾顆神經元"}
    for name, fn in (("kb_cypher", route_kb), ("rest_run_query", route_rest),
                     ("mcp_get_term_info", route_mcp)):
        try:
            res[name] = fn()
        except Exception as e:
            res[name] = {"error": f"{type(e).__name__}: {e}"}
        print(name, json.dumps(res[name], ensure_ascii=False))
    kb, rest = res["kb_cypher"], res["rest_run_query"]
    pairs = kb.get("instanceof_pairs")
    reported = rest.get("count_reported")
    res["note"] = (
        "①③ 一致，② 不一致。② 多出來的不是神經元，是列："
        "DatasetImages 每一個（個體, 類別）配對給一列，而一顆神經元"
        "可以同時屬於好幾個類別（例如 Dm15_R 既是 Dm15，也是麩胺酸性神經元），"
        "所以列數本來就會比顆數多。"
        f"知識庫算出的配對數是 {pairs}，② 報的是 {reported}，"
        f"還差 {reported - pairs if (pairs and reported) else '?'} 列查不出來——"
        "**這一條沒有解掉，不要把它寫成已經解掉**。"
        "另外 ② 在五萬列處被截斷，回來的列裡不重複的 id 只有 "
        f"{rest.get('distinct_ids_in_rows')} 個。"
        "結論：要寫「幾顆神經元」就不能用 ②。")
    (OUT / "cross_check.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1) + "\n", "utf-8")
    (OUT / "cross_check_at.txt").write_text(
        f"旁證三條路的抓取時間 "
        f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}（UTC）\n",
        "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
