#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backlog_cleanup.py — 存量清理（**只标注、不批量改写**）

为什么是「只标注」：
    案例库有三类存量问题，都是**内容问题**，不是格式问题：
      ① **空卡**：13 个行业档的 140 张卡 `what/result/points` 全空 → 交付稿只剩品牌名
      ② **违规词**：`case_lint` 实测 894 条「严禁公司背景」命中，而阈值是 900 → 报 ✅
      ③ **洞察栏**：650 卡中 251 卡无洞察栏；399 条洞察行里 72 条是**数据复述**
    这三类**都不能靠脚本批量改写** —— 批量改写会「把内容改失真」，
    而案例库是模型学写作的教材，失真会直接污染下游交付稿。
    所以本工具只做两件安全的事：
      · `--report`  ：导出**全量清单**（带文件名、行号、原文片段），给人逐条处理
      · `--annotate`：给「无深度卡的清单行」补一个**纯标记**（`（仅清单·无深度卡）`），
                      不改任何实质内容 —— 这是唯一机械安全的动作

用法：
    python scripts/backlog_cleanup.py --report 优化轮次/存量清理清单.md
    python scripts/backlog_cleanup.py --annotate --dry-run    # 先看要改多少行
    python scripts/backlog_cleanup.py --annotate              # 真写入（纯标记）
