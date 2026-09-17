#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
案例卡「要素顺序」规范化 · case_order.py

背景（2026-09-16）：
  历次批量改造（relabel / clean / 手工改写）会把要素行搬乱——
  典型症状：③ 跑到 ② 前面、③ 掉到卡片最后、谁做的／洞察 散了、标题换行被吞（`---### 3.2`）。
  本脚本把「卡片内部要素顺序」变成机械可查、可修复，且**保证不丢内容**。

规范顺序（每张深度卡）：
  ① 是什么 → 谁做的 → ② 为什么 → 洞察 → ③ 做了什么 → ④ 怎么做
  → 落地拆解 → 花了多少 → ⑤ 效果 → 可抄的点
  → 适配不同规模客户 → 常见错误 → 本档关联 → 没解决的问题 / 局限
  （未列出的区块一律排到最后，保持原有相对顺序）

安全保证（硬不变式，任一不过就放弃写入该档）：
  1. 非空行集合（multiset）完全一致 —— 只许改顺序与空行，不许删内容
  2. `### N.M` 标题数 == ① 出现数
  3. ① ② ③ ④ ⑤ 各自出现次数不变

用法：
    python scripts/case_order.py            # 只体检（列出顺序异常的卡）
    python scripts/case_order.py --fix      # 修复（带不变式校验，失败自动放弃）
    python scripts/case_order.py --fix --file 02
退出码：0 = 无异常；1 = 有异常（--fix 时为修复失败）
"""

import argparse
import collections
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")

# 规范顺序（数字越小越前）
RANK = [
    ("① 是什么", 10),
    ("谁做的", 15),
    ("② 为什么", 20),
    ("洞察", 25),
    ("③ 做了什么", 30),
    ("④ 怎么做", 40),
    ("落地拆解", 45),
    ("花了多少", 48),
    ("⑤ 效果", 50),
    ("可抄的点", 60),
    ("适配不同规模客户", 70),
    ("常见错误", 75),
    ("本档关联", 80),
    ("没解决的问题", 90),
]
RANK_OTHER = 200

RE_HEAD = re.compile(r"(?m)^###\s+\d+\.\d+\s")
RE_TOP = re.compile(r"^- \*\*(.+?)\*\*")
RE_ELEM = re.compile(r"(?m)^- \*\*([①②③④⑤]) ")
ELEM_NUM = {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5}


def files(only=""):
    fs = sorted(glob.glob(os.path.join(ROOT, "references", "cases", "*.md")))
    fs = [f for f in fs if re.match(r"\d+", os.path.basename(f))]  # 排除 README.md 等
    if only:
        fs = [f for f in fs if os.path.basename(f).startswith(only)]
    return fs


def cards(text):
    """产出 (卡号, 卡片全文)。卡片 = ### N.M 起，到下一张卡或 ## 章节为止。"""
    heads = list(re.finditer(r"(?m)^###\s+(\d+\.\d+)\s", text))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        nxt = re.search(r"(?m)^##\s", text[m.end():end])
        if nxt:
            end = m.end() + nxt.start()
        yield m.group(1), text[m.start():end]


def order_of(block):
    return [c for c in re.findall(r"(?m)^- \*\*([①②③④⑤]) ", block)]


def is_disordered(block):
    o = order_of(block)
    return [ELEM_NUM[c] for c in o] != sorted(ELEM_NUM[c] for c in o)


def rank_of(block):
    m = RE_TOP.match(block)
    if not m:
        return RANK_OTHER
    title = m.group(1)
    for key, r in RANK:
        if key in title:
            return r
    return RANK_OTHER


def blocks_of(card_body):
    """按「行首 - **X**」切块；块内所有行（含缩进子项）一起搬。"""
    blocks, cur = [], None
    for line in card_body.split("\n"):
        if RE_TOP.match(line):
            if cur is not None:
                blocks.append(cur)
            cur = [line]
        else:
            cur = [line] if cur is None else cur + [line]
    if cur is not None:
        blocks.append(cur)
    return ["\n".join(b).strip("\n") for b in blocks]


