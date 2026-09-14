#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""稽核：頁面上寫的每一個介面名字，都要真的出現在畫面探針拍到的東西裡。

   這是第七道。它補的是 `ui_claim_audit.py` 的天花板——那一道只查
   「有沒有寫出座標」（網域、欄位名、擷取日期），**欄位名寫錯它照樣放行**。
   而欄位名寫錯正是這個專題犯過最多次的一類：一輪就六處（_notes 第 31 條），
   全部是從 API 回傳推出來的，而 **API 的欄位名跟畫面上的欄位名不是同一組**。

   作法跟 `number_audit.py` 同一個模子，只是對象從數字換成名字：
   把 `out/ui/*.json` 裡所有字串串成一份「我們真的拍到的東西」，
   再把頁面上 `<code>` 包起來、長得像介面名字的每一個字串拿去比對。

   結果分三桶，**中間那一桶才是這道稽核真正的價值**：

     ✓ **畫面上有**　　　在 out/ui/*.json 裡找得到。過。
     ⚠ **只有 API 有**　只在 out/*.json 裡找得到、畫面探針沒拍到。
                        **這正是第 31 條那六個錯躲藏的位置**——
                        把 API 的欄位名當成畫面上的欄位名寫出去。
                        不一定錯（頁面本來就會引用 API 的欄位名），但**每一個都要人看一眼**。
     ✗ **兩邊都沒有**　  失敗。要嘛寫錯了，要嘛該補一支探針。

   **這一道的天花板（要知道，否則會高估它）**：

   1. **它查的是「這個字串有沒有被拍到」，不是「它出現在對的地方」。**
      v2 的授權欄叫 `License`、v3 叫 `Licenses`，兩個都在探針輸出裡；
      所以把 v2 的那一欄寫成 `Licenses` 它抓不到。**跨版本的張冠李戴要靠人。**
   2. **它只看 `<code>`。** 寫在 `<i>` 或純文字裡的欄位名它看不到——
      所以規矩是：**凡是介面上的名字，一律用 `<code>` 包起來。**
   3. 對不上的不一定是錯的，所以有 EXEMPT，**每一筆都要寫理由**。

   用法：python3 scripts/field_audit.py                （掃專題根目錄所有 *.html）
         python3 scripts/field_audit.py part3-queries.html
         python3 scripts/field_audit.py --where part3-queries.html
                                                （印出每個名字是在哪幾支探針裡對上的）
   換一個專題時只要改 D 這一行。
"""
import glob
import io
import json
import os
import re
import sys

D = "/home/wanjuli/claude_linux/BSC_plan/specific_topics/VFB"

# ── 對不回畫面探針但確定沒問題的字串：一筆一個理由 ──────────────────────
EXEMPT = {
    "Painted domains": "這是查詢標籤的前半，頁面上完整寫的是 "
                       "`Painted domains for JRC2018U`／`for JFRC2`，"
                       "兩個完整字串都對得回 out/ui/painted_domains.json。",
}

# 長得像「介面上的名字」的 <code> 內容：字母開頭，只含字母、數字、空白、底線、括號。
# 排除掉路徑（含 / . :）、標籤（含 < >）、以及編號。
LOOKS_LIKE_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9 _()]{0,39}$")
CJK = re.compile(r"[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]")
# 探針自己的中介資料，不是服務端的東西
META_KEYS = {"probe", "part", "question", "note", "url", "urls", "site"}
IS_ID = re.compile(r"^(VFB|VFBc|FBbt|FBrf)_[0-9a-z]+$")
# 這些是常見的非介面字串，不要當成欄位名去查
NOT_A_FIELD = {
    "true", "false", "null", "id", "label", "tags", "template", "technique",
    "thumbnail", "name", "gross type",
}


def haystack(sub):
    """探針輸出裡出現過的每一段字串 → 出自哪幾支探針。

    sub="ui" 是畫面探針（學員螢幕上有什麼），sub="api" 是 API 探針（資料庫裡有什麼）。
    **兩份要分開**，因為「這個名字只有 API 有」本身就是一個要看的訊號。
    """
    pat = ("out/ui/*.json" if sub == "ui" else "out/*.json")
    blobs = {}
    for f in sorted(glob.glob(os.path.join(D, *pat.split("/")))):
        if os.path.basename(f) == "_manifest.json":
            continue
        chunks = []

        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k in META_KEYS:
                        continue
                    # 鍵也要套中文過濾：這個專題的 JSON 有中文的鍵
                    # （例如「第4步：Term Info 的 … 欄」），而那些鍵裡可能抄著舊的欄位名。
                    if not CJK.search(str(k)):
                        chunks.append(str(k))
                    walk(v)
            elif isinstance(o, (list, tuple)):
                for v in o:
                    walk(v)
            elif isinstance(o, str):
                # **含中文的字串一律跳過。** 探針輸出裡混著我們自己寫的說明
                # （note、question、以及中文的 JSON 鍵），而那些說明裡就可能
                # 抄著一個寫錯的欄位名——那會讓這道稽核把真錯誤降級成警告。
                # 服務端的東西是英文，我們自己的註解是中文，這條線分得很乾淨。
                if CJK.search(o):
                    return
                chunks.append(o)

        walk(json.load(io.open(f, encoding="utf-8")))
        tag = ("ui/" if sub == "ui" else "") + os.path.basename(f)
        blobs[tag] = "\n".join(chunks)
    return blobs


def candidates(src):
    """頁面上 <code> 包起來、長得像介面名字的字串（去重，保留出現順序）。

    **出處行（`<p class="figsrc">`）整段排除**：那裡的 `<code>` 裝的是檔名、
    探針名、JSON 的鍵（`worksheet`、`docsite_search_box`、`ListAllAvailableImages`），
    它們是在講我們自己的檔案結構，不是在講介面上的名字。
    不排除的話，出處行寫得愈仔細、雜訊愈多——那等於處罰好習慣。
    """
    src = re.sub(r'<p class="figsrc">.*?</p>', " ", src, flags=re.S)
    out = []
    for c in re.findall(r"<code>(.*?)</code>", src, flags=re.S):
        t = re.sub(r"<[^>]+>", "", c)
        t = t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").strip()
        if not t or t in out:
            continue
        if IS_ID.match(t) or t.lower() in NOT_A_FIELD:
            continue
        if not LOOKS_LIKE_FIELD.match(t):
            continue
        out.append(t)
    return out


def audit(path, ui, api, where=False):
    b = os.path.basename(path)
    src = io.open(path, encoding="utf-8").read()
    names = candidates(src)
    seen, api_only, bad, exempt = [], [], [], []
    print(f"══════ {b}")

    def context(t):
        m = re.search(r".{0,60}<code>" + re.escape(t) + r"</code>.{0,60}", src, re.S)
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(0))) if m else ""

    for t in names:
        hits = [f for f, blob in ui.items() if t in blob]
        if hits:
            seen.append(t)
            if where:
                print(f"  ✓ {t:26s} ← {', '.join(sorted(hits))}")
            continue
        ahits = [f for f, blob in api.items() if t in blob]
        if ahits:
            api_only.append(t)
            print(f"  ⚠ 只有 API 有　{t!r} ← {', '.join(sorted(ahits)[:3])}")
            if where:
                print(f"      …{context(t)}…")
            continue
        if t in EXEMPT:
            exempt.append(t)
            continue
        bad.append(t)
        print(f"  ✗ 兩邊都沒有　{t!r}　…{context(t)}…")
    print(f"  查了 {len(names)} 個：畫面上有 {len(seen)}、只有 API 有 {len(api_only)}、"
          f"兩邊都沒有 {len(bad)}"
          f"{f'（另有 {len(exempt)} 個列在 EXEMPT）' if exempt else ''}")
    return len(bad)


def main():
    args = [a for a in sys.argv[1:] if a != "--where"]
    where = "--where" in sys.argv[1:]
    files = ([os.path.join(D, a) if not os.path.isabs(a) else a for a in args]
             or sorted(glob.glob(os.path.join(D, "*.html"))))
    ui, api = haystack("ui"), haystack("api")
    if not ui:
        sys.exit("out/ui/ 裡沒有畫面探針的輸出——先跑 scripts/browser_probe.py")
    print(f"畫面探針 {len(ui)} 支、API 探針 {len(api)} 支\n")
    bad = sum(audit(f, ui, api, where) for f in files)
    print("\n=== 稽核：介面名字對回探針 ===",
          "全部通過" if bad == 0 else f"{bad} 個兩邊都沒有")
    print("　（⚠ 那一類不算失敗，但每一個都要人看一眼："
          "把 API 的欄位名當成畫面上的欄位名，是這個專題犯過最多次的錯。）")
    print("　（天花板：它查的是「有沒有被拍到」，不是「出現在對的版本上」。"
          "v2／v3 的張冠李戴要靠人。）")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