"""
import argparse
import glob
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CASES = os.path.join(ROOT, "references", "cases")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import OK, NG, WARN, HINT   # noqa: E402  统一符号（不要在各自文件里重定义）

# 「严禁公司背景」的侦测词（与 case_lint 同源；此处独立实现是为了**导清单**而非**判达标**）
BG_WORDS = ["创始人", "创始人", "成立于", "成立于", "融资", "融资", "估值",
            "营收", "营收", "净利", "净利", "员工", "员工", "董事长", "董事长"]
# 这些字段里出现背景词是合法的（卡片结构本身要写「谁做的」）
BG_SAFE_FIELDS = ("**谁做的**", "**谁做的**", "**为什么**", "**为什么**")


def read(p):
    return io.open(p, encoding="utf-8").read()


def scan_cases():
    """→ {"empty": [(file, line, text)], "bg": [...], "insight_missing": [...], "insight_data": [...]}"""
    out = {"empty": [], "bg": [], "insight_missing": [], "insight_data": [], "nodc": []}
    for f in sorted(glob.glob(os.path.join(CASES, "*.md"))):
        base = os.path.basename(f)
        t = read(f)
        # ① 空卡：清单行里有品牌名但「做了什么／结果」为空
        for m in re.finditer(r"(?m)^\|\s*[\d.]+\s*\|\s*([^|]+?)\s*\|\s*\|", t):
            out["empty"].append((base, t[:m.start()].count("\n") + 1, m.group(1).strip()))
        for m in re.finditer(r"(?m)^\d+\.\s+\*\*([^*]+)\*\*\s*[｜|]\s*[^\n]{0,10}$", t):
            out["empty"].append((base, t[:m.start()].count("\n") + 1, m.group(1).strip()))
        # ② 违规词（排除合法字段所在行）
        for i, ln in enumerate(t.split("\n"), 1):
            if any(s in ln for s in BG_SAFE_FIELDS):
                continue
            for w in BG_WORDS:
                if w in ln:
                    out["bg"].append((base, i, w, ln.strip()[:60]))
                    break
        # ③ 洞察栏
        heads = list(re.finditer(r"(?m)^###\s+", t))
        for j, hm in enumerate(heads):
            blk = t[hm.start():heads[j + 1].start() if j + 1 < len(heads) else len(t)]
            title = blk.split("\n", 1)[0][:32]
            if "**洞察**" not in blk and "洞察" not in blk:
                out["insight_missing"].append((base, title))
            else:
                for m in re.finditer(r"洞察[^\n]*?[：:]\s*(.+)", blk):
                    line = m.group(1)
                    if len(re.findall(r"\d+(?:\.\d+)?\s*[%％]", line)) >= 1:
                        out["insight_data"].append((base, title, line.strip()[:50]))
        # ④ 清单行是否带深度卡节号（无节号＝暂无深度卡 → 可标记）
        for m in re.finditer(r"(?m)^(\d+\.\s+\*\*[^*]+\*\*[^\n]*)$", t):
            if "§" not in m.group(1) and "仅清单" not in m.group(1):
                out["nodc"].append((base, t[:m.start()].count("\n") + 1, m.group(1)[:50]))
    return out


def main():
    ap = argparse.ArgumentParser(description="案例库存量清理（只标注、不批量改写）")
    ap.add_argument("--report", default="", help="导出全量清单（Markdown）")
    ap.add_argument("--annotate", action="store_true",
                    help="给无深度卡的清单行补标记（**纯标记，不改实质内容**）")
    ap.add_argument("--dry-run", action="store_true", help="配合 --annotate，只显示不写入")
    a = ap.parse_args()

    r = scan_cases()
    print("=" * 66)
    print("案例库存量清理 · backlog_cleanup.py")
    print("=" * 66)
    print(f"  ① 疑似空卡（清单行无做法／结果）：{len(r['empty'])}")
    print(f"  ② 「严禁公司背景」命中（排除合法字段）：{len(r['bg'])}")
    print(f"  ③ 无洞察栏的卡：{len(r['insight_missing'])}")
    print(f"  ④ **数据复述型洞察**（含百分比）：{len(r['insight_data'])}")
    print(f"  ⑤ 无深度卡节号的清单行（可安全标记）：{len(r['nodc'])}")

    if a.report:
        L = ["# 案例库存量清理清单\n",
             "> 由 `scripts/backlog_cleanup.py` 导出。**只列不改** —— 这三类都是内容问题，",
             "> 批量改写会让教材失真，而教材失真会直接污染下游交付稿。\n",
             f"\n## 一、疑似空卡（{len(r['empty'])} 条）\n",
             "| 档 | 行 | 品牌 |\n|---|---|---|\n"]
        for f, ln, b in r["empty"][:200]:
            L.append(f"| {f} | {ln} | {b} |\n")
        L.append(f"\n## 二、「严禁公司背景」命中（{len(r['bg'])} 条，已排除合法字段）\n")
        L.append("> 分两类处理：**A 类**＝纯背景描述（可直接删）；"
                 "**B 类**＝动作主体（改写进「谁做的」）。\n\n| 档 | 行 | 词 | 片段 |\n|---|---|---|---|\n")
        for f, ln, w, s in r["bg"][:200]:
            L.append(f"| {f} | {ln} | {w} | {s} |\n")
        L.append(f"\n## 三、无洞察栏的卡（{len(r['insight_missing'])} 张）\n\n| 档 | 卡 |\n|---|---|\n")
        for f, ti in r["insight_missing"][:200]:
            L.append(f"| {f} | {ti} |\n")
        L.append(f"\n## 四、数据复述型洞察（{len(r['insight_data'])} 条，需改写成人心话）\n\n"
                 "> 判据：**主语要是「人」**，不是「平台／渠道／品牌」。\n\n| 档 | 卡 | 原文 |\n|---|---|---|\n")
        for f, ti, s in r["insight_data"][:200]:
            L.append(f"| {f} | {ti} | {s} |\n")
        io.open(a.report, "w", encoding="utf-8").write("".join(L))
        print(f"{OK} 已导出清单：{a.report}")

    if a.annotate:
        n_file = n_line = 0
        for f in sorted(glob.glob(os.path.join(CASES, "*.md"))):
            t = read(f)
            if "仅清单·无深度卡" in t or "仅清单·无深度卡" in t:
                continue
            lines = t.split("\n")
            # ⚠️ 必须**限定在「案例清单」区段内**：深度卡里也有不缩进的编号行
            #   （如 `- **落地拆解**：` 下的 `  1. …` 虽缩进，但个别档有例外），
            #   不限范围就会把深度卡内容误标成「仅清单」—— 那就把教材改错了。
            hit = 0
            _sec = None
            for i, ln in enumerate(lines):
                if re.match(r"^##\s*[一二三四五六七八九十]*、?\s*案例清单", ln):
                    _sec = i
                    continue
                if _sec is not None and re.match(r"^##\s", ln):
                    _sec = None
                    continue
                if _sec is None:
                    continue
                if re.match(r"^\d+\.\s+\*\*[^*]+\*\*", ln) and "§" not in ln:
                    lines[i] = ln.rstrip() + "（仅清单·无深度卡）"
                    hit += 1
            if hit:
                n_file += 1
                n_line += hit
                if not a.dry_run:
                    io.open(f, "w", encoding="utf-8").write("\n".join(lines))
        print(f"{OK if not a.dry_run else WARN} 标记{'（dry-run 未写入）' if a.dry_run else '完成'}："
              f"{n_line} 行、{n_file} 个文件")
        print(f"{HINT} 这是**纯标记**（只在行尾加「（仅清单·无深度卡）」），不改任何实质内容。")
    if not a.report and not a.annotate:
        print(f"\n{WARN} 未指定动作。用 --report 导清单，或 --annotate 补标记。")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{WARN} 已中断。")
        sys.exit(130)
    except Exception as e:
        print(f"\n{NG} backlog_cleanup 执行出错：{type(e).__name__}: {e}")
        print(f"{HINT} 依协议 8：修正后重跑；环境问题就人工逐文件清理，不要卡在这里。")
        sys.exit(2)
