# VFB 專題課程

教學員怎麼用 [Virtual Fly Brain](https://www.virtualflybrain.org/)——果蠅神經系統的知識庫。

線上版：`https://marginli.github.io/bsc-vfb`（`robots.txt` 擋掉搜尋引擎索引）

## 這個 repo 有什麼

| 路徑 | 是什麼 |
|---|---|
| `index.html` | 課程首頁 |
| `part1-templates.html` | PART 1　座標系：template 與 registration |
| `part2-names.html` | PART 2　把一個名字問清楚 |
| `part3-queries.html` | PART 3　從腦區找到神經元 |
| `part4-connectomes.html` | PART 4　連線體 |
| `part5-nblast.html` | PART 5　形態比對：NBLAST 與 FlyCircuit |
| `part6-api.html` | PART 6　接到程式與 AI |
| `part7-agent-prompts.html` | PART 7　要怎麼交代 AI Agent |
| `part8-agent-run.html` | PART 8　真的讓它跑一遍 |
| `part9-read-code.html` | PART 9　讀懂它寫出來的程式 |
| `assets/` | 共用樣式與所有圖檔 |
| `scripts/vfb_probe.py` | **API 探針**：把教材用到的查詢向 VFB 跑一遍，存進 `out/` |
| `scripts/browser_probe.py` | **畫面探針**：用真的瀏覽器把學員會看到的畫面拍一遍，存進 `out/ui/` |
| `scripts/make_part1_figures.py` | PART 1 的六張真實資料圖 |
| `scripts/make_part5_figures.py` | PART 5 的兩張骨架比對圖（本機 FlyCircuit vs VFB 下載） |
| `scripts/paper_target.py` | PART 7–9 的「靶」：抓 Nern et al. 2025 的補充表，算出要重算的那組數字 |
| `scripts/three_layers.py` | PART 6 的三層對照：同一個問題用滑鼠／`vfb-connect`／MCP 各問一次（需 `pip install --user vfb-connect`） |
| `scripts/video_slides.py` | 首頁那支說明影片的**投影片要點＋旁白稿**（寫在同一個檔） |
| `scripts/make_video.py` | 產生影片：Chrome 截圖 → 合成旁白 → ffmpeg 併成 mp4 ＋ WebVTT 字幕 |
| `scripts/video_check.py` | 查「投影片上寫的每一點，旁白有沒有講到」 |
| `scripts/*_audit.py` | 九道稽核 |
| `recompute/` | **PART 8／9 的產物**：三支程式（`recompute.py`、`cross_check.py`、`make_figure.py`）＋說明。<br>只用 VFB 的資料重算 Nern et al. 2025 的細胞型普查。**不部署**——同一份已包在 `downloads/` 的 zip 裡 |
| `recompute/run_meta.py` | **量那一包自己**：行數、註解比例、換一個參數會怎樣、以及把 zip 解到空資料夾重跑一次。<br>**它不在交付的那一包裡**，產出直接寫到 `out/recompute/run_meta.json`——描述某個 zip 的檔案不能住在那個 zip 裡面 |
| `downloads/vfb-recompute.zip` | 上面那一包，給讀者下載。改了 `recompute/` 之後要重打包 |
| `out/` | 探針的原始輸出。**頁面上每個數字都對得回這裡** |
| `out/ui/` | 畫面探針的輸出。**頁面上每個介面名字都對得回這裡** |
| `out/recompute/` | `recompute/out/` 的副本。**PART 8／9 的數字對回這裡**（稽核只掃 `out/`） |
| `_notes/` | 修正紀錄（給教材設計者，不部署） |

## 這門課的兩條規矩

**一、頁面上每一個數字、每一個介面名字，都要有一支存下來的探針輸出可以對回去。**

探針有兩支，分工要記住——**「資料庫裡有什麼」跟「學員螢幕上有什麼」是兩件事**：

| | 問什麼 | 輸出 |
|---|---|---|
| `scripts/vfb_probe.py` | API：資料庫裡有什麼 | `out/*.json` |
| `scripts/browser_probe.py` | 真的瀏覽器：學員螢幕上有什麼 | `out/ui/*.json` ＋ 截圖（不進版控） |

VFB 換版之後兩支都重跑，程式會列出哪些檔案的內容變了——那就是要回頭複查的清單。

三道稽核分別守住它的三個面向：

- **`number_audit.py`**：頁面上每個數字都對得回 `out/`（含 `out/ui/`），
  且每一節都有出處行。**天花板**：它查的是「這個數字出現過沒有」，
  不是「出現在對的地方」，所以改完數字要用 `--where` 掃一眼。
- **`field_audit.py`**：頁面上 `<code>` 包起來的每個介面名字，對回探針拍到的字串，
  分成**畫面上有／只有 API 有／兩邊都沒有**三桶。**中間那桶是重點**——
  把 API 的欄位名當成畫面上的欄位名，是這個專題犯過最多次的錯（一輪六處）。
  **天花板**：跨版本的張冠李戴它抓不到（v2 叫 `License`、v3 叫 `Licenses`，兩個都在）。
- **`value_audit.py`**：頁面上「資料集／站台／來源」的**值**，逐字對回探針。
  **`field_audit` 查的是欄位名，這一道查的是欄位裡的值**——連兩頁犯過同一型的錯
  （八個站台名有四個被縮寫、三個來源名有一個被縮寫），而前八道一道都抓不到。
  判準是**從版本號定位**（`v1.0.1`、`v783`），因為改寫的人幾乎不會動版本號。
  頁面自己的簡寫列在 `ACCEPTED`，一筆一個理由，**而且是最後才查**。
- **`ui_claim_audit.py`**：介面描述無法自動驗真假，所以它只查
  **有沒有把讀者需要的座標寫出來**——在哪一個網域、去哪一個欄位看、這句話什麼時候成立。
  另外，**要寫畫面上的列數，那一節就得指名某一支 `out/….json` 並標擷取日期**；
  沒有探針撐著就不准寫，因為「幾筆」是介面的性質，不是資料的性質。

**二、介面會改版，問題不會。**
所以能給網址的地方就給網址，不描述介面；非描述不可的時候，
要寫明在哪一個網域、去哪一個欄位看、這句話什麼時候成立。
需要的時候會多寫兩層（同一件事的程式寫法、同一件事怎麼問 AI），
但**不是每一節都湊三層**——滑鼠做得完的事，多寫兩遍只是把同一件事說三次。
教材的可驗證性由第一條那套探針與稽核撐住，跟寫了幾層無關。

完整規範見 `../CLAUDE.md`（共通核心）與 `../types/tool.md`（工具導覽型）。

## 怎麼重跑

```bash
python3 scripts/vfb_probe.py            # API 探針（約 40 秒）
python3 scripts/browser_probe.py        # 畫面探針（約 12 分鐘，會開無頭瀏覽器）
python3 scripts/vfb_probe.py --full     # 連要翻幾萬列的那支一起跑（約 85 秒）
python3 scripts/make_part1_figures.py   # 重畫 PART 1 的圖（需要本機 BSC_plan/D03）
python3 scripts/page_audit.py            # 標籤、連結、錨點、中英夾雜
python3 scripts/number_audit.py         # 每個數字對回 out/；每一節有沒有出處行
python3 scripts/number_audit.py --where part1-templates.html   # 印出數字對到哪一支探針
python3 scripts/ui_claim_audit.py        # 介面描述：日期、網域、欄位名，以及不准講筆數
python3 scripts/field_audit.py          # 介面名字對回 out/ui/（畫面上有／只有 API 有／兩邊都沒有）
python3 scripts/field_audit.py --where part3-queries.html
python3 scripts/quote_audit.py          # 英文引文逐條對回 VFB 說明文件
python3 scripts/code_audit.py           # 頁面上引用的程式碼逐行對回原始碼
python3 scripts/value_audit.py          # 資料集／站台／來源的「值」是不是逐字
python3 scripts/video_check.py          # 投影片上寫的每一點，旁白有沒有講到
python3 scripts/make_video.py           # 重做首頁那支說明影片（改了投影片或旁白才要跑）
python3 scripts/svg_audit.py *.html     # SVG 元素有沒有超出 viewBox
python3 scripts/content_audit.py terms part1-templates.html
python3 scripts/content_audit.py refs  part3-queries.html   # 指涉詞有沒有指名對象
```

PART 8／9 那一包要重跑或改動時：

```bash
cd recompute
python3 recompute.py && python3 make_figure.py    # 主流程＋圖，約 65 秒
python3 cross_check.py                             # 三條路的旁證，約 50 秒
cp out/*.json out/*.txt ../out/recompute/          # 同步給稽核用
cd .. && rm -f downloads/vfb-recompute.zip
cd recompute && zip -qr ../downloads/vfb-recompute.zip \
    recompute.py make_figure.py cross_check.py README.md out/
python3 run_meta.py --zip ../downloads/vfb-recompute.zip   # 量行數＋乾淨重跑，約 2.5 分鐘
```

## 資料來源與授權

頁面上的真實資料圖用的是本機 D03 那包：
模板 FCWB（Ostrovsky & Jefferis 2014，CC0）、
分區 FCWBNP（natverse，GPL-3；分區出自 Ito et al. 2014, *Neuron* 81:755–765）。
VFB 的說明文字以引文方式引用並註明出處與讀取日期。
VFB 上的資料**逐筆各有授權**（JRC2018 系列是 CC-BY-NC-SA 4.0、hemibrain template 是 CC-BY 4.0、
FlyCircuit 是自訂授權），要用之前逐筆查。

教學用途，非營利。
