#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""案例卡精简摘要 · 只印写 ②/洞察/花了多少/适配/常见错误/本档关联 所需的骨干"""
import re, sys, glob, os

def blocks(text):
    heads = list(re.finditer(r"(?m)^###\s+(\d+\.\d+)\s", text))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        nxt = re.search(r"(?m)^##\s", text[m.end():end])
        if nxt:
            end = m.end() + nxt.start()
        out.append((m.group(1), text[m.start():end]))
    return out

CUT = int(sys.argv[2]) if len(sys.argv) > 2 else 170
import os as _os
R = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "references", "cases")
for pat in sys.argv[1].split(","):
    fp = glob.glob(f"{R}/{pat}-*.md")
    if not fp:
        print("!! 找不到", pat); continue
    fp = fp[0]
    t = open(fp, encoding="utf-8").read()
    print("=" * 96)
    print("###", os.path.basename(fp), f"（{len(t)} 字）")
    for cid, b in blocks(t):
        lines = b.split("\n")
        print(f"\n--- §{cid} {lines[0][4:80]}")
        for l in lines:
            s = l.strip()
            if not s or s == "---":
                continue
            if re.match(r"^- \*\*(① 是什么|谁做的|② 为什么|洞察|③ 做了什么|④ 怎么做|花了多少|⑤ 效果)", s):
                print("  " + (s if len(s) <= CUT else s[:CUT] + "…"))
            elif re.match(r"^(  - |  \d+\. |\d+\. |  - \*\*)", l) and len(s) > 4:
                print("  " + (s if len(s) <= CUT else s[:CUT] + "…"))
