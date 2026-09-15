#!/usr/bin/env python3
"""產生首頁那支約 10 分鐘的說明影片。

   內容在 video_slides.py（投影片要點＋旁白稿），這支只負責產出：
     1. 每張投影片用 headless Chrome 截成 1920×1080 的 PNG
     2. 每段旁白用 edge-tts 合成（zh-TW-HsiaoChenNeural，語速 -8%）
     3. 依各段長度把 PNG 排成影像軌，與音軌一起用 ffmpeg 合成 MP4
     4. 依各段長度切出 WebVTT 字幕

   改了投影片或旁白就重跑：  python3 scripts/make_video.py
   產出：assets/vfb-overview.mp4、assets/vfb-overview.vtt、assets/poster.jpg

   **旁白有兩種來源，看 _voice/ 在不在：**
     · `_voice/ref.wav` ＋ `_voice/ref.txt` 存在 → 用 F5-TTS 克隆那個聲音，
       全程在本機 GPU 上跑，稿子不離開這台機器。
       要用這條路得跑 venv 裡的 python：
           ~/.venvs/tts/bin/python scripts/make_video.py
     · 不存在 → 退回 edge-tts（微軟的語音服務，會把旁白文字送出去）。

   **`_voice/` 不進版控**（.gitignore）——那是本人的聲音樣本，
   不該躺在一個公開 repo 裡。要重跑的人自己放一段自己的。

   **克隆的三個實測教訓**（2026-09-15）：
     1. 參考片段的**頭尾都要落在停頓處**，否則最後幾個字會漏進合成音
        （用 ffmpeg 的 silencedetect 找，不要用 whisper 的詞級時間戳——它幾乎沒有間隙）。
     2. 合成速度跟著參考片段走。同一個人「邊想邊講」是 2.47 字/秒、
        「照稿唸」是 3.99 字/秒——**樣本要用照稿唸的**，否則影片會長一倍。
     3. **字母 V 唸不出來、四個以上的字母串會糊掉**（V F B → dfb、N B L A S T → 論幣咬AST）。
        M C P、R E S T、A P I、F B b t 沒問題。所以旁白改用中文說法，
        投影片照舊寫原名。`J R C 二零一八 Unisex` 可以（寫 2018 反而會掉字）。
"""
import io, os, re, json, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from video_slides import SLIDES          # noqa: E402

ROOT = os.path.dirname(HERE)
WORK = os.path.join(ROOT, "_video")      # 中間檔，不進 repo（.gitignore）
OUT = os.path.join(ROOT, "assets")
VOICE, RATE, PAD = "zh-TW-HsiaoChenNeural", "-8%", 0.6
REF_WAV = os.path.join(os.path.dirname(HERE), "_voice", "ref.wav")
REF_TXT = os.path.join(os.path.dirname(HERE), "_voice", "ref.txt")
CLONE = os.path.exists(REF_WAV) and os.path.exists(REF_TXT)
# 旁白裡為了讓 TTS 逐字母唸而加的空白，字幕要還原回去。
# **長的要排在前面**，否則 "A I" 會先把 "N B L A S T" 咬掉一段。
FIX = [("J R C 二零一八 Unisex", "JRC2018Unisex"), ("v 1.0.1", "v1.0.1"), ("v 1.1", "v1.1"),
       ("N B L A S T", "NBLAST"), ("F B b t", "FBbt"), ("B A N C", "BANC"),
       ("M E 底線 R", "ME_R"), ("M E 括號 R", "ME(R)"),
       ("vfb connect", "vfb-connect"), ("cells only", "cells_only"),
       ("is data source", "is_data_source"),
       ("B S C", "BSC"), ("V F B", "VFB"), ("M C P", "MCP"),
       ("R E S T", "REST"), ("A P I", "API"), ("A I", "AI")]

CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{width:1920px;height:1080px;background:#fbfcfd;font:400 17px/1.7 "Noto Sans CJK TC","Noto Sans TC",sans-serif;color:#1b2733;overflow:hidden}
.bar{height:10px;background:linear-gradient(90deg,#2563eb 0%,#7c3aed 55%,#d97706 100%)}
.wrap{padding:56px 84px 0;height:1070px;display:flex;flex-direction:column}
.eyebrow{color:#2563eb;font-weight:700;font-size:24px;letter-spacing:.12em;text-transform:uppercase;margin-bottom:14px}
h1{font-size:58px;line-height:1.28;font-weight:700;letter-spacing:-.01em}
h1 b{color:#2563eb}
.body{display:flex;gap:60px;margin-top:40px;flex:1;min-height:0}
.col{flex:1;min-width:0}
ul{list-style:none}
li{position:relative;padding-left:40px;margin-bottom:26px;font-size:31px;line-height:1.62;color:#2b3a48}
li:before{content:"";position:absolute;left:0;top:18px;width:20px;height:5px;border-radius:3px;background:#2563eb}
li b{color:#0f1b26;font-weight:700}
.fig{flex:0 0 720px;display:flex;flex-direction:column;justify-content:center}
.fig img{width:100%;max-height:700px;object-fit:contain;border:1px solid #e4e8ee;border-radius:14px;background:#fff}
.cap{font-size:19px;color:#7a8794;margin-top:14px;line-height:1.6}
.full li{font-size:34px}
.foot{display:flex;justify-content:space-between;align-items:center;padding:22px 0 26px;color:#9aa7b4;font-size:19px;border-top:1px solid #e8ecf1;margin-top:auto}
.pg{font-variant-numeric:tabular-nums}
"""


def slide_html(s, i, n):
    fig = (f'<div class="fig"><img src="file://{s["img"]}">'
           f'<div class="cap">{s["imgcap"]}</div></div>') if s["img"] else ""
    return (f'<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<style>{CSS}</style></head><body><div class="bar"></div><div class="wrap">'
            f'<div class="eyebrow">{s["eyebrow"]}</div><h1>{s["title"]}</h1>'
            f'<div class="body"><div class="{"col" if s["img"] else "col full"}">'
            f'<ul>{"".join(f"<li>{b}</li>" for b in s["bullets"])}</ul></div>{fig}</div>'
            f'<div class="foot"><div>BSC 腦空間體研究中心 · 專題課程 VFB　｜　marginli.github.io/bsc-vfb</div>'
            f'<div class="pg">{i + 1} / {n}</div></div></div></body></html>')



# ══════════════════════════════════════════════════════════════════
# 克隆模型唸不出阿拉伯數字：471 會變成「for 71」、884 變成「N84」、
# 62 變成「Cinti2」。改成國字就完全正確（實測）。
# **稿子裡仍然寫阿拉伯數字**——字幕、video_check、頁面對照全靠它；
# 只在送進 TTS 之前轉一次。edge-tts 不需要這一步。
# ══════════════════════════════════════════════════════════════════
_D = "零一二三四五六七八九"
_U = ["", "十", "百", "千"]


def _card(n: int) -> str:
    """基數讀法：471 → 四百七十一、80003 → 八萬零三、52827 → 五萬二千八百二十七。"""
    if n == 0:
        return "零"
    if n >= 10 ** 8:
        return "".join(_D[int(c)] for c in str(n))      # 太大就逐字唸
    out = ""
    for unit, name in ((10 ** 4, "萬"),):
        if n >= unit:
            out += _card(n // unit) + name
            n %= unit
            if n == 0:
                return out
            if n < unit // 10:
                out += "零"
    s4 = str(n)
    for i, c in enumerate(s4):
        d, u = int(c), _U[len(s4) - 1 - i]
        if d == 0:
            if not out.endswith("零") and i != len(s4) - 1:
                out += "零"
        else:
            out += _D[d] + u
    out = out.rstrip("零") or "零"
    # 中文說「十」不說「一十」（只在整個數字的開頭；一百一十的「一十」要留著）
    return out[1:] if out.startswith("一十") else out


# 克隆模型跟 edge-tts 相反：**短縮寫不要拆字母**。
#   M C P → 「MACP」、V F B → 「dfb」；不拆反而正確（MCP、API、REST 實測都對）。
# 長一點的還是不行（NBLAST 拆不拆都糊），那些已經在稿子裡改成中文說法了。
UNSPACE = ["A I", "A P I", "M C P", "R E S T", "B S C", "V F B", "F B b t", "B A N C"]


def unspace(t: str) -> str:
    for w in UNSPACE:
        t = t.replace(w, w.replace(" ", ""))
    return t


def zh_num(t: str) -> str:
    """把旁白裡的阿拉伯數字換成國字。年份逐字唸，其餘照基數讀法。"""
    t = re.sub(r"(\d{4})\s*年",
               lambda m: "".join(_D[int(c)] for c in m.group(1)) + "年", t)
    t = re.sub(r"(\d[\d,]*)(?:\.(\d+))?\s*%",
               lambda m: "百分之" + _card(int(m.group(1).replace(",", "")))
               + ("點" + "".join(_D[int(c)] for c in m.group(2)) if m.group(2) else ""), t)
    # 版本號之類的多段小數（1.0.1）逐字唸
    t = re.sub(r"(?<![\d.])(\d+)\.(\d+)\.(\d+)(?![\d.])",
               lambda m: "點".join("".join(_D[int(c)] for c in g) for g in m.groups()), t)
    t = re.sub(r"(?<![\d.])(\d[\d,]*)\.(\d+)(?![\d.])",
               lambda m: _card(int(m.group(1).replace(",", "")))
               + "點" + "".join(_D[int(c)] for c in m.group(2)), t)
    t = re.sub(r"(?<![\d.])(\d[\d,]*)(?![\d.])",
               lambda m: _card(int(m.group(0).replace(",", ""))), t)
    return t


def ts(t):
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:06.3f}"


def tts_clone():
    """F5-TTS：模型只載入一次，15 段共用（每段各開一次 CLI 要多花十幾分鐘）。"""
    from f5_tts.api import F5TTS
    return F5TTS(model="F5TTS_v1_Base")


def main():
    os.makedirs(f"{WORK}/png", exist_ok=True)
    os.makedirs(f"{WORK}/aud", exist_ok=True)
    tts = tts_clone() if CLONE else None
    ref_text = io.open(REF_TXT, encoding="utf-8").read().strip() if CLONE else ""
    print(f"旁白來源：{'本機克隆（F5-TTS）' if CLONE else 'edge-tts（微軟）'}")
    durs = []
    for i, s in enumerate(SLIDES):
        p = f"{WORK}/s{i:02d}.html"
        io.open(p, "w", encoding="utf-8").write(slide_html(s, i, len(SLIDES)))
        subprocess.run(["google-chrome", "--headless=new", "--disable-gpu", "--no-sandbox",
                        "--hide-scrollbars", "--window-size=1920,1080", "--virtual-time-budget=3000",
                        f"--screenshot={WORK}/png/s{i:02d}.png", f"file://{p}"], capture_output=True)
        a = f"{WORK}/aud/a{i:02d}." + ("wav" if CLONE else "mp3")
        if not os.path.exists(a):
            if CLONE:
                tts.infer(ref_file=REF_WAV, ref_text=ref_text,
                          gen_text=unspace(zh_num(s["say"])), file_wave=a,
                          remove_silence=False)
            else:
                subprocess.run(["edge-tts", "--voice", VOICE, f"--rate={RATE}",
                                "--text", s["say"], "--write-media", a],
                               capture_output=True, timeout=300)
        durs.append(float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a],
            capture_output=True, text=True).stdout.strip()))
        print(f"   投影片 {i + 1}/{len(SLIDES)}　旁白 {durs[-1]:.1f} 秒")

    with io.open(f"{WORK}/ca.txt", "w") as f:
        for i in range(len(durs)):
            f.write(f"file 'aud/a{i:02d}.{'wav' if CLONE else 'mp3'}'\n")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", f"{WORK}/ca.txt",
                    "-af", f"apad=pad_dur={PAD}", "-c:a", "aac", "-b:a", "128k",
                    f"{WORK}/voice.m4a"], capture_output=True, cwd=WORK)
    with io.open(f"{WORK}/cv.txt", "w") as f:
        for i, d in enumerate(durs):
            f.write(f"file 'png/s{i:02d}.png'\nduration {d + PAD:.3f}\n")
        f.write(f"file 'png/s{len(durs) - 1:02d}.png'\n")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", f"{WORK}/cv.txt",
                    "-i", f"{WORK}/voice.m4a", "-c:v", "libopenh264", "-b:v", "900k",
                    "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", "24", "-c:a", "copy",
                    "-shortest", "-movflags", "+faststart", f"{OUT}/vfb-overview.mp4"],
                   capture_output=True, cwd=WORK)

    vtt, t = ["WEBVTT", ""], 0.0
    for s, d in zip(SLIDES, durs):
        sents = [x for x in re.split(r"(?<=[。！？])", s["say"]) if x.strip()]
        tot, cur = sum(len(x) for x in sents), t
        for x in sents:
            dur = d * len(x) / tot
            for a, b in FIX:
                x = x.replace(a, b)
            vtt += [f"{ts(cur)} --> {ts(cur + dur)}", x.strip(), ""]
            cur += dur
        t += d + PAD
    io.open(f"{OUT}/vfb-overview.vtt", "w", encoding="utf-8").write("\n".join(vtt))
    # **影片本身的數字也是數字**（規範第 4 節那條「拿產物當數據」）：
    # 秒數、張數、解析度、檔案大小都寫進 out/，首頁上的那幾個才對得回探針。
    import json
    # **量成品，不要用音軌加總**：ffmpeg 的 -shortest 會讓 mp4 比加總短幾秒，
    # 而頁面上寫的是讀者實際看到的長度。
    total = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", f"{OUT}/vfb-overview.mp4"],
        capture_output=True, text=True).stdout.strip())
    io.open(os.path.join(ROOT, "out", "video_meta.json"), "w", encoding="utf-8").write(
        json.dumps({
            "probe": "video_meta",
            "what": "首頁那支說明影片的規格；由 scripts/make_video.py 在產生影片時一併寫出",
            "file": "assets/vfb-overview.mp4",
            "slides": len(SLIDES),
            "seconds": round(total, 1),
            "mm": int(total // 60), "ss": round(total % 60),
            "width": 1920, "height": 1080, "resolution": "1080p", "fps": 24,
            "say_chars": sum(len(s["say"]) for s in SLIDES),
            "voice": ("F5-TTS 克隆（本機）" if CLONE else VOICE),
            "rate": ("參考片段的自然語速" if CLONE else RATE),
            "mb": round(os.path.getsize(f"{OUT}/vfb-overview.mp4") / 2**20, 1),
        }, ensure_ascii=False, indent=1) + "\n")

    from PIL import Image
    Image.open(f"{WORK}/png/s00.png").convert("RGB").save(f"{OUT}/poster.jpg", quality=86, optimize=True)
    print(f"\n完成：{sum(durs) + len(durs) * PAD:.0f} 秒，"
          f"{os.path.getsize(f'{OUT}/vfb-overview.mp4') / 2**20:.1f} MB")


if __name__ == "__main__":
    main()
