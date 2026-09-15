#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_meta.py — 量這一包自己：行數、註解比例、換一個參數會怎樣、以及乾淨重跑驗證。

**這一支存在的理由是一次違規。** run_meta.json 原本是用臨時腳本產的，
沒有任何程式會重新產生它——於是 recompute.py 一長，PART 9 頁面上的
「534 行／793 行／152 行註解」就悄悄過期，而稽核看不出來（數字還在某個檔案裡）。
「要放上頁面的東西，產它的程式就得留著」這條規矩，這個檔案自己犯過一次。

**它寫到 ../out/recompute/run_meta.json，不寫進 recompute/out/。**
這一份是課程對這一包的量測紀錄，不是這一包自己的產出——
描述某個 zip 的檔案不能住在那個 zip 裡面，否則它永遠差一版。

跑法：
    python3 run_meta.py                                       # 只量程式，約 70 秒
    python3 run_meta.py --zip ../downloads/vfb-recompute.zip   # 連乾淨重跑一起，約 4 分鐘

不給 --zip 時 clean_run 會寫成 null，**不會留下上一次的舊值**——
乾淨重跑是對某一個 zip 的宣稱，沒驗就不該有數字。
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import tokenize
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
DEST = HERE.parent / "out" / "recompute" / "run_meta.json"

# 交付的那一包裡的東西。run_meta.py 自己不在裡面，所以不算進行數。
SHIPPED_PY = ["recompute.py", "make_figure.py", "cross_check.py"]
SHIPPED_OTHER = ["README.md"]

# 重跑之後要逐位元組比對的產出。fetched_at.txt 含時間戳，scatter.png 是
# matplotlib 產的二進位檔，兩個都不比。
SKIP_WHEN_COMPARING = {"fetched_at.txt", "cross_check_at.txt",
                       "run_meta.json", "scatter.png"}


def count_lines() -> tuple[dict, dict]:
    """行數，以及其中有多少行是註解或說明字串。

    不數 `#` 開頭的行就算了事：docstring 是字串不是註解，
    而一份研究用程式的說明有一大半寫在 docstring 裡。
    **兩者要用不同的工具抓**——註解用 tokenize，docstring 用 ast。
    """
    files = {f: len((HERE / f).read_text("utf-8").splitlines())
             for f in SHIPPED_PY + SHIPPED_OTHER}
    marked = 0
    for f in SHIPPED_PY:
        src = (HERE / f).read_text("utf-8")
        lines = set()
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                lines.add(tok.start[0])
        # **docstring 要用 ast 抓，不能用 tokenize 抓「獨佔一行的字串」**——
        # 這支程式滿是跨行的 Cypher 查詢字串，那些是程式不是說明，
        # 用後者會多數出一倍（實測 310 行 vs 156 行）。
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                lines.update(range(body[0].lineno, body[0].end_lineno + 1))
        marked += len(lines)
    total = sum(files[f] for f in SHIPPED_PY)
    return files, {
        "total_py": total,
        "comment_or_docstring": marked,
        "pct": round(marked / total * 100),
        "how": "COMMENT 用 tokenize 數、docstring 用 ast 抓（跨行的查詢字串不算）；"
               f"{len(SHIPPED_PY)} 支 .py 合計，不含 README.md，"
               "也不含 run_meta.py（它不在交付的那一包裡）"}


def match_key_variant() -> dict:
    """把 PARAMS['match_key'] 換成 class，其餘不動，重跑一次。

    這一組數字是 PART 9 第 2 節那張表的內容——**一個參數把結論從 732 改成 535**。
    在同一個行程裡改 PARAMS 再呼叫同樣三支函式，跟改檔案重跑等價
    （比對那一段每次都讀 PARAMS，沒有快取）。
    """
    sys.path.insert(0, str(HERE))
    import recompute as R

    R.PARAMS["match_key"] = "class"
    target = R.paper_target()
    vfb = R.vfb_side()
    cmp = R.compare(target, vfb)
    return {
        "what": "把 PARAMS['match_key'] 從 instance 改成 class，其餘不動，重跑一次的結果",
        "why": "用來示範一個參數會把結論改成什麼樣子",
        "matched": cmp["matched"],
        "same_count": cmp["same_count"],
        "different_count": cmp["different_count"],
        "delta_max": cmp["delta_max"],
        "total_cells_paper": cmp["total_cells_paper"],
        "total_cells_vfb": cmp["total_cells_vfb"],
        "only_in_paper": len(cmp["only_in_paper"]),
        "only_in_vfb": len(cmp["only_in_vfb"])}


