#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_charts.py — 从方案稿**自动生成数据图**（A 类）＋ 列出待生的 AI 示意图（B 类）

为什么有它（2026-09-22 · 用户要求「一套跟方案相匹配的生图逻辑」）：
    方案里的数字都在表里，但交付稿是**纯文字 + 表格**，客户看不到形状。
    用户另一套 skill（`Marketing-Analysis`）有成体系的图表能力（骨架留位 → `chart_check` 校验
    → `md2docx` 嵌图 → 交付模板固化样式），本 skill 过去**连插入图片都不支持**。

**与方案相匹配**（核心原则，别违反）：
    图的数字**直接从方案稿的表里抽**，不另编。所以——
      · 图画对了 ⇒ 表没抄错；图画不出来 ⇒ 说明那张表结构异常，**该报出来**；
      · 图题必须带**结论句 + 数据源章节**（本库「结论先行」规矩）。
    → 这条是「同一件事只留一个表达式」的延伸，也是**防幻觉的根本手段**。

两类图 / 两条路（用户 2026-09-22 定「两个都做」）：
    **A 类 · 数据图** —— 本脚本用 matplotlib **确定性生成**：可复现、零幻觉。
    **B 类 · 示意/氛围图** —— 由 AI 生图。⚠️ **费 token → 只列清单、不自动生**：
        `--ai-plan` 输出「哪几章值得配示意/氛围图 + 用途 + 提示词草稿」，交用户确认后才生。

用法
----
    python scripts/make_charts.py 方案.md                # A 类：自动出图并回填引用
    python scripts/make_charts.py 方案.md --dry-run      # 只看会画哪几张（不出图）
    python scripts/make_charts.py 方案.md --ai-plan      # B 类：列 AI 待生清单（不生成）
    python scripts/make_charts.py 方案.md --force        # 已有引用也重画（默认跳过）

产出
----
    与方案稿同目录的 `charts/` 下：`chartN-<slug>.png`（300 dpi，A4 竖排可用宽内）
    并在方案稿里、**对应表的下方**插入一行：`![图 N｜<结论> — 数据源：§X](charts/xxx.png)`

退出码：0 = 成功；1 = 有表该画却画不出来（结构异常）；2 = 出错
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _common import OK, NG, WARN, HINT, INFO   # noqa: E402

# ── 中文字体：matplotlib 默认字体没有中文，会画成豆腐块。必须先找一款可用的。────────
#    ⚠️ 找不到就**警告并停下**，不要静默出豆腐块（那等于交付一张废图）。
CN_FONT_CANDIDATES = [
    "PingFang SC", "Heiti SC", "Songti SC", "STHeiti", "Arial Unicode MS",
    "Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei", "SimHei",
]


def setup_matplotlib():
    import matplotlib
    matplotlib.use("Agg")                      # 无界面
    from matplotlib import font_manager, rcParams
    have = {f.name for f in font_manager.fontManager.ttflist}
    for name in CN_FONT_CANDIDATES:
        if name in have:
            rcParams["font.sans-serif"] = [name]
            rcParams["axes.unicode_minus"] = False
            return name
    print(f"{WARN} 找不到任何可用中文字体（试过：{'、'.join(CN_FONT_CANDIDATES)}）")
    print(f"{HINT} 图会画成豆腐块 —— 请先装一款中文字体，或在本脚本 CN_FONT_CANDIDATES 里加你的字体名。")
    return None


# ── 配色：营销方案用**克制的中性色**（不是数据大屏）。涨跌才用红/绿（中国习惯）。──
PALETTE = ["#2F4858", "#33658A", "#86BBD8", "#F6AE2D", "#F26419",
           "#758E4F", "#9A8C98", "#C9ADA7"]
INK = "#1F1F1F"


def parse_tables(lines):
    """抽出所有 markdown 表 → [{'line': 表头行号, 'header': [...], 'rows': [[...]]}]"""
    out, i, n = [], 0, len(lines)
    while i < n:
        if lines[i].strip().startswith("|") and i + 1 < n and re.match(r"^\|[-:\s|]+\|$", lines[i + 1].strip()):
            header = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            rows, j = [], i + 2
            while j < n and lines[j].strip().startswith("|"):
                rows.append([c.strip() for c in lines[j].strip().strip("|").split("|")])
                j += 1
            out.append({"line": i, "header": header, "rows": rows})
            i = j
        else:
            i += 1
    return out


def num(s):
    """从单元格里抠出第一个数（容忍「~106」「12.5 元」「45%」「800」）。→ float / None"""
    if s is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace(",", ""))
    return float(m.group(0)) if m else None