def normalize_card(card):
    """只重排卡内区块；标题行留在原位。"""
    m = re.match(r"(?s)(^###\s+\d+\.\d+\s[^\n]*\n)(.*)$", card)
    if not m:
        return card, False
    head, body = m.group(1), m.group(2)
    # 卡尾（--- 或下一个 ## 章节）不参与重排
    cut = re.search(r"(?m)^(---|##\s)", body)
    core, tail = (body[:cut.start()], body[cut.start():]) if cut else (body, "")
    blocks = blocks_of(core)
    if not any(RE_TOP.match(b) for b in blocks):
        return card, False
    ordered = [b for _, b in sorted(enumerate(blocks), key=lambda t: (rank_of(t[1]), t[0]))]
    new = head + "\n\n" + "\n\n".join(ordered) + "\n\n" + (tail.lstrip("\n") if tail else "")
    new = re.sub(r"\n{4,}", "\n\n\n", new)
    return new, new != card


def line_multiset(s):
    return collections.Counter(l.strip() for l in s.split("\n") if l.strip())


def main():
    ap = argparse.ArgumentParser(description="案例卡要素顺序规范化（零删除，带不变式校验）")
    ap.add_argument("--fix", action="store_true", help="写入修复（预设只体检）")
    ap.add_argument("--file", default="", help="只处理某行业档（如 02）")
    a = ap.parse_args()

    bad, fixed, skipped = [], 0, 0
    for p in files(a.file):
        src = open(p, encoding="utf-8").read()
        new = src
        for num, card in list(cards(src)):
            if is_disordered(card):
                bad.append((os.path.basename(p), num, "".join(order_of(card))))
        if not a.fix:
            continue
        # 逐卡替换（由后往前，避免索引位移）
        spans = []
        heads = list(re.finditer(r"(?m)^###\s+(\d+\.\d+)\s", src))
        for i, m in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(src)
            nxt = re.search(r"(?m)^##\s", src[m.end():end])
            if nxt:
                end = m.end() + nxt.start()
            spans.append((m.start(), end))
        for s, e in reversed(spans):
            nc, _ = normalize_card(src[s:e])
            new = new[:s] + nc + new[e:]
        new = re.sub(r"\n{4,}", "\n\n\n", new)
        # 硬不变式
        ok = line_multiset(new) == line_multiset(src)
        # 卡片标题数 == ① 出现数（每张卡必须恰好一个 ①）
        ok = ok and len(re.findall(RE_HEAD, new)) == len(re.findall(r"(?m)^- \*\*① 是什么\*\*", new))
        ok = ok and all(len(re.findall(f"^- \\*\\*{c} ", new, re.M)) ==
                        len(re.findall(f"^- \\*\\*{c} ", src, re.M)) for c in "①②③④⑤")
        if not ok:
            skipped += 1
            print(f"  ❌ 不变式不过，放弃写入：{os.path.basename(p)}")
            continue
        if new != src:
            open(p, "w", encoding="utf-8").write(new)
            fixed += 1

    if bad:
        print(f"顺序异常：{len(bad)} 张卡")
        for f, n, o in bad[:20]:
            print(f"   {f} §{n} → {o}")
    else:
        print("✅ 所有卡片要素顺序正常（①②③④⑤）")
    if a.fix:
        print(f"---\n已修复文件 {fixed} 个；因不变式放弃 {skipped} 个")
    sys.exit(0 if not bad else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"{WARN} 已中断。")
        sys.exit(130)
    except Exception as e:
        # 协议 8：脚本挂了要能降级继续，不能让执行 AI 卡在裸 traceback 上。
        print(f"{NG} 执行出错：{type(e).__name__}: {e}")
        print(f"{HINT} 依协议 8：修正后重跑；环境问题就改用 Markdown 协议手工完成，不要卡在这里。")
        sys.exit(2)
