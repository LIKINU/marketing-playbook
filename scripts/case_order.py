#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
案例卡「要素顺序」规范化 · case_order.py

背景（2026-09-16）：
  歷次批量改造（relabel / clean / 手工改寫）會把要素行搬亂——
  典型症狀：③ 跑到 ② 前面、③ 掉到卡片最後、誰做的／洞察 散了、標題換行被吞（`---### 3.2`）。
  本腳本把「卡片內部要素順序」變成機械可查、可修復，且**保證不丟內容**。

規範順序（每張深度卡）：
  ① 是什麼 → 誰做的 → ② 為什麼 → 洞察 → ③ 做了什麼 → ④ 怎麼做
  → 落地拆解 → 花了多少 → ⑤ 效果 → 可抄的點
  → 適配不同規模客戶 → 常見錯誤 → 本檔關聯 → 沒解決的問題 / 局限
  （未列出的區塊一律排到最後，保持原有相對順序）

安全保證（硬不變式，任一不過就放棄寫入該檔）：
  1. 非空行集合（multiset）完全一致 —— 只許改順序與空行，不許刪內容
  2. `### N.M` 標題數 == ① 出現數
  3. ① ② ③ ④ ⑤ 各自出現次數不變

用法：
    python scripts/case_order.py            # 只體檢（列出順序異常的卡）
    python scripts/case_order.py --fix      # 修復（帶不變式校驗，失敗自動放棄）
    python scripts/case_order.py --fix --file 02
退出碼：0 = 無異常；1 = 有異常（--fix 時為修復失敗）
"""

import argparse
import collections
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")

# 規範順序（數字越小越前）
RANK = [
    ("① 是什麼", 10),
    ("誰做的", 15),
    ("② 為什麼", 20),
    ("洞察", 25),
    ("③ 做了什麼", 30),
    ("④ 怎麼做", 40),
    ("落地拆解", 45),
    ("花了多少", 48),
    ("⑤ 效果", 50),
    ("可抄的點", 60),
    ("適配不同規模客戶", 70),
    ("常見錯誤", 75),
    ("本檔關聯", 80),
    ("沒解決的問題", 90),
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
    """產出 (卡號, 卡片全文)。卡片 = ### N.M 起，到下一張卡或 ## 章節為止。"""
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
    """按「行首 - **X**」切塊；塊內所有行（含縮進子項）一起搬。"""
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
    """只重排卡內區塊；標題行留在原位。"""
    m = re.match(r"(?s)(^###\s+\d+\.\d+\s[^\n]*\n)(.*)$", card)
    if not m:
        return card, False
    head, body = m.group(1), m.group(2)
    # 卡尾（--- 或下一個 ## 章節）不參與重排
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
    ap = argparse.ArgumentParser(description="案例卡要素順序規範化（零刪除，帶不變式校驗）")
    ap.add_argument("--fix", action="store_true", help="寫入修復（預設只體檢）")
    ap.add_argument("--file", default="", help="只處理某行業檔（如 02）")
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
        # 逐卡替換（由後往前，避免索引位移）
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
        # 硬不變式
        ok = line_multiset(new) == line_multiset(src)
        # 卡片標題數 == ① 出現數（每張卡必須恰好一個 ①）
        ok = ok and len(re.findall(RE_HEAD, new)) == len(re.findall(r"(?m)^- \*\*① 是什麼\*\*", new))
        ok = ok and all(len(re.findall(f"^- \\*\\*{c} ", new, re.M)) ==
                        len(re.findall(f"^- \\*\\*{c} ", src, re.M)) for c in "①②③④⑤")
        if not ok:
            skipped += 1
            print(f"  ❌ 不變式不過，放棄寫入：{os.path.basename(p)}")
            continue
        if new != src:
            open(p, "w", encoding="utf-8").write(new)
            fixed += 1

    if bad:
        print(f"順序異常：{len(bad)} 張卡")
        for f, n, o in bad[:20]:
            print(f"   {f} §{n} → {o}")
    else:
        print("✅ 所有卡片要素順序正常（①②③④⑤）")
    if a.fix:
        print(f"---\n已修復檔案 {fixed} 個；因不變式放棄 {skipped} 個")
    sys.exit(0 if not bad else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"{WARN} 已中断。")
        sys.exit(130)
    except Exception as e:
        # 协议 8：脚本挂了要能降级继续，不能让执行 AI 卡在裸 traceback 上。
        print(f"{NG} 執行出錯：{type(e).__name__}: {e}")
        print(f"{HINT} 依協議 8：修正後重跑；環境問題就改用 Markdown 協議手工完成，不要卡在這裡。")
        sys.exit(2)
