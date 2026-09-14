# VFB 專題課程

教學員怎麼用 [Virtual Fly Brain](https://www.virtualflybrain.org/)——果蠅神經系統的知識庫。

線上版：`https://marginli.github.io/bsc-vfb`（`robots.txt` 擋掉搜尋引擎索引）

## 這個 repo 有什麼

| 路徑 | 是什麼 |
|---|---|
| `index.html` | 課程首頁 |
| `part1-templates.html` | PART 1　座標系：template 與 registration |
| `assets/` | 共用樣式與所有圖檔 |
| `scripts/vfb_probe.py` | **探針**：把教材用到的查詢向 VFB 跑一遍，存進 `out/` |
| `scripts/make_part1_figures.py` | PART 1 的六張真實資料圖 |
| `scripts/*_audit.py` | 六道稽核 |
| `out/` | 探針的原始輸出。**頁面上每個數字都對得回這裡** |
| `_notes/` | 修正紀錄（給教材設計者，不部署） |

## 這門課的兩條規矩

**一、頁面上每一個數字，都要有一支存下來的 API 輸出可以對回去。**
所以有 `scripts/vfb_probe.py`。VFB 換版之後重跑一次，程式會列出哪些檔案的內容變了
——那就是要回頭複查的清單。這條規矩由 `scripts/number_audit.py` 把關：
它逐一比對頁面上的每個數字，並檢查每一節都有出處行。
**它的天花板要知道**——它查的是「這個數字出現過沒有」，不是「出現在對的地方」，
所以改完數字要用 `--where` 掃一眼對上的來源對不對。

`scripts/ui_claim_audit.py` 管另一半：介面描述無法自動驗真假，
所以它只查**有沒有把讀者需要的座標寫出來**——在哪一個網域、去哪一個欄位看、
這句話什麼時候成立，以及**不准寫「你會看到幾筆」**（那是介面的性質，不是資料的性質）。

**二、介面會改版，問題不會。**
所以能給網址的地方就給網址，不描述介面；非描述不可的時候，
要寫明在哪一個網域、去哪一個欄位看、這句話什麼時候成立。
需要的時候會多寫兩層（同一件事的程式寫法、同一件事怎麼問 AI），
但**不是每一節都湊三層**——滑鼠做得完的事，多寫兩遍只是把同一件事說三次。
教材的可驗證性由第一條那套探針與稽核撐住，跟寫了幾層無關。

完整規範見 `../CLAUDE.md`（共通核心）與 `../types/tool.md`（工具導覽型）。

## 怎麼重跑

```bash
python3 scripts/vfb_probe.py            # 跑探針（約 40 秒）
python3 scripts/vfb_probe.py --full     # 連要翻幾萬列的那支一起跑（約 85 秒）
python3 scripts/make_part1_figures.py   # 重畫 PART 1 的圖（需要本機 BSC_plan/D03）
python3 scripts/page_audit.py            # 標籤、連結、錨點、中英夾雜
python3 scripts/number_audit.py         # 每個數字對回 out/；每一節有沒有出處行
python3 scripts/number_audit.py --where part1-templates.html   # 印出數字對到哪一支探針
python3 scripts/ui_claim_audit.py        # 介面描述：日期、網域、欄位名，以及不准講筆數
python3 scripts/quote_audit.py          # 英文引文逐條對回 VFB 說明文件
python3 scripts/svg_audit.py *.html     # SVG 元素有沒有超出 viewBox
python3 scripts/content_audit.py terms part1-templates.html
```

## 資料來源與授權

頁面上的真實資料圖用的是本機 D03 那包：
模板 FCWB（Ostrovsky & Jefferis 2014，CC0）、
分區 FCWBNP（natverse，GPL-3；分區出自 Ito et al. 2014, *Neuron* 81:755–765）。
VFB 的說明文字以引文方式引用並註明出處與讀取日期。
VFB 上的資料**逐筆各有授權**（JRC2018 系列是 CC-BY-NC-SA 4.0、hemibrain template 是 CC-BY 4.0、
FlyCircuit 是自訂授權），要用之前逐筆查。

教學用途，非營利。
