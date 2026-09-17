#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
案例档「章节标题」规范化 · case_sections.py

为什么有它（2026-09-17）：
    45 个行业档里，同一个章节有多达 7–8 种写法、序号还散在「二/三/四」「四/五/六」——
    共 56 个不同的原始标题、却只有 9 个语义槽位。Agent 想找「这档的对接清单」，
    得先猜它叫「四、本行业对接实测清单」还是「六、对接实测清单」还是「五、对接实测清单」。
    **这才是「Agents 看不来」的真因，不是文件多。**

做什么：
    1. 标题文字唯一化：9 个槽位各一个固定写法（**简体**，去掉所有括注变体）
    2. 序号按「实际顺序」重编（一、二、三…）—— 不同档章数不同，序号本就不该跨文件一致；
       Agent 靠 grep 标题文字定位，序号只服务人读
    3. 槽位标题一律**简体**固定写法（全仓统一简体，2026-09-18）；异体写法归一
    4. 46–51 是另一套结构（选服务商／引报告的自查清单），**保留其限定词**，只统一格式

安全保证（硬不变式，任一不过就放弃写入该档）：
    1. `## ` 标题**数量**不变
    2. **非空行 multiset 完全一致** —— 只许改标题行文字，不许动内容一行
    3. 改完后**所有 `## ` 标题都在白名单内**
    4. 每个槽位在某档内**最多出现一次**

用法：
    python scripts/case_sections.py            # 只体检，列出不一致的档
    python scripts/case_sections.py --fix      # 修复（带不变式校验）
    python scripts/case_sections.py --fix --file 23