def col_of(header, kws):
    for i, h in enumerate(header):
        if any(k in h for k in kws):
            return i
    return -1


# ─────────────────────────────────────────────────────────────────────────────
# 图型（每种都返回 (标题, 画图函数)）；「数据源」由调用方按表所属章节补
# ─────────────────────────────────────────────────────────────────────────────
def chart_pie_like(ax, tbl, title):
    """预算结构：把「分项 × 金额」画成降序横向条形（比饼图更易读）。"""
    i_name = col_of(tbl["header"], ["分项", "项目", "物料", "名称", "渠道"])
    i_amt = col_of(tbl["header"], ["金额", "成本", "预算", "元"])
    if i_name < 0 or i_amt < 0:
        return None
    pairs = [(r[i_name], num(r[i_amt])) for r in tbl["rows"] if i_name < len(r) and i_amt < len(r)]
    pairs = [(k, v) for k, v in pairs if v and k and "合计" not in k and "总" not in k]
    if len(pairs) < 3:
        return None
    pairs.sort(key=lambda x: x[1])
    total = sum(v for _, v in pairs) or 1
    labels = [k[:14] for k, _ in pairs]
    vals = [v for _, v in pairs]
    ax.barh(labels, vals, color=PALETTE[1], height=0.62)
    for y, v in enumerate(vals):
        ax.text(v + total * 0.012, y, f"{v:,.0f}（{v / total:.0%}）", va="center", fontsize=8.5, color=INK)
    ax.set_xlim(0, max(vals) * 1.22)
    ax.set_xlabel("金额（元）", fontsize=9)
    return f"共 {len(vals)} 项，合计 {total:,.0f} 元；最大项「{labels[-1]}」占 {vals[-1] / total:.0%}"


def chart_kpi(ax, tbl, title):
    """KPI：目标 vs 预警线（目标取区间下界，预警线取阈值）。"""
    i_k = col_of(tbl["header"], ["KPI", "指标"])
    i_t = col_of(tbl["header"], ["目标"])
    i_w = col_of(tbl["header"], ["预警"])
    if i_k < 0 or i_t < 0:
        return None
    names, tgts, warns = [], [], []
    for r in tbl["rows"]:
        if max(i_k, i_t) >= len(r):
            continue
        nums = [num(x) for x in re.findall(r"\d[\d,]*", r[i_t])]
        if not nums:
            continue
        names.append(r[i_k][:10])
        tgts.append(min(nums))                      # 区间下界＝最低目标
        warns.append(num(r[i_w]) if i_w >= 0 and i_w < len(r) else None)
    if len(names) < 2:
        return None
    import numpy as np
    x = np.arange(len(names))
    w = 0.38
    ax.bar(x - w / 2, tgts, w, label="目标（区间下界）", color=PALETTE[1])
    if any(v is not None for v in warns):
        ax.bar(x + w / 2, [v or 0 for v in warns], w, label="预警线（触发兜底）", color=PALETTE[4])
    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=8.5)
    ax.legend(fontsize=8.5, frameon=False)
    ax.set_ylabel("数值", fontsize=9)
    return f"{len(names)} 个 KPI 的目标与预警线对照（预警线一触即启动兜底）"


def chart_sensitivity(ax, tbl, title):
    """敏感性：第一列是档位、后续列是数值 → 折线（如 动销率 → 净利）。"""
    if len(tbl["header"]) < 2:
        return None
    xs, series = [], {}
    for i, h in enumerate(tbl["header"][1:], 1):
        series[h] = []
    for r in tbl["rows"]:
        v0 = num(r[0]) if r else None
        if v0 is None:
            return None                              # 第一列不是数字 → 不是敏感性表
        xs.append(v0)
        for i, h in enumerate(tbl["header"][1:], 1):
            series[h].append(num(r[i]) if i < len(r) else None)
    if len(xs) < 3:
        return None
    for k, (name, ys) in enumerate(series.items()):
        if all(y is None for y in ys):
            continue
        ax.plot(xs, [y if y is not None else float("nan") for y in ys],
                marker="o", linewidth=1.8, color=PALETTE[k % len(PALETTE)], label=name[:12])
        for x, y in zip(xs, ys):
            if y is not None:
                ax.annotate(f"{y:,.0f}", (x, y), textcoords="offset points",
                            xytext=(0, 7), ha="center", fontsize=8, color=INK)
    ax.set_xlabel(tbl["header"][0], fontsize=9)
    ax.legend(fontsize=8.5, frameon=False)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    return f"{tbl['header'][0]} 从 {xs[0]:g} 到 {xs[-1]:g} 的走势（{len(xs)} 档）"


