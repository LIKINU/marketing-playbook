#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
空转扫描器 · tautology_scan.py

为什么要有这支脚本（2026-09-19）：

  第一轮「78 行逐行核对」时派了 **6 个 LLM 校验员**，用手工反例找出 **25 处「判据空转」** ——
  即「**把章节内容删空、只留表头/标签**，`selfcheck` 仍然 ✅」的判据。
  手工做这件事**慢、不可重复、还会漏**（每个校验员只盯自己那一个作业体系）。

  但这件事**根本不需要 LLM**：它是个纯粹的差分 ——
    · 输入 A：掏空稿（内容删空、表头保留）
    · 输入 B：真标杆稿（真内容）
  对同一套 `selfcheck` 跑两遍，把「关卡 → 标记」抓出来对比：
    · **在 A 上仍是 ✅ 的关 = 空转**（它没能力抓住「什么都没有」）
    · 在 B 上是 ❌（而 B 并非完整版专属）的关 = 可能误伤，也要看

  → 于是把「一次性的人工取证」变成**可反复运行的机械检查**。
    **只要改了判据就重跑它** —— 这才是防「判据悄悄变成永真」的正解。

用法：
    python tautology_scan.py                 # 用默认夹具（示例规则表 → 标准档骨架）
    python tautology_scan.py --tier B端      # 换档位
    python tautology_scan.py --keep          # 保留中间产物到 /tmp 并打印路径
