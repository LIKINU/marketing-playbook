#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
顶层工作档「标题统一」· top_titles.py

为什么（2026-09-17，用户裁定）：
    「050607 为甚么没放在 cases 库里 而且要跟 cases 库的格式一样」
    → 裁定：**06 进 cases（由 relocate_06.py 处理）；05/07 只统一标题。**

05／07 的标题问题（不改内容、只改标题）：
    05：
      · `## 阶段一｜…`～`## 阶段五｜…` 与 `## 路径一｜…`～`## 路径三｜…`
        占用了 `## ` 这层，但它们其实是「二、五阶段路径」与「三、三条路径」的**下级**——
        结果 H2 序号序列被切断（一 二 阶段一…五 三 路径一…三 四 …），
        file_meta 自动生成的目录因此长到没法看。
      · 末节 `## 查不到的部分` 没有序号，与其余 11 节不一致。
      · 「（合并版）」是内部痕迹，不是标题讯息。
    07：
      · 「（背这三句就够）」「（一句话定位，用来快速排除）」是口语说明，不是语义限定词。

做什么（**只动 `## `/`### ` 标题行，正文一行不碰**）：
    1. 把 `## 阶段N｜…` / `## 路径N｜…` 降为 `### `，其下属 `### ` 一并降为 `#### `
    2. H2 序号按出现顺序重编（〇、一、二…），末节补上序号
    3. 去掉口语括注与内部痕迹，保留语义限定词

硬不变式：
    1. **非标题行逐行不变**（含空行；用整段字符串比对）
    2. `# ` 一级标题数不变
    3. 改完后所有 `## ` 都在下面 EXPLICIT 白名单里（防止误改）

用法：
    python scripts/top_titles.py            # 体检
    python scripts/top_titles.py --fix
退出码：0 = 一致（或修复成功）；1 = 异常；2 = 脚本出错
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
REF = os.path.join(ROOT, "references")

FILES = ["05-小企业与新品牌从零打造.md", "06-选流派矩阵与对照表.md"]

# 首节序号的起点：05 有「〇、先定位你在哪一格」故从 〇 起；07 直接从 一 起
START = {"05-小企业与新品牌从零打造.md": 0, "06-选流派矩阵与对照表.md": 1}

NUMS = ["〇", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"]

RE_H2 = re.compile(r"^##\s+(.+?)\s*$")
RE_H3 = re.compile(r"^###\s+(.+?)\s*$")

# ── 降级：这些 H2 其实是下级（降成 H3），其下 `### ` 再降一级
DEMOTE_PREFIX = ("阶段一｜", "阶段二｜", "阶段三｜", "阶段四｜", "阶段五｜",
                 "路径一｜", "路径二｜", "路径三｜")

# ── H2 改名（精确比对，不含序号）→ (新标题正文, 是否降级)
RENAME = {
    # 05
    "合并说明": "合并说明",
    "新品牌 0→1 的五阶段路径": "新品牌 0→1 的五阶段路径",
    "小企业品牌化的三条路径": "小企业品牌化的三条路径",
    "各赛道从零起盘": "各赛道从零起盘",
    "零预算 / 微预算打法库（合并版）": "零预算 / 微预算打法库",
    "新品牌上市 90 天作战计划模板": "新品牌上市 90 天作战计划模板",
    "预算分配参考表": "预算分配参考表",
    "失败归因与解法（合并版）": "失败归因与解法",
    "骗局识别库（代运营 / 加盟 / 投流课程）": "骗局识别库（代运营 / 加盟 / 投流课程）",
    "对接实测清单（见小企业／新品牌客户时照着问）": "对接实测清单（小企业／新品牌客户照着问）",
    "小企业主决策自检清单（可打印）": "小企业主决策自检清单（可打印）",
    "查不到的部分": "查不到的部分",
    "先定位你在哪一格（路由表）": "先定位你在哪一格（路由表）",
    # 07
    "六组对照：同一问题，五类解法怎么解": "六组对照：同一问题，五类解法怎么解",
    "总览表（横版速查）": "总览表（横版速查）",
    "三条选型原则（背这三句就够）": "三条选型原则",
    "流派速查（一句话定位，用来快速排除）": "流派速查",
}


def strip_num(s):
    return re.sub(r"^\s*[〇一二三四五六七八九十]+\s*、\s*", "", s).strip()


def tidy(text, k0=0, verbose=False):
    lines = text.split("\n")
    out, changes = [], []
    k = k0
    demoting = False          # 是否正处于「阶段N／路径N」之下

    for i, l in enumerate(lines):
        m2 = RE_H2.match(l)
        if m2:
            core = strip_num(m2.group(1).replace("**", "").strip())
            if core.startswith(DEMOTE_PREFIX):
                demoting = True
                new = "### " + core
                if new != l:
                    changes.append((i + 1, l, new))
                out.append(new)
                continue
            demoting = False
            if core not in RENAME:
                raise ValueError(f"未在白名单的 H2：{core!r}（第 {i+1} 行）")
            canon = RENAME[core]
            num = NUMS[k] if k < len(NUMS) else str(k)
            k += 1
            new = f"## {num}、{canon}"
            if new != l:
                changes.append((i + 1, l, new))
            out.append(new)
            continue

        m3 = RE_H3.match(l)
        if m3 and demoting:
            new = "#### " + m3.group(1).strip()
            if new != l:
                changes.append((i + 1, l, new))
            out.append(new)
            continue

        out.append(l)

    return "\n".join(out), changes


def verify(old, new):
    def nonhead(s):
        return [l for l in s.split("\n")
                if l.strip() and not l.lstrip().startswith("#")]
    if nonhead(old) != nonhead(new):
        d = [x for x, y in zip(nonhead(old), nonhead(new)) if x != y]
        return f"非标题行被改动（{len(d)} 行），例：{d[0][:60]!r}" if d else "非标题行数变了"
    if len(re.findall(r"(?m)^#\s", old)) != len(re.findall(r"(?m)^#\s", new)):
        return "一级标题数变了"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true")
    a = ap.parse_args()

    bad = ok = 0
    for name in FILES:
        f = os.path.join(REF, name)
        old = open(f, encoding="utf-8").read()
        try:
            new, changes = tidy(old, START.get(name, 0))
        except ValueError as e:
            print(f"❌ {name}：{e}")
            bad += 1
            continue
        if not changes:
            ok += 1
            print(f"✅ {name}：已一致")
            continue
        print(f"\n{name}（{len(changes)} 处）")
        for ln, o, n in changes:
            print(f"  L{ln}\n    - {o}\n    + {n}")
        v = verify(old, new)
        if v:
            print(f"  ⚠️ 放弃写入：{v}")
            bad += 1
            continue
        if a.fix:
            open(f, "w", encoding="utf-8").write(new)

    print("\n" + "-" * 64)
    print(f"已一致 {ok} 档｜需改 {len(FILES) - ok - bad} 档｜异常 {bad} 档")
    print("✅ 完成，接著跑 file_meta.py --fix 同步目录" if a.fix else "（体检模式，未写入）")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
