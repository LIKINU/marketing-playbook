#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫出案例档的断句损坏行（打印完整行，便于写精准修复）"""
import re, sys, glob, os

import os as _os
R = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "references", "cases")
CJK = r"[\u4e00-\u9fff]"
PATS = [
    ("粗体后缺冒号", re.compile(r"\*\*[^*\n]{2,26}\*\*(?=" + CJK + r")")),
    ("句尾被截", re.compile(r"^[\s\-0-9.*]*[^\s。！？：）】\"」]$")),
    ("括号不成对", re.compile(r"(【[^】\n]*$)|(^[^【\n]*】)")),
    ("替代符残留", re.compile(r"…|\.\.\.|<<|>>")),
]
for pat in sys.argv[1].split(","):
    fp = glob.glob(f"{R}/{pat}-*.md")
    if not fp:
        print("!! 找不到", pat); continue
    fp = fp[0]
    print("=" * 90)
    print("###", os.path.basename(fp))
    lines = open(fp, encoding="utf-8").read().split("\n")
    for i, l in enumerate(lines, 1):
        s = l.rstrip()
        if not s or set(s) <= set("-*"):
            continue
        hits = []
        for name, p in PATS:
            if name == "句尾被截":
                if len(s) > 34 and s.startswith(("- **", "  - ", "  ", "*")) and not s.endswith(
                        ("。", "：", "！", "？", "】", "）", "\"", "」", "—")):
                    hits.append(name)
            elif p.search(s):
                hits.append(name)
        # 粗体计数为奇数
        if s.count("**") % 2 == 1:
            hits.append("粗体不成对")
        if hits:
            print(f"L{i} [{'/'.join(sorted(set(hits)))}] {s}")
