#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""稽核：凡是描述介面的句子，都要交代清楚它在哪裡、什麼時候成立。

   為什麼只管這幾件事：介面描述是這一型教材裡唯一無法自動驗對錯的東西
   （程式沒辦法替你去看那個畫面）。所以這支程式不查對錯，只查
   **有沒有把讀者需要的座標寫出來**。四道規則全部來自 _notes 第 15–21 條，
   每一條都對應一次學員真的卡住的經驗：

     A. 介面元件出現的那一節，要有擷取日期。
        介面會改版；沒有日期，讀者無從判斷這句話是什麼時候成立的。
     B. 給操作指示的那一節，要寫出網域。
        （第 18 條：作業單寫「打開 virtualflybrain.org」，那是說明文件站不是檢視器，
        學員在錯的網站上怎麼找都找不到。錯的不是描述，是起點。）
     C. 寫「會看到幾筆」要有畫面探針撐著。
        （第 20、21 條：同一個查詢，不同的框給不同的筆數，前端還會把一筆拆成好幾列。
        「幾筆」是介面的性質，不是資料的性質。）
        **這一條 2026-09-14 從全面禁止改成有條件放行**：當初禁止，是因為
        當時沒有任何辦法驗證畫面上究竟有幾列——唯一的來源是 API 的筆數，
        而那是另一回事。現在 scripts/browser_probe.py 用真的瀏覽器把列數數回來，
        存在 out/ui/。所以規則改成：**那一節的出處行要指名某一支探針輸出檔
        （out/….json，API 的或畫面的都算），而且要有擷取日期，才可以寫筆數**；
        兩者缺一仍然不准。指名到檔案是關鍵——只寫「由探針查得」等於沒有出處，
        重跑的時候沒有人知道要回頭比對哪一支。
        （PART 2 的主題正是「同一個字串在三個框給三種筆數」——
        若仍全面禁止，這一課就寫不出來，而它是學員最常撞到的那件事。）
     D. 作業單的每一步都要有網址，而且用到「看／找／確認」就要指名欄位。
        （第 18 條：網址是主線，介面描述是備案。
        第 19 條：說了「看什麼」沒說「去哪裡看」，學員到畫面前找不到東西。）

   **這支程式管不到的**：那句介面描述是不是真的。只有人去看畫面才知道。
   第 20 條就是在四道稽核全過的情況下寫出一句錯的介面描述的。

   用法：python3 scripts/ui_claim_audit.py              （掃專題根目錄所有 *.html）
         python3 scripts/ui_claim_audit.py part1-templates.html
   換一個專題時改 D 與 WIDGETS／DOMAINS 這幾行。
