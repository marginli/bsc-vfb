# 用 VFB 的資料重算 Nern et al. 2025 的細胞型普查

這一包是 VFB 專題課程 PART 8 的產物，PART 9 逐段解釋它。

**它做什麼**：只用 Virtual Fly Brain 上的公開資料，重新算出
Nern et al. (2025, *Nature* 641: 1225–1237) 那篇視覺系統普查的逐型細胞數，
再跟論文補充表逐列比對，把對不上的部分分類列出來。

**它不做什麼**：不判斷論文對不對。兩邊是不同的處理管線，
差異多半是「同一件事被記成兩種樣子」。

## 怎麼跑

```bash
pip install openpyxl matplotlib        # 只需要這兩個
python3 recompute.py                   # 主流程，約 60 秒
python3 make_figure.py                 # 畫圖，約 2 秒（要先跑 recompute.py）
python3 cross_check.py                 # 換兩條路再問一次，約 50 秒
```

不需要 API key，不需要登入。三支程式都可以單獨重跑。

## 產出

| 檔案 | 是什麼 |
|---|---|
| `out/target.json` | 論文那一側：從補充表算出來的靶（逐列的型名與顆數） |
| `out/vfb.json` | VFB 那一側：資料集底下的神經元、類別、兩種比對鍵各自的計數 |
| `out/compare.json` | 逐列比對：對得上幾筆、顆數相同幾筆、三類對不上的完整清單 |
| `out/figure.json` | 圖上的點數（對角線上／偏離） |
| `out/class_tree_examples.json` | 「末端類別」與「泛稱」的實例；含一條被查出來是錯的直覺 |
| `out/scatter.png` | 逐型散點圖，以及 21 筆差異的大小 |
| `out/cross_check.json` | 同一個數字問三條路的結果，以及**還沒解掉**的那一條 |
| `out/paper_quotes.json` | 頁面上引的論文原句，以及它們逐字對回全文的結果 |
| `out/fetched_at.txt` | 主流程的抓取時間與每一個關鍵數字 |
| `out/cross_check_at.txt` | 旁證那一支的抓取時間 |

**時間戳只寫在 `out/fetched_at.txt` 與 `out/cross_check_at.txt` 裡**，其餘檔案不含時間。
這樣重跑一次之後，`git diff` 看得出來的就只有真正變掉的數字。

## 自己決定的參數

全部集中在 `recompute.py` 開頭的 `PARAMS`，只有三個：用哪一套資料、
拿什麼當比對的鍵、什麼算一個細胞型。**改任何一個，下面每個數字都會變**——
每一個旁邊都寫了改了會怎樣。例如把 `match_key` 從 `instance` 改成 `class`，
顆數相同的列數會從 732 掉到 535。

## 資料來源與授權

- 論文：doi:10.1038/s41586-025-08746-0，**CC-BY**。
  補充表 Supplementary Table 1 由程式直接向出版社的靜態內容站取得。
- VFB 資料集 `Nern2024`（neuPrint *JRC_Optic-Lobe*）。
  VFB 上的資料**逐筆各有授權**，要拿去用之前逐筆查。

教學用途，非營利。
