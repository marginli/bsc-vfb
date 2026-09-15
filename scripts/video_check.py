#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""檢查說明影片的旁白有沒有講到投影片上寫的每一點。

   投影片是給眼睛看的摘要，旁白是給耳朵聽的完整句子。
   **上面寫了、下面沒講**是最容易被觀眾抓到的缺陷（使用者的原話：
   「有一些投影片上有寫的資料，你都沒有講到」）。

   查兩件事：
     1. 要點裡的每一個數字，旁白有沒有出現（數字最容易漏）
     2. 要點裡用 <b> 標出來的關鍵詞，旁白有沒有涵蓋（比對去掉標點的字串）

   用法：python3 scripts/video_check.py
"""
import os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from video_slides import SLIDES                      # noqa: E402
from make_video import FIX                           # noqa: E402

# 旁白一律用阿拉伯數字（TTS 會唸成中文），所以數字可以精確比對。
# 唯一要處理的是千分位逗號：投影片寫 3,130，旁白寫 3130。


def unspell(t):
    """旁白把縮寫拆成單字母（`N B L A S T`）才唸得對，比對前要先還原。
    不還原的話，投影片上的 NBLAST、cells_only 會被誤報成「旁白沒講」。"""
    for a, b in FIX:
        t = t.replace(a, b)
    return t


def plain(t):
    return re.sub(r"[\s，。、：；！？「」（）《》%．·—…]", "", re.sub(r"<[^>]+>", "", t))


def num_in(num, say):
    """投影片上的數字，旁白有沒有講到（去掉千分位與空白後比對）。"""
    return num.replace(",", "") in say.replace(",", "").replace(" ", "")


def main():
    total = miss_n = miss_w = 0
    for i, s in enumerate(SLIDES, 1):
        say, bad_n, bad_w = plain(unspell(s["say"])), [], []
        for b in s["bullets"]:
            for num in re.findall(r"\d[\d,]*(?:\.\d+)?%?", re.sub(r"<[^>]+>", "", b)):
                total += 1
                if not num_in(num, unspell(s["say"])):
                    bad_n.append(num)
            # 關鍵詞只當「提示」：旁白是完整句子，用字不會跟要點一模一樣，
            # 所以這裡只挑「帶英數的專有名詞」比對，避免整段誤報。
            for w in re.findall(r"<b>(.*?)</b>", b):
                w = plain(w)
                if re.fullmatch(r"[A-Za-z0-9_\-\.％%]{3,}", w) and w not in say:
                    bad_w.append(w)
        if bad_n or bad_w:
            print(f"投影片 {i:>2}　{plain(s['title'])[:24]}")
            if bad_n:
                print(f"     旁白沒講的數字：{'、'.join(sorted(set(bad_n)))}")
                miss_n += len(set(bad_n))
            if bad_w:
                print(f"     旁白沒涵蓋的關鍵詞：{'｜'.join(sorted(set(bad_w)))}")
                miss_w += len(set(bad_w))
    chars = sum(len(s["say"]) for s in SLIDES)
    print(f"\n{len(SLIDES)} 張投影片　旁白 {chars:,} 字 → 約 {chars / 4.44 / 60:.1f} 分鐘")
    print(f"數字漏講 {miss_n} 個（共 {total} 個）　專有名詞漏講 {miss_w} 個")
    return 1 if (miss_n or miss_w) else 0


if __name__ == "__main__":
    sys.exit(main())
