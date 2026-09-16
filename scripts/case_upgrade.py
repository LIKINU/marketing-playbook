#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
案例卡升级校验 · case_upgrade.py

目标（用户 2026-09-16 定）：全 620 张深度卡统一为**五要素**并在现有基础上补全：
    ① 是什麼  ② 為什麼（問題/目標）  ③ 做了什麼  ④ 怎麼做  ⑤ 效果
+ 目标篇幅 ≥2500 字（详细版）；效果查不到的写「未披露」，不编造。

本脚本把「五要素齐不齐、字数够不够」变成机械可查（模型不会看文字规则）。

用法：
    python scripts/case_upgrade.py                 # 全库体检 + 进度
    python scripts/case_upgrade.py --list          # 列出未达标的卡
    python scripts/case_upgrade.py --file 01       # 只看某行业档
    python scripts/case_upgrade.py --min 2500
退出码：0 = 全部达标；1 = 有未达标
"""

import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")

ELEM = {
    "① 是什麼": ["① 是什麼", "①是什麼", "是什麼", "是什麼："],
    "② 為什麼": ["② 為什麼", "②為什麼", "為什麼", "當時的問題", "問題/目標", "當時的問題/目標"],
    "③ 做了什麼": ["③ 做了什麼", "③做了什麼", "做了什麼", "具體做了什麼"],
    "④ 怎麼做": ["④ 怎麼做", "④怎麼做", "怎麼做"],
    "⑤ 效果": ["⑤ 效果", "⑤效果", "效果", "結果"],
}


def cards(path):
    t = open(path, encoding="utf-8").read()
    # 非案例卡：標題含「專節／清單／總表／速查」的是參考頁，不按五要素考核
    NON_CASE = ("專節", "清單", "總表", "速查", "對照表", "對照（", "必讀")
    for m in re.finditer(r"(?m)^###\s+(\d+\.\d+)\s+(.+)$", t):
        if any(k in m.group(2) for k in NON_CASE):
            continue
        seg = t[m.end():]
        nxt = re.search(r"(?m)^#{1,3}\s", seg)
        yield m.group(1), m.group(2)[:34], (seg[:nxt.start()] if nxt else seg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=2500)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--file", default="")
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(ROOT, "references", "cases", "*.md")))
    def _num(fp):
        m = re.match(r"(\d+)", os.path.basename(fp))
        return int(m.group(1)) if m else 999  # 非編號檔（README.md 等）一律排除
    files = [f for f in files if _num(f) <= 45]
    if a.file:
        files = [f for f in files if os.path.basename(f).startswith(a.file)]

    total = ok = 0
    fails = []
    for f in files:
        cnt = file_ok = 0
        for cid, title, seg in cards(f):
            cnt += 1
            total += 1
            miss = [k for k, alts in ELEM.items() if not any(x in seg for x in alts)]
            short = len(seg) < a.min
            if not miss and not short:
                ok += 1
                file_ok += 1
            else:
                fails.append((os.path.basename(f), cid, title, ",".join(miss), len(seg)))
        bar = "▉" * int(10 * file_ok / cnt) if cnt else ""
        print(f"  {bar:<10} {file_ok:>3}/{cnt:<3} {os.path.basename(f)}")

    print("-" * 60)
    print(f"达标 {ok}/{total}（{ok/total:.1%}）｜目标：五要素齐 ＋ ≥{a.min} 字")
    if a.list and fails:
        print(f"\n未达标卡（{len(fails)}）:")
        for fn, cid, title, miss, ln in fails[:80]:
            print(f"  {fn[:18]} §{cid} {title} ｜缺:{miss or '-'}｜{ln}字")
    sys.exit(0 if ok == total else 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ {type(e).__name__}: {e}")
        sys.exit(2)