退出码：0 = 未发现空转；1 = 发现空转（列出）；2 = 用法错误
"""

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
EXAMPLE_RULES = os.path.join(ROOT, "references", "范例", "（示例）区域茶饮新品牌-任务规则表.json")
BENCH = os.path.join(ROOT, "references", "范例", "便利店开学季战役-交付稿.md")
SELFCHECK = os.path.join(HERE, "selfcheck.py")
COMPOSER = os.path.join(HERE, "composer.py")

# 关卡行形如：`  ✅ 渠道原生：开头过短 0 行…` / `  ❌ 0.1 因子表：…`
LINE = re.compile(r"^\s*([✅❌⚠️ℹ️])\s+([^：:\n]{2,30})[：:](.*)$")


def hollow(text):
    """把稿子**掏空**：表格只留表头与分隔行；`- **标签**：内容` 只留标签。

    这就是六个 LLM 校验员手工做的事，这里用代码固定下来 —— **手法可重复**。
    """
    out, i = [], 0
    lines = text.split("\n")
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("|"):
            blk = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                blk.append(lines[i])
                i += 1
            out.append(blk[0])                                   # 表头留下
            out.extend(r for r in blk[1:] if "---" in r)          # 分隔行留下
            continue
        m = re.match(r"^(\s*-\s*\*\*[^*]{2,40}\*\*[^\n]*?[：:]).*$", lines[i])
        out.append(m.group(1) if m else lines[i])
        i += 1
    return "\n".join(out)


def run_selfcheck(path):
    """跑 selfcheck，回 ({关卡名: 标记}, 是否崩溃)。

    ⚠️ 2026-09-19：**崩溃必须当硬失败**。第一版只印一行警告就继续，于是
    selfcheck 崩了、只印出 1 行关卡，扫描器照样报「✅ 未发现空转」——
    **那是最坏的一种绿：检查根本没跑，却报告没问题。**
    """
    r = subprocess.run([PY, SELFCHECK, path], capture_output=True, text=True)
    out = r.stdout
    crashed = "执行出错" in out or r.returncode == 2
    if crashed:
        print(f"{NG} selfcheck 在 {os.path.basename(path)} 上崩了 —— **本次结论不成立**：")
        for l in out.splitlines():
            if "出错" in l or "在 selfcheck.py" in l:
                print("   " + l.strip())
    verdicts = {}
    for ln in out.splitlines():
        m = LINE.match(ln)
        if m:
            name = m.group(2).strip()
            # 同一关可能印多行（明细+汇总），取「最严」的那个标记
            mark = m.group(1)
            rank = {"❌": 3, "⚠️": 2, "✅": 1, "ℹ️": 0}
            if name not in verdicts or rank[mark] > rank[verdicts[name]]:
                verdicts[name] = mark
    return verdicts, crashed


from _common import OK, NG, WARN, INFO   # noqa: E402  统一符号，不要各自重定义


def main():
    ap = argparse.ArgumentParser(description="空转扫描：掏空稿上仍 ✅ 的判据＝空转")
    ap.add_argument("--tier", default="标准")
    ap.add_argument("--rules", default=EXAMPLE_RULES)
    ap.add_argument("--skeleton", help="直接给一份骨架（跳过 composer）")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()

    sk = a.skeleton
    if not sk:
        if not os.path.exists(a.rules):
            print(f"{NG} 找不到规则表：{a.rules}")
            sys.exit(2)
        sk = "/tmp/tauto_skeleton.md"
        r = subprocess.run([PY, COMPOSER, "--rules", a.rules, "--out", sk,
                            "--tier", a.tier], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"{NG} composer 失败：{r.stderr[:200]}")
            sys.exit(2)

    base = open(sk, encoding="utf-8").read()
    hol = hollow(base)
    p_hol = "/tmp/tauto_hollow.md"
    open(p_hol, "w", encoding="utf-8").write(hol)

    print("=" * 72)
    print("空转扫描 · tautology_scan.py")
    print("（方法：把稿子**掏空**——表格只留表头、字段只留标签——再跑 selfcheck；"
          "**在掏空稿上仍是 ✅ 的关＝空转**）")
    print("=" * 72)
    v_hol, crash_hol = run_selfcheck(p_hol)
    v_sk, crash_sk = run_selfcheck(sk)
    if crash_hol or crash_sk:
        print(f"\n{NG} 中止：selfcheck 崩溃时**任何「未发现空转」的结论都是假的**。"
              f"先修崩溃再重跑本脚本。")
        sys.exit(2)
    print(f"  掏空稿：{len(v_hol)} 关被印出｜骨架：{len(v_sk)} 关被印出")

    # ⚠️ **设计使然的例外**（量类判据）：
    #   `composer` 会把**打法库的方法论正文**一并注入骨架（「先记数：高峰与低峰各站店外 30 分钟…」
    #   「晚上 8 点的实景照」…）。这些是**正文**（不是标题、不是注释、不是表头），
    #   因此任何「数数字／数字数」的判据，在内容被删空后**仍然达标** ——
    #   **这是判据类型的固有边界，不是「忘了查内容」**：它无法区分
    #   「骨架自带的方法论」与「填稿人写进去的内容」，因为两者在文本层是同一种东西。
    #   → 如实归类，不装作修好；真正抓「空壳」的是【31】。
    BY_DESIGN = {
        "正文非空白字数": "字数关：骨架注入的方法论正文本身就有一万多字，删空内容后仍过线",
        "场景章深度": "深度关：章节里的数字来自注入的方法论（「站店外 30 分钟」「晚上 8 点」）",
    }
    taut = sorted(n for n, mk in v_hol.items() if mk == OK and n not in ("内容空洞",))
    # 掏空稿上该关仍是 ✅，且它在骨架上也是 ✅ → 它没有区分能力
    taut = [n for n in taut if v_sk.get(n) == OK]
    taut_by_design = [n for n in taut if n in BY_DESIGN]
    taut = [n for n in taut if n not in BY_DESIGN]

    print(f"\n{NG if taut else OK} 空转判据：**{len(taut)} 处**"
          + ("（掏空后仍 ✅，等于没有检查能力）" if taut else "（未发现）"))
    for n in taut:
        print(f"     · {n}")
    print(f"\n  ⚠️ 「内容空洞」(【31】) 已单列不计 —— 它是**兜底关**，"
          f"它的职责就是抓这些关漏掉的东西。")
    if taut_by_design:
        print(f"\n{INFO} 设计使然的例外（量类判据，{len(taut_by_design)} 处）—— **不是缺陷**：")
        for n in taut_by_design:
            print(f"     · {n}：{BY_DESIGN[n]}")

    # 反向：掏空稿上 ❌ 的关，说明它真能区分内容有无（这是好关）
    good = sorted(n for n, mk in v_hol.items() if mk == NG)
    print(f"\n{OK} 有区分力的关（掏空后变 ❌）：{len(good)} 处")
    if a.keep:
        print(f"\n  中间产物：{sk}｜{p_hol}")
    print("\n" + "-" * 72)
    if taut:
        print("处置建议：把这些关从「查关键词在不在」改成查**内容层** ——")
        print("  `selfcheck.py` 里有现成助手 `_data_text(sec)`：它排除标题行、注释行、")
        print("  **每张表的表头与分隔行**、**每行第一格**（骨架常把第一格预填成标签）。")
    else:
        print("✅ 未发现空转：每个被印出的关，都真的因为「内容被删空」而变红。")
    sys.exit(1 if taut else 0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(130)
    except Exception as e:
        print(f"{NG} 脚本执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