"""
import io, re, os, sys, glob, html

D = "/home/wanjuli/claude_linux/BSC_plan/specific_topics/VFB"

# 具名的介面元件。**不要**放「畫面」「欄」「點」這種泛稱——
# 它們在講圖、講表、講質心的句子裡到處都是，放進來整份稽核就被雜訊淹掉。
WIDGETS = [r'Term Info', r'資訊面板', r'搜尋框', r'檢視器', r'網址列', r'下拉',
           r'按鈕', r'圖示', r'命令面板', r'<code>Quer(y For|ies)</code>',
           r'Aligned [Tt]o', r'<code>Licenses?</code>', r'<code>Symbol</code>',
           r'<code>Source</code>', r'<code>Name</code>']


def widget_name(pat):
    """把 regex 還原成人看的名字（<code>Queries</code> → Queries）。"""
    return re.sub(r'</?code>', '', pat)
# 有這些字＝這一段在給操作指示
IMPERATIVE = [r'打開', r'輸入', r'貼到', r'點進', r'執行它', r'往下捲', r'搜尋 <code>']
# 有這些字＝這一句在斷言「畫面上會長成什麼樣」——那才是會過期、需要標日期的句子。
# 只是提到某個元件的名字（例如首頁的課程地圖）不算。
SHOWS = [r'會出現', r'寫著', r'列的是', r'顯示的是', r'有一區叫', r'有一欄叫', r'會轉到']
# 叫人「移動到某個地方」的步驟才需要網址；在同一頁上繼續做的步驟不需要。
NAVIGATE = [r'打開', r'開啟', r'貼到', r'前往', r'網址：']
DOMAINS = [r'virtualflybrain\.org']
# 「會看到幾筆」的各種寫法
COUNT_CLAIM = re.compile(
    r'(會?看到|回來的?|顯示|給你|只有|剩下)[^。；]{0,12}?\d[\d,]*\s*(筆|列|個結果|項)')
DATE = re.compile(r'20\d\d-\d\d-\d\d|20\d\d\s*年\s*\d+\s*月\s*\d+\s*日')


def text_of(frag):
    t = re.sub(r'<(script|style)\b.*?</\1>', ' ', frag, flags=re.S)
    return html.unescape(re.sub(r'<[^>]+>', ' ', t))


def sections(src):
    # 最後一節的範圍會一路吃到頁尾，而頁尾有日期也有出處字樣——
    # 不切掉的話，最後一節等於自動通過所有「這一節有沒有…」的檢查（實測過）。
    cut = src.find('<div class="pager"')
    if cut > 0:
        src = src[:cut]
    parts = re.split(r'(<h2\b[^>]*id="s\d+"[^>]*>.*?</h2>)', src, flags=re.S)
    out = [("(前言)", "(前言)", parts[0])]
    for k in range(1, len(parts), 2):
        sid = re.search(r'id="(s\d+)"', parts[k]).group(1)
        title = re.sub(r'\s+', ' ', text_of(parts[k])).strip()
        out.append((sid, title, parts[k] + parts[k + 1]))
    return out


def audit(path):
    b = os.path.basename(path)
    src = re.sub(r'<(script|style)\b.*?</\1>', ' ', io.open(path, encoding="utf-8").read(),
                 flags=re.S)
    bad = 0
    print(f"══════ {b}")
    checked = 0

    for sid, title, body in sections(src):
        txt = text_of(body)
        hits = sorted({w for w in WIDGETS if re.search(w, body)})
        gives_orders = any(re.search(p, body) for p in IMPERATIVE)
        asserts_ui = any(re.search(p, body) for p in SHOWS)
        if not hits and not gives_orders:
            continue
        checked += 1
        name = f"{sid} {title[:24]}"

        # A. 斷言「畫面長什麼樣」就要有日期（只是提到元件名字不算）
        if hits and asserts_ui and not DATE.search(txt):
            print(f"  [缺日期] {name} 斷言了畫面上會出現什麼"
                  f"（{'、'.join(widget_name(h) for h in hits[:3])}），卻沒有擷取日期")
            bad += 1
        # B. 給操作指示就要寫出網域
        if gives_orders and not any(re.search(d, body) for d in DOMAINS):
            print(f"  [缺網域] {name} 在給操作指示，卻沒寫明是在哪一個網站上做")
            bad += 1

    # C. 寫筆數要有探針撐著：這一節要同時指名某支 out/….json 與擷取日期
    for sid, title, body in sections(src):
        txt = text_of(body)
        backed = bool(re.search(r"out/[\w/]*\.json", body)) and bool(DATE.search(txt))
        for m in COUNT_CLAIM.finditer(txt):
            if backed:
                continue
            ctx = re.sub(r'\s+', ' ', txt[max(0, m.start() - 20):m.end() + 12])
            print(f"  [講筆數] {sid} …{ctx}…"
                  f"　（要寫筆數，這一節得指名某支 out/….json 並標擷取日期）")
            bad += 1

    # D. 作業單每一步：叫人移動就要給網址；叫人去看就要指名欄位
    #    只看「在給操作指示」的那一節——目錄那種純錨點的 <ol> 不算作業單。
    for sid, title, body in sections(src):
        if "<ol>" not in body or not any(re.search(p, body) for p in IMPERATIVE):
            continue
        for i, li in enumerate(re.findall(r'<li>(.*?)</li>', body, flags=re.S), 1):
            if (any(re.search(p, li) for p in NAVIGATE)
                    and not re.search(r'href="https?://', li)):
                print(f"  [缺網址] {sid} 第 {i} 步叫人打開某個地方，卻沒給可以直接貼的網址")
                bad += 1
            # 「指名了欄位」＝ 有一個 <code> 裝的不是編號也不是網址。
            #   步驟裡多半也會用 <code> 包 VFB_00101567 這種編號，
            #   只數 <code> 的話，把欄位名拿掉照樣過關（實測過）。
            names = [c.strip() for c in re.findall(r'<code>(.*?)</code>', li)]
            names = [c for c in names
                     if not re.fullmatch(r'(VFB|VFBc|FBbt)_\d+', c)
                     and "http" not in c and "/" not in c]
            if re.search(r'看|找|確認', text_of(li)) and not names:
                print(f"  [缺欄位] {sid} 第 {i} 步叫人去看／找，卻沒指名是哪一個欄位或區塊")
                bad += 1

    print(f"  查了 {checked} 節有介面描述或操作指示")
    return bad


def main():
    args = sys.argv[1:]
    files = ([os.path.join(D, a) if not os.path.isabs(a) else a for a in args]
             or sorted(glob.glob(os.path.join(D, "*.html"))))
    bad = sum(audit(f) for f in files)
    print("\n=== 稽核：介面描述 ===", "全部通過" if bad == 0 else f"{bad} 個問題")
    print("　（這一道不查對錯——介面描述是不是真的，只有人去看畫面才知道。）")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