def chart_items(ax, tbl, title, top=12):
    """条目成本：如物料 12 件 → 成本条形（只画有数字的）。"""
    i_name = col_of(tbl["header"], ["物料", "行动", "品项", "名称", "项目"])
    i_cost = col_of(tbl["header"], ["成本", "金额", "预算", "元"])
    if i_name < 0 or i_cost < 0:
        return None
    pairs = [(r[i_name], num(r[i_cost])) for r in tbl["rows"]
             if i_name < len(r) and i_cost < len(r) and num(r[i_cost])]
    if len(pairs) < 4:
        return None
    pairs.sort(key=lambda x: -(x[1] or 0))
    pairs = pairs[:top]
    labels = [k[:12] for k, _ in pairs]
    vals = [v for _, v in pairs]
    ax.barh(range(len(vals)), vals, color=PALETTE[2], height=0.62)
    ax.set_yticks(range(len(vals)))
    ax.set_yticklabels(labels, fontsize=8.5)
    ax.invert_yaxis()
    for y, v in enumerate(vals):
        ax.text(v + (max(vals) or 1) * 0.015, y, f"{v:,.1f}", va="center", fontsize=8, color=INK)
    ax.set_xlabel("成本（元）", fontsize=9)
    return f"{len(pairs)} 项成本降序；最高「{labels[0]}」{vals[0]:,.1f} 元"


# 识别器：表头特征 → 图型（**顺序即优先级**，先匹配先赢）
RECOGNIZERS = [
    # (判据, 图型, slug, 说明)
    (lambda h, t: col_of(h, ["分项"]) >= 0 and col_of(h, ["金额"]) >= 0, chart_pie_like, "budget", "预算结构"),
    (lambda h, t: col_of(h, ["KPI", "指标"]) >= 0 and col_of(h, ["目标"]) >= 0, chart_kpi, "kpi", "KPI 目标与预警线"),
    (lambda h, t: col_of(h, ["动销"]) >= 0 and col_of(h, ["净利"]) >= 0, chart_sensitivity, "sensitivity", "敏感性（动销→净利）"),
    (lambda h, t: col_of(h, ["物料"]) >= 0 and col_of(h, ["成本"]) >= 0, chart_items, "materials", "物料成本分布"),
]


def section_of(lines, idx):
    """表头往上找最近的 ##### 标题 → (章节名, 章节号)"""
    for j in range(idx, -1, -1):
        m = re.match(r"^(#{2,4})\s*(.+?)\s*$", lines[j])
        if m:
            title = m.group(2)
            no = re.match(r"^([0-9]+(?:\.[0-9]+)?)", title)
            return title[:30], (no.group(1) if no else title[:8])
    return "", ""


# ── B 类：AI 示意图待生清单（**只列不生成**，费 token 要先问）────────────────
AI_SUGGEST = [
    ("门店形象 / 门头改造", "让客户看到改造后的门头效果", "门店门头效果图：品类色块＋大字品类词＋夜间灯光，实拍视角"),
    ("物料样机", "物料清单是文字表，客户看不出「贴出来长什么样」", "便利店橱窗大字报+价签+集点卡的实拍样机拼图"),
    ("风格板 / 视觉调性", "定位与主张段落，客户要看到视觉方向", "品牌视觉 moodboard：主色+辅色+字体气质+场景图，3×2 拼版"),
    ("节奏排期示意", "节奏表是日期表，客户看不出「什么时候是峰值」", "开学季 14 天节奏示意图：时间轴＋峰值标记＋关键动作图标"),
]


def dump_ai_plan(lines, plan_path):
    print("=" * 68)
    print("B 类｜AI 示意图待生清单（**不自动生成** —— 生图费 token，需你确认）")
    print("=" * 68)
    print(f"{INFO} 依据：这批图是「示意/氛围」性质，**数字不参与**；生图前请先确认张数与用途。")
    print(f"{WARN} 生图产物必须标注「AI 生成、仅供示意」（合规与版权）；不得用于标注价格/功效。")
    print()
    for i, (name, why, prompt) in enumerate(AI_SUGGEST, 1):
        print(f"  {i}. {name}")
        print(f"     为什么值得配：{why}")
        print(f"     提示词草稿：{prompt}")
    print()
    print(f"{HINT} 确认要做哪几张后，再逐张生；**默认不生**。")


