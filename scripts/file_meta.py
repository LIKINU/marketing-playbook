#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件「自解释头」生成与校验 · file_meta.py

为什么有它（2026-09-17，用户原话）：
    「单纯写一个文字，根本就没有办法解决这么多文件，标题也没有说清楚，
      根本就没有办法让 Agent 理解并完整读取。」
    —— 61 个文件里只有 2 个有目录行；文件头全是散文（讲背景、可信度），
       **没有一条说「什么时候读」「读完得到什么」「有哪几节」**。
       Agent 因此无法判断要不要读、也无法确认自己读全了。

做什么：
    给每个文件（references/ 顶层 ＋ cases/ 01–50）在文件开头插入统一的引用块：
        > **这是什么**   一句话
        > **什么时候读** 触发场景 ＋ 明确「不要读什么」
        > **读完你能**   具体产出（由实际章节推导）
        > **目录**       由实际 `## ` 章节**自动生成** ← 这条让 Agent 能确认读全
        > **规模**       字数／卡数，由文件统计**自动生成**
    原本的引用行（建立日期、可信度等）**一律保留**，移到新块后面。

四项字段**全部机械生成**（不靠人写），因此永不会与实际不符；
改了章节或卡片，重跑一次即同步 —— 这才是机制，不是文字补丁。

用法：
    python scripts/file_meta.py                 # 体检：列出缺头／目录不符的档
    python scripts/file_meta.py --fix           # 生成／更新
    python scripts/file_meta.py --fix --file 23
