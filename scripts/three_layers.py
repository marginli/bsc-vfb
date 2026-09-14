#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""three_layers.py — 同一個問題，用滑鼠、程式、AI 各問一次，然後比對。

問題固定是這一個（PART 3 做過的那個）：
    medulla（FBbt_00003748）裡「有一部分在裡面」的神經元種類，有幾種？

三層各自怎麼問：
    滑鼠   檢視器的 Query For 區點 `Neurons with some part in medulla`
           → 數字由 scripts/browser_probe.py 拍下，存在 out/ui/query_results.json
    程式   vfb_connect 的 get_terms_by_region()
    AI     VFB 自己的 MCP server 的 run_query 工具

**這支程式存在的理由，是 types/tool.md〈跨頁一致性〉那一條**：
三層要拿得到同一個答案；**答案不一樣的時候，要當場說為什麼，不能留給讀者自己比。**
實測三層不是一開始就一致——差別全部出在**參數的預設值**，而那正是要教的東西。

需要 `pip install --user vfb-connect`（PART 6 自己會教怎麼裝）。
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path("/home/wanjuli/claude_linux/BSC_plan/specific_topics/VFB")
OUT = ROOT / "out"
sys.path.insert(0, str(ROOT / "scripts"))
import vfb_probe as V  # noqa: E402

REGION = "FBbt_00003748"
REGION_NAME = "medulla"
QUERY_TYPE = "NeuronsPartHere"
MCP = "https://vfb3-mcp.virtualflybrain.org"


def mouse_layer() -> dict:
    """滑鼠那一層的答案，直接讀畫面探針拍下來的標題列。"""
    d = json.loads((OUT / "ui" / "query_results.json").read_text("utf-8"))
    title = d.get("title_bar") or ""
    return {"how": "檢視器的 Query For 區點下那支查詢",
            "title_on_screen": title,
            "n": int(title.split()[0]) if title[:1].isdigit() else None,
            "source": "out/ui/query_results.json"}


def rest_layer() -> dict:
    """REST 那一層——滑鼠背後打的就是它，用來確認畫面上的數字不是別的東西。"""
    url, count, rows, _ = V.paged("/run_query",
                                  {"id": REGION, "query_type": QUERY_TYPE}, page=2000)
    return {"how": f"/run_query?id={REGION}&query_type={QUERY_TYPE}",
            "n": count, "ids": sorted({V.strip_markup(r.get("id", "")) for r in rows}),
            "url": url}


def code_layer() -> dict:
    """程式那一層。**兩個呼叫都要跑**：預設值與 cells_only=True，
    因為它們的差別正是這一節要講的事。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from vfb_connect import VfbConnect
        vc = VfbConnect()
        default = vc.get_terms_by_region(REGION_NAME)
        cells = vc.get_terms_by_region(REGION_NAME, cells_only=True)
    return {"how": "vfb_connect.get_terms_by_region()",
            "banner_chars_printed_on_import": len(buf.getvalue()),
            "default": {"call": f"get_terms_by_region('{REGION_NAME}')",
                        "n": len(default), "ids": sorted(set(default["id"]))},
            "cells_only": {"call": f"get_terms_by_region('{REGION_NAME}', cells_only=True)",
                           "n": len(cells), "ids": sorted(set(cells["id"]))}}


def ai_layer() -> dict:
    """AI 那一層：MCP server 的 run_query。無認證、無 session id。"""
    def rpc(payload):
        req = urllib.request.Request(
            MCP, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))

    init = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "bsc-vfb", "version": "1.0"}}})
    server = (init.get("result") or {}).get("serverInfo") or {}
    # 工具清單要存下來——頁面上會逐個列出它們的名字，不存就無從追回
    tl = rpc({"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {}})
    tools = [{"name": t["name"],
              "params": list(((t.get("inputSchema") or {}).get("properties") or {})),
              "required": (t.get("inputSchema") or {}).get("required") or [],
              "description_first_line": (t.get("description") or "").splitlines()[:1]}
             for t in (tl.get("result") or {}).get("tools", [])]

    res = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
               "params": {"name": "run_query",
                          "arguments": {"id": REGION, "query_type": QUERY_TYPE,
                                        "limit": 3}}})
    txt = "".join(c.get("text", "")
                  for c in (res.get("result") or {}).get("content", []))
    o = json.loads(txt)
    # VFB 的說明文件介紹七類工具；實際問它，回來的比七個多。
    documented = {"get_term_info", "search_terms", "run_query", "get_hierarchy",
                  "list_search_facets", "resolve_entity", "resolve_combination"}
    names = {t["name"] for t in tools}
    return {"how": "MCP tools/call run_query", "endpoint": MCP,
            "server": f"{server.get('name')} {server.get('version')}",
            "protocol": (init.get("result") or {}).get("protocolVersion"),
            "n_tools": len(tools),
            "tools": tools,
            "documented_seven_all_present": documented <= names,
            "tools_not_in_docs": sorted(names - documented),
            "n": o.get("count"), "keys_returned": list(o)}


def main() -> int:
    mouse, rest, code, ai = mouse_layer(), rest_layer(), code_layer(), ai_layer()
    r_ids = set(rest["ids"])
    c_ids = set(code["cells_only"]["ids"])
    only_code, only_rest = sorted(c_ids - r_ids), sorted(r_ids - c_ids)

    def describe(ids):
        if not ids:
            return []
        lit = "[" + ",".join(f"'{x}'" for x in ids) + "]"
        return [{"id": r[0], "label": r[1], "kinds": r[2]} for r in V.cypher(
            "MATCH (c:Class) WHERE c.short_form IN %s RETURN c.short_form, c.label, "
            "[l IN labels(c) WHERE l IN ['Neuron','Cell','Deprecated']] AS kind "
            "ORDER BY c.short_form" % lit)[1]]

    payload = {
        "question": f"{REGION_NAME}（{REGION}）裡有一部分在裡面的神經元種類，有幾種？",
        "mouse": mouse, "rest_behind_the_mouse": {k: v for k, v in rest.items()
                                                  if k != "ids"},
        "code": {k: (v if k != "default" and k != "cells_only"
                     else {kk: vv for kk, vv in v.items() if kk != "ids"})
                 for k, v in code.items()},
        "ai": ai,
        "agree_mouse_rest_ai": mouse["n"] == rest["n"] == ai["n"],
        "code_default_minus_rest": code["default"]["n"] - rest["n"],
        "code_cells_only_vs_rest": {
            "shared": len(c_ids & r_ids),
            "only_in_code": describe(only_code),
            "only_in_rest": describe(only_rest)},
        "note": ("滑鼠、REST、MCP 三者給同一個數字。程式那一層預設多出來的是"
                 "**這個腦區的次分區**（不是神經元）；加上 cells_only=True 之後，"
                 "剩下的差別是**膠細胞**（cell 不等於 neuron）與**一個已棄用的詞**"
                 "（vfb_connect 預設 include_deprecated=False，REST 沒有這個預設）。"
                 "三個差別全部來自參數的預設值。"),
    }
    (OUT / "three_layers.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"  滑鼠 {mouse['n']}　REST {rest['n']}　MCP {ai['n']}　"
          f"三者一致：{payload['agree_mouse_rest_ai']}")
    print(f"  程式 預設 {code['default']['n']}／cells_only {code['cells_only']['n']}")
    print(f"  cells_only 與 REST：共有 {len(c_ids & r_ids)}、"
          f"只在程式 {len(only_code)}、只在 REST {len(only_rest)}")
    print("  → out/three_layers.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
