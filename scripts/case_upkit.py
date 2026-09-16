#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""案例卡升级工具包 · upkit.py
各檔升级脚本统一 import 本模块，避免每個檔重寫 blocks/插入/校驗樣板。

典型用法：
    from upkit import run
    C = {"3.1": {"why": ..., "ins": ..., "n3": ..., "spend": ...,
                 "attrib": ..., "fit": ..., "err": ..., "rel": ...}}
    R = [("旧句", "新句"), ...]          # 斷句修復，每條必須唯一命中
    run(FP, C, R, need=("②","④"))       # need 指定本檔要補齊的要素個數
"""
import re
import collections


def blocks(text):
    """產出 (卡號, 起, 訖)。卡 = ### N.M 起，到下一張卡或 ## 章節為止。"""
    heads = list(re.finditer(r"(?m)^###\s+(\d+\.\d+)\s", text))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        nxt = re.search(r"(?m)^##\s", text[m.end():end])
        if nxt:
            end = m.end() + nxt.start()
        out.append((m.group(1), m.start(), end))
    return out


def ins_after_line(b, prefix, text):
    i = b.find(prefix)
    assert i >= 0, "NO " + prefix
    j = b.find("\n", i)
    assert j > 0
    return b[:j + 1] + text + b[j + 1:]


def ins_before(b, anchor, text, alt=()):
    for a in (anchor,) + tuple(alt):
        i = b.find(a)
        if i > 0:
            return b[:i] + text + b[i:]
    raise AssertionError("NO ANCHOR " + anchor)


def fill(b, d, cid):
    """按 d 的字段就地補齊要素。缺哪個字段就補哪塊（可只傳部分）。"""
    n0 = len(b)
    if "why" in d:                       # ② 為什麼 + 洞察（插在「誰做的」之後）
        t = "\n- **② 為什麼**：" + d["why"] + "\n"
        if d.get("ins"):
            t += "\n- **洞察**：" + d["ins"] + "\n"
        b = ins_after_line(b, "- **誰做的**", t)
    if "n3" in d:                        # ③ 改一行式 + 新增 ④ 標題
        b2 = re.sub(r"(?m)^- \*\*③ 做了什麼\*\*(（[^）]*）)?：",
                    "- **③ 做了什麼**：" + d["n3"] + "\n\n- **④ 怎麼做**：", b, count=1)
        assert b2 != b, "③ MISS " + cid
        b = b2
    if "spend" in d:                     # 花了多少（插在 ⑤ 效果 之前）
        b = ins_before(b, "- **花了多少**", "", ("- **⑤ 效果**",))
        b = ins_before(b, "- **⑤ 效果**", "- **花了多少**：" + d["spend"] + "\n\n")
    if "attrib" in d:                    # 尾塊（插在 適用前提 之前）
        tail = ("- ⚠️ **歸因提醒**：" + d["attrib"] + "\n\n"
                "- **適配不同規模客戶**：\n  " + d["fit"] + "\n\n"
                "- **常見錯誤**：\n  " + d["err"] + "\n\n"
                "- **本檔關聯**：" + d["rel"] + "\n\n")
        b = ins_before(b, "- **適用前提 / 坑**：", tail,
                       ("- **適用前提**：", "- **沒解決的問題 / 局限**：", "- **局限**："))
    assert len(b) > n0, "SHRINK " + cid
    return b


def run(FP, C, R=(), need=("②", "④"), order=("①", "③", "⑤")):
    t = open(FP, encoding="utf-8").read()
    ORIG = t
    for cid, s, e in reversed(blocks(t)):
        if cid not in C:
            continue
        t = t[:s] + fill(t[s:e], C[cid], cid) + t[e:]
    skipped = []
    for old, new in R:
        n = t.count(old)
        if n != 1:
            skipped.append((n, old[:44]))
            continue
        t = t.replace(old, new, 1)
    c0 = collections.Counter(re.findall(r"(?m)^- \*\*([①②③④⑤]) ", ORIG))
    c1 = collections.Counter(re.findall(r"(?m)^- \*\*([①②③④⑤]) ", t))
    h0 = len(re.findall(r"(?m)^###\s+\d+\.\d+\s", ORIG))
    h1 = len(re.findall(r"(?m)^###\s+\d+\.\d+\s", t))
    assert h0 == h1, f"卡片數變了 {h0}→{h1}"
    for k in order:
        assert c0[k] == c1[k], f"{k} 計數被改動 {c0[k]}→{c1[k]}"
    for k in need:
        # 有的卡有兩個 ④（如「④ 怎麼做（上海站）＋（北京站）」），故用 >=
        assert c1[k] >= h1, f"{k} 未補齊：{c1[k]}/{h1}"
    open(FP, "w", encoding="utf-8").write(t)
    print(f"要素  前 {dict(c0)}  →  後 {dict(c1)}｜卡片 {h0}")
    for n, s in skipped:
        print(f"⚠️ 跳過修復（命中 {n} 處）：{s}")
    print(f"✅ {FP.split('/')[-1]}｜字數 {len(ORIG)} → {len(t)}（+{len(t)-len(ORIG)}）")