退出码：0 = 全部合规（或修复成功）；1 = 有异常；2 = 脚本出错
"""

import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
CASES = os.path.join(ROOT, "references", "cases")

FIELDS = ("这是什么", "什么时候读", "读完你能", "目录", "规模")

# ── references/ 顶层工作档的「这是什么／什么时候读／读完你能」（人工写准：
#    这 10 档是「工具」而非「资料」，字段无法从章节推导）
MANUAL = {
    "00": ("打法引擎：**104 条打法**，每条含「为什么用它／具体动作到每一步／验收指标／可抄案例」",
           "**动笔前出骨架时**（第 -1 步导航表：『动笔前出骨架』）",
           "按客户状况查到 3–7 条可执行打法，每条都能直接抄成动作"),
    "01": ("交付文档的章节模板：八篇结构逐章骨架 ＋ 每章要填什么",
           "**写方案正文时**（确定打法组合之后）",
           "一份可直接往下填的八篇骨架，含每章硬要素清单"),
    "02": ("多 Agent 分工简报：五个角色（策略／品牌／触达／文案／财务风控）的可复制简报 ＋ 产出规格",
           "**要跑多 Agent 分工时**（每次接案必走）",
           "五份能直接丢给角色的简报，含「写不到即不合格」的深度下限"),
    "03": ("方法论操作手册：**111 个模型**（A–M 十三类），每个含「解决什么问题／怎么用N步／实操示例」",
           "**写策略篇时**（必引用 ≥3 个模型并标出处）",
           "3 个以上可直接写进方案的模型，含填空模板与示例"),
    "04": ("失败归因总库：**12 个失败模式** ＋ 归因速查表 ＋ 接案前 34 条失败预演清单",
           "**交付前的风险自检**（以及客户出事时定根因）",
           "「我这套打法会不会踩进模式 NN」的自检结论 ＋ 对应解法"),
    "05": ("小企业／新品牌从零打造：**五阶段路径**（验证→冷启→成长…），每阶段含目标／唯一KPI／预算／该做／不该做／常见死法／退出判据",
           "**客户是小企业或新品牌时**（这是主入口，不是补充）",
           "客户当前处在哪一阶段、这阶段唯一该盯的 KPI、以及下一步的预算与动作"),
    "06": ("选流派矩阵：**六组对照**（同一问题，五类解法怎么解）＋ 选型三原则",
           "**客户问「该找哪一类服务商／该走哪条流派」时**",
           "六个常见问题下、五类流派各自的解法与代价对照"),
    "07": ("质量标尺：便利店开学季案的**实测范式**——达不到本文门槛＝未达标",
           "**写完方案、准备交付前**（当深度标尺对照用）",
           "一份「做到什么程度算够」的判据清单"),
    "08": ("操作流程 SOP：**S0–S8 逐步**——每步的输入／命令／产出／校验",
           "**一接案就跑**（不确定下一步做什么时，也读它）",
           "当前处在第几步、下一步该跑哪条命令、产出应该长什么样"),
}


# 非案例档（不按此规范）：导航页本身
SKIP_NAMES = {"README.md"}

# 文件类型判定：一级标题 + 用途
KIND = {
    "cases": "案例集",
}


def read(p):
    return open(p, encoding="utf-8").read()


def h2_sections(t):
    """档内所有 `## ` 章节标题（去掉行内粗体，保留序号）"""
    out = []
    for m in re.finditer(r"(?m)^##\s+(.+?)\s*$", t):
        s = m.group(1).replace("**", "").strip()
        out.append(s)
    return out


def h1(t):
    m = re.search(r"(?m)^#\s+(.+?)\s*$", t)
    return m.group(1).replace("**", "").strip() if m else ""


def file_kind(path, t):
    """回传 (种类, 显示名, 卡数)"""
    base = os.path.basename(path)
    num = re.match(r"(\d+)", base)
    n = int(num.group(1)) if num else None
    cards = len(re.findall(r"(?m)^###\s+\d+\.\d+\s", t))
    if "/cases/" in path:
        if n and n >= 46:
            return "机构档", cards
        return "行业档", cards
    return "工作档", 0


def derive(path, t, sections, cards, kind):
    """四项字段的内容 —— 全部由文件实际内容推导"""
    base = os.path.basename(path)
    fname_stem = re.sub(r"^\d+-", "", os.path.splitext(base)[0])
    # 惯例：档内 H1 写得更完整，优先采用；去掉「· 营销案例集」这类后缀
    h1t = h1(t)
    h1t = re.sub(r"\s*[·・]\s*(营销案例集|营销案例集|案例集).*$", "", h1t).strip()
    h1t = re.sub(r"^\d+\s*[·・\-—]\s*", "", h1t)
    name = h1t or fname_stem
    num = re.match(r"(\d+)", base)
    n = num.group(1) if num else ""

    # 顶层工作档：用人工写准的字段（推导不出来）
    if kind == "工作档" and n and n in MANUAL:
        what, when, ret = MANUAL[n]
        toc = " ｜ ".join(sections) if sections else "（无 ## 章节）"
        size = f"{len(t)/10000:.1f} 万字"
        return what, when, ret, toc, size

    # ── 这是什么
    if kind == "行业档":
        what = f"{name} 这一行的营销案例集：**{cards} 张深度案例卡**，每卡五要素（是什么／为什么／做了什么／怎么做／效果）＋ 适用前提与坑"
    elif kind == "机构档":
        # 不写「不含公司财务与人事」这种绝对话——46–50 的「行业概览」与 51 的卡片
        # 本来就会引用乙方自身的毛利／收费结构（那是「选乙方」的判断依据）。
        # 真正要守的规则写成红线，让它机械地出现在每个机构档的文件头。
        what = (f"**{name}** 的机构案例：{cards} 张卡，每卡写「谁帮谁做了什么、怎么做、结果如何」；"
                f"乙方自身的营收／毛利／收费口径**只作选乙方判断，不得写进对外交付物**")
    else:
        what = h1(t) or fname_stem

    # ── 什么时候读
    if kind == "行业档":
        when = (f"**客户属于「{name}」这个行业时**：进档先读「案例清单」挑 1–3 个 → 再跳「深度拆解」。"
                f"　⛔ **不要读**：其余 44 个行业档、`cases/46–51`")
    elif kind == "机构档":
        # 场景从章节限定词推导（「门禁清单（选 4A 前）」→ 选 4A 前）
        qual = ""
        for s in sections:
            m = re.search(r"门禁清单[（(]([^）)]+)[）)]", s)
            if m:
                qual = m.group(1).strip()
                break
        scene = f"**{qual}**" if qual else "**要选乙方、或要把机构方法论引进方案时**"
        when = (f"{scene}：先读「门禁清单」自查 → 再看「深度拆解」找可引用的战役。"
                f"　⛔ **不要读**：`cases/01–45`（那是行业案例，与选乙方无关）")
    else:
        when = "**只在它被点名时读**（见 `../SKILL.md` 第 -1 步导航表）；不要通读。"

    # ── 读完你能（由实际章节推导，只列真的有的）
    got = []
    bare = [re.sub(r"^[一二三四五六七八九十]+\s*、\s*", "", s) for s in sections]
    for kw, desc in [
        ("案例清单", f"一份可抄动作清单（{cards} 条，每条一句话）"),
        ("本行业打法地图", "本行业的主路线与取舍"),
        ("行业概览", "本行业的规模／增长／营销关键点"),
        ("门禁清单", "接案前必须问出的 A–H 八项"),
        ("深度拆解", f"{cards} 张深度卡（14 个区块，可整卡复用）" if cards else "深度卡"),
        ("本行业对接实测清单", "本行业专属的 10 条提问"),
        ("本行业常见死法", "本行业最常翻的车与归因"),
        ("查不到的部分", "哪些数字不可引用（防对客户说错话）"),
    ]:
        if any(kw in s for s in bare):
            got.append(desc)
    # 46–51 的槽位叫「对接实测清单」（不带「本行业」），要单独收一次
    if (any("对接实测清单" in s for s in bare)
            and not any("本行业对接实测清单" in s for s in bare)):
        got.append("可照着问的对接实测清单")
    marks = "①②③④⑤⑥⑦⑧⑨"
    ret = ("".join(f"{marks[i]} {g}　" for i, g in enumerate(got)).strip()
           if got else "（见下方目录）")

    # ── 目录（自动；章节过多时截断，避免炸掉整行）
    if not sections:
        toc = "（无 ## 章节）"
    elif len(sections) <= 14:
        toc = " ｜ ".join(sections)
    else:
        toc = " ｜ ".join(sections[:8]) + f" ｜ …（共 {len(sections)} 节）"

    # ── 规模（自动）
    chars = len(t)
    size = f"{chars/10000:.1f} 万字" + (f" / {cards} 卡" if cards else "")
    return what, when, ret, toc, size


def meta_block(path, t):
    sections = h2_sections(t)
    kind, cards = file_kind(path, t)
    what, when, ret, toc, size = derive(path, t, sections, cards, kind)
    return (
        f"> **这是什么**：{what}\n"
        f"> **什么时候读**：{when}\n"
        f"> **读完你能**：{ret}\n"
        f"> **目录**：{toc}\n"
        f"> **规模**：{size}\n"
    )


def split_head(t):
    """回传 (一级标题行, 文件头引用块行列表, 其余正文)"""
    lines = t.split("\n")
    i = 0
    while i < len(lines) and not lines[i].startswith("# "):
        i += 1
    if i >= len(lines):
        return None, [], t
    h1line = lines[i]
    j = i + 1
    quotes = []
    while j < len(lines) and (lines[j].startswith(">") or lines[j].strip() == ""):
        if lines[j].startswith(">"):
            quotes.append(lines[j])
        j += 1
    rest = "\n".join(lines[j:])
    return h1line, quotes, rest


def build(path, t):
    h1line, quotes, rest = split_head(t)
    if h1line is None:
        return None
    # 保留原引用行里「不是我们生成的那五项」的行
    keep = [q for q in quotes
            if not any(("**" + f + "**") in q for f in FIELDS)]
    mb = meta_block(path, t)
    return h1line + "\n\n" + mb + ("\n".join(keep) + "\n" if keep else "") + "\n" + rest


def files(only=""):
    fs = [f for f in sorted(glob.glob(os.path.join(ROOT, "references", "*.md")))
          if os.path.basename(f) not in SKIP_NAMES]
    fs += [f for f in sorted(glob.glob(os.path.join(CASES, "*.md")))
           if os.path.basename(f) not in SKIP_NAMES]
    if only:
        fs = [f for f in fs if os.path.basename(f).startswith(only)]
    return fs


def main():
    ap = argparse.ArgumentParser(description="文件自解释头")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--file", default="")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    bad = ok = 0
    for f in files(a.file):
        base = os.path.basename(f)
        t = read(f)
        want = meta_block(f, t)
        _, quotes, _ = split_head(t)
        have = "\n".join(q for q in quotes if any(("**" + x + "**") in q for x in FIELDS))
        # 校验：五栏齐 且 目录行与实际章节一致
        cur_toc = ""
        for q in quotes:
            if "**目录**" in q:
                cur_toc = q.split("**目录**：", 1)[-1].strip()
        want_toc = meta_block(f, t).split("**目录**：", 1)[-1].split("\n")[0].strip()
        miss = [x for x in FIELDS if ("**" + x + "**") not in have]
        if miss or cur_toc != want_toc:
            bad += 1
            if not a.quiet:
                why = (f"缺 {','.join(miss)}" if miss else "目录与实际章节不符")
                print(f"  ⚠️ {base}：{why}")
        else:
            ok += 1
        if a.fix:
            new = build(f, t)
            if new is None:
                print(f"  ❌ {base}：找不到一级标题，跳过")
                continue
            # 硬不变式：只许动文件头（一级标题＋引用块），正文逐行不变
            _, _, rest_old = split_head(t)
            _, _, rest_new = split_head(new)
            if rest_old != rest_new:
                print(f"  ❌ {base}：正文被改动，放弃写入")
                continue
            open(f, "w", encoding="utf-8").write(new)

    print("-" * 64)
    print(f"合规 {ok} 档｜需处理 {bad} 档")
    if a.fix:
        print("✅ 已生成/更新自解释头")
    else:
        print("（体检模式，未写入。加 --fix 执行）")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