def main():
    ap = argparse.ArgumentParser(description="从方案稿自动生成数据图（A 类）／列 AI 待生清单（B 类）")
    ap.add_argument("plan", help="方案 Markdown")
    ap.add_argument("--dry-run", action="store_true", help="只列会画哪几张，不出图")
    ap.add_argument("--ai-plan", action="store_true", help="只输出 B 类 AI 待生清单（不生成）")
    ap.add_argument("--force", action="store_true", help="已有引用也重画（默认跳过）")
    ap.add_argument("--outdir", default="charts", help="图输出目录（相对方案稿所在目录）")
    a = ap.parse_args()

    if not os.path.exists(a.plan):
        print(f"{NG} 找不到方案稿：{a.plan}")
        return 2
    lines = open(a.plan, encoding="utf-8").read().split("\n")

    if a.ai_plan:
        dump_ai_plan(lines, a.plan)
        return 0

    font = setup_matplotlib() if not a.dry_run else None
    if not a.dry_run and font is None:
        return 1
    if font:
        print(f"{INFO} 中文字体：{font}")

    base = os.path.dirname(os.path.abspath(a.plan))
    outdir = os.path.join(base, a.outdir)
    tables = parse_tables(lines)

    jobs = []
    for t in tables:
        for judge, fn, slug, label in RECOGNIZERS:
            if judge(t["header"], t):
                sec, secno = section_of(lines, t["line"])
                jobs.append({"tbl": t, "fn": fn, "slug": slug, "label": label, "sec": sec, "secno": secno})
                break

    if not jobs:
        print(f"{WARN} 没找到可画的数据表（认的表头：预算分项+金额／KPI+目标／动销+净利／物料+成本）")
        return 0

    print(f"{INFO} 认出 {len(jobs)} 张可画的表：")
    for k, j in enumerate(jobs, 1):
        print(f"   {k}. [{j['label']}] §{j['secno']} {j['sec']}（表头：{'｜'.join(j['tbl']['header'][:5])}）")
    if a.dry_run:
        print(f"{HINT} --dry-run：未出图。")
        return 0

    import matplotlib.pyplot as plt
    os.makedirs(outdir, exist_ok=True)
    made, failed = [], []
    for k, j in enumerate(jobs, 1):
        fname = f"chart{k}-{j['slug']}.png"
        fpath = os.path.join(outdir, fname)
        rel = f"{a.outdir}/{fname}"
        existing = any(rel in l for l in lines)
        if existing and not a.force:
            print(f"   {INFO} 已有引用，跳过：{rel}（要重画加 --force）")
            continue
        fig, ax = plt.subplots(figsize=(7.2, max(2.6, min(6.0, 0.42 * len(j['tbl']['rows']) + 1.6))), dpi=300)
        try:
            concl = j["fn"](ax, j["tbl"], j["label"])
        except Exception as e:
            concl = None
            print(f"   {WARN} 画「{j['label']}」出错：{type(e).__name__}: {e}")
        if not concl:
            plt.close(fig)
            failed.append(j["label"])
            print(f"   {NG} 放弃「{j['label']}」—— 表结构不符合该图型的必要列（**这本身是信号**：该表可能结构异常）")
            continue
        ax.set_title(concl, fontsize=9.5, color=INK, pad=8)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        fig.tight_layout()
        fig.savefig(fpath, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        made.append((k, j, rel, concl))

    print()
    for k, j, rel, concl in made:
        print(f"   {OK} 出图：{rel}")
    print(f"\n{INFO} 共出 {len(made)} 张；放弃 {len(failed)} 张。")

    # ── 回填引用（幂等：已有该图引用的位置不重复插）──
    if made:
        new = list(lines)
        for k, j, rel, concl in made:
            anchor = j["tbl"]["line"]
            # 插到该表最后一行的下一行
            end = anchor + 2
            while end < len(new) and new[end].strip().startswith("|"):
                end += 1
            cap = (f"![图 {k}｜{concl} — 数据源：§{j['secno']} {j['sec']}]({rel})")
            if not any(rel in l for l in new):
                new.insert(end, "\n" + cap)
        open(a.plan, "w", encoding="utf-8").write("\n".join(new))
        print(f"{OK} 已把 {len(made)} 条图引用回填到方案稿（表下方一行）")
        print(f"{HINT} 下一步：build_docx 会把它们嵌成图片（居中＋题注）。")

    if failed:
        print(f"\n{WARN} {len(failed)} 张没画出来：{'、'.join(failed)} —— 建议人工看一眼那些表的结构。")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{WARN} 已中断。")
        sys.exit(130)
    except Exception as e:
        print(f"\n{NG} 脚本执行出错：{type(e).__name__}: {e}")
        print("→ 依协议 8：同一项连续 2 次不过就停手，把问题摊给用户。")
        sys.exit(2)
