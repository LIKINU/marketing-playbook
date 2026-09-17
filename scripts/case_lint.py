#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
案例卡体检 · case_lint.py  （把「案例集硬规则」变成机械检查）

为什么有它（2026-09-16）：
    SKILL 写了「案例集硬规则：严禁公司背景（创始人／成立年份／股权／融资／营收／人事）」，
    但**没有任何脚本检查**，于是库里积累了大量与营销无关的背景资讯（营收 1000+ 处）。
    规则只写在文字里＝模型不会看＝等于没有。本脚本把它变成可跑的检查。

用法：
    python scripts/case_lint.py                    # 扫全库，出报告
    python scripts/case_lint.py cases/14-*.md      # 只扫指定档
    python scripts/case_lint.py --max 900          # 容忍上限（超过则退出码 1）
    python scripts/case_lint.py --strict           # 关闭「身份栏／归因栏」豁免（回到裸计数）
    python scripts/case_lint.py --quiet

两处**已记录的计数豁免**（用户 2026-09-17 决策，选项 A：维持现状、只调整上限）：
    1. `- **谁做的**：` —— 格式规定的**身份栏**，按设计就要写「谁做的（甲方自建／创始人／成立年份）」。
       它回答的是「这个案例属于谁」，不是公司传记；把它计入「公司背景违规」等于与格式冲突。
    2. `- ⚠️ **归因提醒**：` —— 它的**职能就是口径溯源**，必须指名「某人在某场合披露」才能让人核到源头。
       去掉人名会让这一栏失去意义。用 `--strict` 可恢复裸计数。

上限：**预设 900**（2026-09-17 实测基准：裸计数 1043 → 剔身份栏 868 → 再剔归因栏 768；
     取 900 保留约 17% 余量，用于拦截**新增**的背景膨胀，而不是要求清理既有存量）。
     下限只作趋势预警，**不是硬门槛**——不想让它报警就 `--max` 传更大的值。

退出码：0 = 未超上限；1 = 超出（建议清理）；2 = 脚本出错
规则来源：`references/cases/README.md` §六「卡片内容硬规则」（＋两项计数例外）
"""

import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")

from _common import OK, NG, WARN, HINT, INFO   # noqa: E402  统一符号，不要在各自文件里重定义

# 公司背景词（与 SKILL「案例集硬规则」对应）。机构／书籍／出版物类（46–51）豁免。
BG_WORDS = ["创始人", "创始人", "成立于", "成立于", "股权", "股权", "融资", "融资",
            "营收", "营收", "财报", "财报", "估值", "董事长", "董事长", "CEO",
            "裁员", "裁员", "IPO", "上市首日", "招股书", "招股书", "创办人", "创办人"]
EXEMPT_SKIP = {49}   # 只豁免 49（营销书籍与作者：作者名/书名本身即重点）
# 注：46/47/48/50（机构/出版物类）同样按规则清理 —— 只保留「理解其方法所必需」的背景

# 计数豁免行（前缀匹配）。见文件头说明（1）（2）。
EXEMPT_PREFIX = ("- **谁做的**", "- ⚠️ **归因提醒**")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser(description="案例卡体检（禁公司背景）")
    ap.add_argument("paths", nargs="*", help="指定文件；不给则扫全库")
    ap.add_argument("--max", type=int, default=None, help="全库容忍上限（预设：豁免模式 900；--strict 模式不设闸）")
    ap.add_argument("--strict", action="store_true", help="关闭身份栏／归因栏豁免（裸计数，报告用）")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    # --strict 是「量测模式」：只报数，不设闸（避免每次跑都红）。
    limit = a.max if a.max is not None else (None if a.strict else 900)
    ex_prefix = () if a.strict else EXEMPT_PREFIX
    files = a.paths or sorted(glob.glob(os.path.join(ROOT, "references", "cases", "*.md")))
    if not files:
        print(f"{NG} 找不到案例档")
        sys.exit(2)

    total = 0
    excl_total = 0
    rows = []
    worst_cards = []
    for f in files:
        base = os.path.basename(f)
        m = re.match(r"(\d+)", base)
        if not m:
            continue          # 非编号档（README.md 等）不是案例卡，跳过
        n = int(m.group(1))
        raw = read(f)
        # 标题（品牌名+角度）＝参考对象，不计入「公司背景」违规
        lines = [l for l in raw.splitlines() if not re.match(r"^#{1,6}\s", l)]
        kept, dropped = [], 0
        for l in lines:
            if ex_prefix and l.startswith(ex_prefix):
                dropped += sum(l.count(w) for w in BG_WORDS)
            else:
                kept.append(l)
        t = "\n".join(kept)
        hits = {w: t.count(w) for w in BG_WORDS if t.count(w)}
        cnt = sum(hits.values())
        if n not in EXEMPT_SKIP:
            total += cnt
            excl_total += dropped
        if cnt:
            rows.append((cnt, base, n in EXEMPT_SKIP, hits))
            # 逐卡定位重灾区
            for cm in re.finditer(r"(?m)^###\s+(\d+\.\d+)\s+(.+)$", t):
                end = re.search(r"(?m)^#{1,3}\s", t[cm.end():])
                seg = t[cm.end(): cm.end() + (end.start() if end else len(t))]
                c = sum(seg.count(w) for w in BG_WORDS)
                if c >= 5:
                    worst_cards.append((c, base, cm.group(1), cm.group(2)[:34]))

    if not a.quiet:
        print("=" * 64)
        print("案例卡体检 · 「严禁公司背景」")
        print("=" * 64)
        print(f"扫描 {len(files)} 个文件；违规词计入 {total}｜上限 {limit if limit else '—（量测模式，不设闸）'}"
              f"｜豁免 {excl_total}（{'裸计数，无豁免' if a.strict else '身份栏／归因栏'}）")
        rows.sort(reverse=True)
        for cnt, base, exempt, hits in rows[:15]:
            tag = "（49 书籍作者类·豁免）" if exempt else ""
            top = "、".join(f"{k}×{v}" for k, v in sorted(hits.items(), key=lambda x: -x[1])[:4])
            print(f"  {cnt:>5}  {base}{tag}\n         {top}")
        if worst_cards:
            print("\n重灾卡（单卡 ≥5 处背景词；这是既有存量，非新问题）：")
            for c, base, cid, title in sorted(worst_cards, reverse=True)[:10]:
                print(f"  {c:>3}  {base} §{cid} {title}")

    print("\n" + "-" * 64)
    print("规则：案例卡应只留「营销动作 ＋ 结果」；创始人／融资／营收／人事属应剔除的背景。")
    print("例外一：46–51（机构／书籍／出版物类）可保留「理解其方法所必需」的背景。")
    if not a.strict:
        print("例外二（2026-09-17 决策 A）：`- **谁做的**` 身份栏 与 `- ⚠️ **归因提醒**` 口径溯源栏"
              " 不计入；加 `--strict` 可恢复裸计数。")
    if limit is None:
        print(f"{OK} 量测模式（--strict）：裸计数 {total}，本轮不设闸。")
        sys.exit(0)
    if total > limit:
        print(f"{NG} 超上限（{total} > {limit}）—— 建议按上面清单清理案例卡。")
        sys.exit(1)
    print(f"{OK} 未超上限（{total} ≤ {limit}）。")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"{NG} 执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
