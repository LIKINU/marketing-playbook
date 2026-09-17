#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""案例卡升级工具包 · upkit.py
各档升级脚本统一 import 本模块，避免每个文件重写 blocks/插入/校验样板。

典型用法：
    from upkit import run
    C = {"3.1": {"why": ..., "ins": ..., "n3": ..., "spend": ...,
                 "attrib": ..., "fit": ..., "err": ..., "rel": ...}}
    R = [("旧句", "新句"), ...]          # 断句修复，每条必须唯一命中
    run(FP, C, R, need=("②","④"))       # need 指定本档要补齐的要素个数
"""
import re
import collections


def blocks(text):
    """产出 (卡号, 起, 讫)。卡 = ### N.M 起，到下一张卡或 ## 章节为止。"""
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
    """按 d 的字段就地补齐要素。缺哪个字段就补哪块（可只传部分）。"""
    n0 = len(b)
    if "why" in d:                       # ② 为什么 + 洞察（插在「谁做的」之后）
        t = "\n- **② 为什么**：" + d["why"] + "\n"
        if d.get("ins"):
            t += "\n- **洞察**：" + d["ins"] + "\n"
        b = ins_after_line(b, "- **谁做的**", t)
    if "n3" in d:                        # ③ 改一行式 + 新增 ④ 标题
        b2 = re.sub(r"(?m)^- \*\*③ 做了什么\*\*(（[^）]*）)?：",
                    "- **③ 做了什么**：" + d["n3"] + "\n\n- **④ 怎么做**：", b, count=1)
        assert b2 != b, "③ MISS " + cid
        b = b2
    if "spend" in d:                     # 花了多少（插在 ⑤ 效果 之前）
        b = ins_before(b, "- **花了多少**", "", ("- **⑤ 效果**",))
        b = ins_before(b, "- **⑤ 效果**", "- **花了多少**：" + d["spend"] + "\n\n")
    if "attrib" in d:                    # 尾块（插在 适用前提 之前）
        tail = ("- ⚠️ **归因提醒**：" + d["attrib"] + "\n\n"
                "- **适配不同规模客户**：\n  " + d["fit"] + "\n\n"
                "- **常见错误**：\n  " + d["err"] + "\n\n"
                "- **本档关联**：" + d["rel"] + "\n\n")
        b = ins_before(b, "- **适用前提 / 坑**：", tail,
                       ("- **适用前提**：", "- **没解决的问题 / 局限**：", "- **局限**："))
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
    assert h0 == h1, f"卡片数变了 {h0}→{h1}"
    for k in order:
        assert c0[k] == c1[k], f"{k} 计数被改动 {c0[k]}→{c1[k]}"
    for k in need:
        # 有的卡有两个 ④（如「④ 怎么做（上海站）＋（北京站）」），故用 >=
        assert c1[k] >= h1, f"{k} 未补齐：{c1[k]}/{h1}"
    open(FP, "w", encoding="utf-8").write(t)
    print(f"要素  前 {dict(c0)}  →  后 {dict(c1)}｜卡片 {h0}")
    for n, s in skipped:
        print(f"⚠️ 跳过修复（命中 {n} 处）：{s}")
    print(f"✅ {FP.split('/')[-1]}｜字数 {len(ORIG)} → {len(t)}（+{len(t)-len(ORIG)}）")
