#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
案例卡五要素·结构层 · case_relabel.py

用户定调（2026-09-16）：每张卡要「加上 ① 是什麼 ② 為什麼 ③ 做了什麼 ④ 怎麼做 ⑤ 效果」，
且是**在现有内容上添加**（原文不删）。

本脚本做**机械结构层**（不编造任何内容）：
  ① 是什麼   ← 由卡标题「品牌｜角度（年份）」推导一行
  ② 為什麼   ← 把「解決了什麼問題／當時的問題/目標 (及變體)」改名为 ②
  ③ 做了什麼 ← 有「做了什麼」就改名；否则插一行「见④的 N 步」指针
  ④ 怎麼做   ← 把「具體做了什麼／具體動作」改名为 ④
  ⑤ 效果     ← 把「結果／得到了什麼結果」改名为 ⑤
已存在的标签一律不动；原文一字不删。

用法：
    python scripts/case_relabel.py --dry-run     # 预览会改什么
    python scripts/case_relabel.py --apply
退出码：0 正常；2 出错
"""

import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")

WHY_SRC = ["解決了什麼問題", "当时的问题/目标", "當時的問題/目標", "問題/目標", "问题/目标", "為什麼", "为什么"]
HOW_SRC = ["具體做了什麼", "具体做了什么", "具體動作"]
DID_SRC = ["做了什麼", "做了什么"]
EFF_SRC = ["得到了什麼結果", "结果", "結果", "效果"]

L1, L2, L3, L4, L5 = "① 是什麼", "② 為什麼", "③ 做了什麼", "④ 怎麼做", "⑤ 效果"


def has(seg, *labels):
    return any(x in seg for x in labels)


def process(path, apply):
    t = open(path, encoding="utf-8").read()
    out, changed = [], 0
    lines = t.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = re.match(r"^###\s+(\d+\.\d+)\s+(.+?)\s*$", ln)
        if not m:
            out.append(ln); i += 1; continue
        # 收集本卡整段
        j = i + 1
        while j < len(lines) and not re.match(r"^#{1,3}\s", lines[j]):
            j += 1
        seg = lines[i:j]
        body = "\n".join(seg)
        title = m.group(2)
        ins = []
        # ① 是什麼（缺才插）
        if not has(body, L1, "①是什麼"):
            parts = re.split(r"[｜|]", title)
            brand = parts[0].strip()
            angle = parts[1].strip() if len(parts) > 1 else title
            angle = re.sub(r"（[^）]*）\s*$", "", angle).strip()
            ins.append(f"- **{L1}**：{brand} —— {angle}")
        # ②③④⑤ 改名（缺才改）
        for k, ln2 in enumerate(seg):
            if re.match(r"^\s*-\s*\*\*", ln2):
                name = re.match(r"^\s*-\s*\*\*(.+?)\*\*", ln2).group(1).strip("：: ")
                if not has(body, L2) and any(s in name for s in WHY_SRC):
                    seg[k] = ln2.replace(f"**{name}**", f"**{L2}**", 1); changed += 1
                elif not has(body, L4) and any(s in name for s in HOW_SRC):
                    seg[k] = ln2.replace(f"**{name}**", f"**{L4}**", 1); changed += 1
                elif not has(body, L5) and any(s in name for s in EFF_SRC):
                    seg[k] = ln2.replace(f"**{name}**", f"**{L5}**", 1); changed += 1
                elif not has(body, L3) and any(s in name for s in DID_SRC):
                    seg[k] = ln2.replace(f"**{name}**", f"**{L3}**", 1); changed += 1
        body2 = "\n".join(seg)
        # ③ 仍缺 → 插指针
        if not has(body2, L3):
            nhow = len(re.findall(r"(?m)^\s{2,}\d+[.、]", body2))
            ins.append(f"- **{L3}**：共 {nhow} 件事，分步做法见下方「{L4}」" if nhow else f"- **{L3}**：（本卡未展開，詳見下）")
        # 插到标题后的第一个空行之后（保留原有 > 引言在最上面）
        k = 1
        while k < len(seg) and (seg[k].startswith(">") or not seg[k].strip()):
            k += 1
        seg = seg[:k] + ins + [""] + seg[k:]
        if ins or changed:
            changed += len(ins)
        out.extend(seg)
        i = j
    if apply and changed:
        open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not (a.apply or a.dry_run):
        a.dry_run = True
    def _num(fp):
        m = re.match(r"(\d+)", os.path.basename(fp))
        return int(m.group(1)) if m else 999  # 非編號檔（README.md 等）一律排除

    files = [f for f in sorted(glob.glob(os.path.join(ROOT, "references", "cases", "*.md")))
             if _num(f) <= 50]
    tot = 0
    for f in files:
        n = process(f, a.apply)
        tot += n
        if a.dry_run and n:
            print(f"  {os.path.basename(f)}: {n} 处")
    print("-" * 56)
    print(f"{'APPLY 完成' if a.apply else 'DRY-RUN'}：{tot} 处改动")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ {type(e).__name__}: {e}")
        sys.exit(2)