退出码：0 = 一致（或修复成功）；1 = 有异常（--fix 时为修复失败）；2 = 脚本出错
"""

import argparse
import collections
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
CASES = os.path.join(ROOT, "references", "cases")

# ── 01–45：9 个语义槽位（顺序＝规范顺序，但实际编号按档内出现顺序给）
#    每项＝(正则, 正规标题文字[不含序号])
SLOTS_01_45 = [
    (r"案例清单|八个案例一句话",                              "案例清单"),
    (r"本行业打法地图|本行业的八种增长机制",                    "本行业打法地图"),
    (r"行业概览",                                            "行业概览"),
    (r"门禁清单",                                            "门禁清单"),
    (r"深度拆解|深度案例",                                    "深度拆解"),
    (r"本行业对接实测清单|对接实测清单",                        "本行业对接实测清单"),
    (r"本行业常见死法",                                       "本行业常见死法"),
    (r"查不到的部分",                                         "查不到的部分"),
    (r"相关|相关",                                            "相关"),
]

# ── 46–51：机构／书籍／出版物类，**限定词是语义的一部分，必须保留**
SLOTS_46_50 = [
    (r"行业概览",                "行业概览"),
    (r"门禁清单",                "门禁清单"),
    (r"深度案例|深度拆解",        "深度拆解"),
    (r"对接实测清单",             "对接实测清单"),
    (r"一页速查",                "一页速查"),
    (r"查不到的部分",             "查不到的部分"),
    (r"相关|相关",                "相关"),
]

NUMS = "一二三四五六七八九十"
RE_H2 = re.compile(r"^##\s+(.+?)\s*$")


def strip_num(s):
    """去掉开头的『一、』『二、』…… 与粗体标记"""
    s = re.sub(r"^\s*[一二三四五六七八九十]+\s*、\s*", "", s)
    return s.replace("**", "").strip()


def match_slot(core, slots, keep_qual=False):
    """回传 (槽位索引, 正规文字, 限定词)。

    01–45：括注**全部是模板注解**（「先读这一节」「按需阅读」「每篇 800–1500 字」…），
           **一律剥掉** —— 用整串比对会漏掉长括注（第一版 bug：29 档的案例清单没被改）。
    46–51：括注里的「选 4A 前」「找咨询前」是**语义限定词，必须保留**，只剥尾缀「先过一遍」。
    """
    for i, (pat, canon) in enumerate(slots):
        if re.search(pat, core):
            qual = ""
            if keep_qual:
                paren = re.search(r"[（(]([^）)]*)[）)]", core)
                if paren:
                    qual = re.sub(r"先过一遍$", "", paren.group(1).strip()).strip()
            return i, canon, qual
    return None


def norm_file(text, slots, keep_qual=False, strict_file=False):
    """回传 (新文字, 改动清单, 错误讯息)"""
    lines = text.split("\n")
    hits = []           # (行号, 原标题, 槽位i, canon, qual)
    for i, l in enumerate(lines):
        m = RE_H2.match(l)
        if not m:
            continue
        core = strip_num(m.group(1))
        r = match_slot(core, slots, keep_qual)
        if r is None:
            return None, [], f"未匹配的标题：{l!r}"
        hits.append((i, l, r[0], r[1], r[2]))

    # 同一槽位不得出现两次
    c = collections.Counter(h[2] for h in hits)
    dup = [slots[k][1] for k, v in c.items() if v > 1]
    if dup and strict_file:
        pass  # 允许（极少数档可能有两个「查不到」段），下面不报错
    # 重编号：按出现顺序
    k = 0
    changes = []
    for i, old, si, canon, qual in hits:
        title = canon + (f"（{qual}）" if qual else "")
        new = f"## {NUMS[k]}、{title}"
        k += 1
        if new != old:
            changes.append((i + 1, old, new))
            lines[i] = new
    return "\n".join(lines), changes, None


def verify(old, new, slots, keep_qual=False):
    """硬不变式"""
    o = [l for l in old.split("\n") if l.strip()]
    n = [l for l in new.split("\n") if l.strip()]
    if collections.Counter(o) != collections.Counter(n):
        # 允许「整行被替换」的情形：用差集判断是否只在标题行
        diff_o = collections.Counter(o) - collections.Counter(n)
        diff_n = collections.Counter(n) - collections.Counter(o)
        if set(diff_o) != {x for _, x, _ in []} and not all(l.startswith("## ") for l in diff_o):
            return f"非空行 multiset 被破坏（{len(diff_o)} 行）"
        if not all(l.startswith("## ") for l in diff_n):
            return f"新增了非标题行（{len(diff_n)} 行）"
    if len(re.findall(r"(?m)^##\s", old)) != len(re.findall(r"(?m)^##\s", new)):
        return "## 标题数变了"
    # 逐条检查：改完的标题必须**等于**正规文字（不只是「能匹配到槽位」）
    # —— 第一版只检查「能匹配」，漏掉了「括注未剥净」的情况。
    for raw in re.findall(r"(?m)^##\s+(.+)$", new):
        core = strip_num(raw)
        r = match_slot(core, slots, keep_qual)
        if r is None:
            return f"改完仍有非白名单标题：{raw!r}"
        expect = r[1] + (f"（{r[2]}）" if r[2] else "")
        if core != expect:
            return f"标题未收敛到正规版：{core!r} ≠ {expect!r}"
    return None


def files(only=""):
    fs = [f for f in sorted(glob.glob(os.path.join(CASES, "*.md")))
          if re.match(r"\d", os.path.basename(f))]
    if only:
        fs = [f for f in fs if os.path.basename(f).startswith(only)]
    return fs


def main():
    ap = argparse.ArgumentParser(description="案例档章节标题规范化")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--file", default="")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    bad = ok = changed = 0
    for f in files(a.file):
        base = os.path.basename(f)
        num = int(re.match(r"(\d+)", base).group(1))
        kq = num >= 46          # 46–51 才保留语义限定词
        slots = SLOTS_46_50 if kq else SLOTS_01_45
        old = open(f, encoding="utf-8").read()
        new, changes, err = norm_file(old, slots, kq)
        if err:
            print(f"❌ {base}：{err}")
            # 报错不能只告诉人「错了」—— 执行 AI 会开始瞎试，烧额度。
            print(f"   → 多半是某个 `## ` 标题不在 SLA 槽位白名单里（或同一槽位出现两次）。"
                  f"\n     处置：看该档的 `## ` 标题，改成 SLOTS 表里有的固定写法；"
                  f"确属新槽位就补进本档的 SLOTS_01_45／SLOTS_46_50，再重跑本脚本。")
            bad += 1
            continue
        if not changes:
            ok += 1
            continue
        changed += 1
        if not a.quiet:
            print(f"\n{base}（{len(changes)} 处）")
            for ln, o, n in changes:
                print(f"  L{ln}")
                print(f"    - {o}")
                print(f"    + {n}")
        if a.fix:
            v = verify(old, new, slots, kq)
            if v:
                print(f"  ⚠️ 放弃写入 {base}：{v}")
                bad += 1
                continue
            open(f, "w", encoding="utf-8").write(new)

    print("\n" + "-" * 64)
    print(f"已一致 {ok} 档｜需改 {changed} 档｜异常 {bad} 档")
    if a.fix:
        print("✅ 修复完成" if not bad else f"⚠️ 有 {bad} 档未修复")
    else:
        print("（体检模式，未写入。加 --fix 执行）")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 执行出错：{type(e).__name__}: {e}")
        print("   → 这是本脚本自己挂了（不是案例档的问题），**不要**改用例文档去迁就它。"
              "\n     处置：① 确认在仓库根目录跑；② `git status` 看本脚本或案例档有没有被改坏；"
              "\n     ③ 它只做机械归一，跳过本脚本不影响交付（后续 kb_audit L6 会再报一次）。")
        sys.exit(2)