def clean_run(zip_path: Path) -> dict:
    """把交付的那一包解到一個空資料夾、刪掉 out/、重跑，再跟原本的產出逐位元組比。

    **這是 PART 9 第 6 節第 5 問自己在防的那件事**：臨時腳本查完即丟、
    產物卻留在 out/ 裡，乾淨重跑就會少東西。只有真的解開重跑才驗得到。
    """
    with tempfile.TemporaryDirectory() as td:
        work = Path(td) / "pkg"
        work.mkdir()
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            z.extractall(work)
        shutil.rmtree(work / "out", ignore_errors=True)

        def run(*cmd):
            t = time.time()
            r = subprocess.run([sys.executable, *cmd], cwd=work,
                               capture_output=True, text=True)
            if r.returncode:
                raise SystemExit(f"乾淨重跑失敗：{cmd}\n{r.stdout}\n{r.stderr}")
            return time.time() - t

        secs_main = run("recompute.py") + run("make_figure.py")
        secs_cross = run("cross_check.py")

        same, differ = [], []
        for f in sorted((work / "out").glob("*")):
            if f.name in SKIP_WHEN_COMPARING:
                continue
            orig = OUT / f.name
            if not orig.exists():
                differ.append(f"{f.name}（原本沒有這個檔）")
            elif orig.read_bytes() == f.read_bytes():
                same.append(f.name)
            else:
                differ.append(f.name)

        # 原本 out/ 裡有、重跑卻沒產出來的 —— 就是「臨時腳本留下的產物」
        orphans = sorted(p.name for p in OUT.glob("*")
                         if p.name not in SKIP_WHEN_COMPARING
                         and not (work / "out" / p.name).exists())

    return {
        "where": f"把 {zip_path.name} 解到一個空資料夾、刪掉 out/ 之後重跑",
        "zip_contains": len(names),
        "recompute_plus_figure_seconds": round(secs_main),
        "cross_check_seconds": round(secs_cross),
        "outputs_identical_to_original": not differ and not orphans,
        "identical_files": same,
        "differing_files": differ,
        "not_regenerated": orphans}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zip", type=Path, default=None,
                    help="交付的那一包；給了才做乾淨重跑")
    args = ap.parse_args()

    print("① 量行數…")
    files, code_lines = count_lines()
    print(f"   {files}　註解或說明 {code_lines['comment_or_docstring']} 行"
          f"（{code_lines['pct']}%）")

    print("② 換一個參數重跑（match_key=class）…")
    variant = match_key_variant()
    print(f"   對得上 {variant['matched']}　顆數相同 {variant['same_count']}")

    if args.zip:
        print("③ 乾淨重跑…")
        clean = clean_run(args.zip)
        print(f"   {clean['recompute_plus_figure_seconds']} 秒 ＋ "
              f"{clean['cross_check_seconds']} 秒　"
              f"產出一致：{clean['outputs_identical_to_original']}")
        if clean["not_regenerated"]:
            print(f"   ⚠ 重跑沒產生出來的檔案：{clean['not_regenerated']}")
    else:
        print("③ 乾淨重跑：略過（沒給 --zip）")
        clean = None

    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps({
        "what": "PART 8 那一輪實跑的環境與計時。由 recompute/run_meta.py 產生。",
        "files": files,
        "clean_run": clean,
        "dependencies": ["openpyxl", "matplotlib"],
        "python": f"Python {platform.python_version()}",
        "match_key_class_variant": variant,
        "code_lines": code_lines,
    }, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(f"→ {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
