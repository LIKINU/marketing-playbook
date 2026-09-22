#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stats.py — 全仓「数字」的**唯一事实源**（任务书 B5 + D6）

为什么有它（2026-09-22 · 外部任务书 D6 提出，实测确认）：
    同一个量在文档里被写死多次，**每次扩充必然过期**。实测现状：
      · 打法条数：SKILL/AGENTS 写 104、README 写 116 —— 而**真实是 116**；
      · 模型数：文档写 111 —— 真实 111（这条恰好对，但没法保证下次还对）；
      · 深度卡：SKILL 里 628 与 611 **两个数并存**（早该作废的旧口径没清）；
      · 冒烟项数：三处写「12 项」，实际 13（本次改完是 15）。
    判据都对了、文档却在骗人 —— 而**读者是按文档判断这套工具有多大**的。

它做什么：
    ① 用**各档真实的卡片标记**统计一遍（标记写在本文件里，是唯一出处）；
    ② `--audit` 把 SKILL／README／AGENTS 里出现的同类数字**逐条抓出来对账**，
       不一致就 exit 1（挂进回归，从此不再漂）。

用法：
    python scripts/stats.py              # 打印全部数字
    python scripts/stats.py --json       # 机器可读
    python scripts/stats.py --audit      # 对账文档里的数字（不一致 exit 1）
退出码：0 = 通过；1 = --audit 发现不一致；2 = 出错
"""

import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REF = os.path.join(ROOT, "references")
sys.path.insert(0, HERE)
from _common import OK, NG, WARN, INFO   # noqa: E402

# ── 各档的「卡片标记」——**唯一出处**。加新档就加这里，别在文档里手写数字。──
#    标记都经过实测核对（2026-09-22），不是猜的：
#      · 打法库用 `### 1.1 超级符号` 这种「编号.序号」标题；`### 0.x` 是 §0 总表小节，**不算打法**；
#      · 方法论用 `### A1｜…`（A–M 十三类）；
#      · 失败归因的业务模式用 `## 模式 01｜…`，AI 执行者模式用 `## 模式 A · …`；
#      · 案例卡用各档里的 `### 3.1 品牌｜…`（深度卡），清单小标题（`### 商超`/`### A. 生意基本盘`）不算。
SPECS = [
    #   ⚠️ 第一版写成 `^###\s+1\d*\.\d+` → 只匹配「1x.x」，把 §2～§11 的打法全漏了（实测 32）。
    #      「非 0 开头」才是正解：`### 0.1 §1 认知类` 是 §0 总表小节，不算打法。
    ("打法条数", "references/00-打法库.md", r"^###\s+(?!0\.)\d+\.\d+", "§1 起的打法标题（§0 总表小节不计）"),
    ("模型数", "references/03-方法论操作手册.md", r"^###\s+[A-M]\d+", "A–M 十三类的模型卡"),
    ("业务失败模式", "references/04-失败归因总库.md", r"^##\s+模式\s*\d+", "模式 01–12"),
    ("AI执行者模式", "references/04-失败归因总库.md", r"^##\s+模式\s+[A-I]\s*[·・]", "附录 模式 A–I"),
    ("深度卡", "references/cases/*.md", r"^###\s+\d+\.\d+", "各行业档的 ### N.M 深度卡"),
    ("行业案例档", "references/cases/*.md", None, "cases/*.md（不含 README）"),
    ("顶层参考档", "references/[0-9]*.md", None, "references/ 下的编号档"),
    ("脚本数", "scripts/*.py", None, "scripts/*.py"),
    ("文档档数", "*.md", None, "仓库根目录的 .md"),
]


def count(pattern, glob_pat):
    files = sorted(glob.glob(os.path.join(ROOT, glob_pat)))
    files = [f for f in files if not f.endswith("README.md")]
    if pattern is None:
        return len(files)
    n = 0
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                n += len(re.findall(pattern, fh.read(), re.M))
        except Exception as e:
            # ⚠️ **不吞异常**（2026-09-22：`optimize_scan` 的 D1 当场抓到我这行 `except: pass`）——
            #   吞掉＝这个数字可能少算一格却回报「一致」。宁可吵一声。
            print(f"{WARN} 统计跳过（读不了）：{os.path.basename(f)}（{type(e).__name__}）")
    return n


def cli_count():
    n = 0
    for f in glob.glob(os.path.join(HERE, "*.py")):
        with open(f, encoding="utf-8") as fh:
            if '__name__ == "__main__"' in fh.read():
                n += 1
    return n


def collect():
    out = {}
    for name, gp, pat, _why in SPECS:
        out[name] = count(pat, gp)
    out["CLI 脚本数"] = cli_count()
    return out


# ── 文档里「写着数字」的句子：抓 N 与它后面的量名，再与实测对账 ──
#    只抓**明确的量名**（够窄才不误伤）：条打法／个模型／个失败模式／张深度卡／份行业案例／支脚本
AUDIT_PATTERNS = [
    (r"(\d+)\s*条打法", "打法条数"),
    (r"(\d+)\s*个模型", "模型数"),
    (r"(\d+)\s*个失败模式", "业务失败模式"),
    (r"(\d+)\s*张(?:深度)?卡", "深度卡"),
    (r"(\d+)\s*份行业案例", "行业案例档"),
    (r"(\d+)\s*支\s*(?:Python\s*)?脚本", "脚本数"),
]

# ⚠️ 不是「声明数量」的语境 —— 见到就不对账（否则一堆叙述被误报）。
#    实测第一版把「挑 ≥3 个模型」「接入 33 个模型后」「回 0 张卡」「把 49 个模型绑到」
#    全当成了数量声明（15 处误报，真漂移只有 4 处）→ 判据被噪声淹没。
#    规则：**数字前面 ≤7 字里**出现下列任一词 → 是叙述／要求，不是仓库规模。
AUDIT_SKIP_BEFORE = ("≥", ">=", "挑", "选", "接入", "只有", "回", "把", "用", "绑",
                     "至少", "需", "应", "引", "对", "覆盖", "接", "含")


def _is_size_statement(line, start):
    """这个数字是在**声明仓库规模**吗？（不是叙述／要求／范围／作废声明）"""
    pre = line[max(0, start - 7):start]
    if any(k in pre for k in AUDIT_SKIP_BEFORE):
        return False
    # 范围数（「3–7 条打法」「5~8 个模型」）不是数量声明
    if re.search(r"[0-9][\s]*[–—~～\-][\s]*$", pre):
        return False
    # 「作废声明」行（「历史数字 419 → 611 → 628 均已作废，勿再引用」）——那正是为了消灭旧数，
    # 把它当漂移去改＝把作废说明也改坏。
    if re.search(r"作废|勿再引用|已废弃", line):
        return False
    return True


def audit(stats):
    """扫 SKILL/README/AGENTS，把同类数字抓出来对账。→ [(file, line_no, text, said, real)]"""
    bad = []
    for f in ("SKILL.md", "README.md", "AGENTS.md"):
        p = os.path.join(ROOT, f)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as fh:
            for i, ln in enumerate(fh, 1):
                for pat, key in AUDIT_PATTERNS:
                    for m in re.finditer(pat, ln):
                        if not _is_size_statement(ln, m.start()):
                            continue          # 叙述／要求，不是数量声明
                        said = int(m.group(1))
                        real = stats.get(key)
                        if real is not None and said != real:
                            bad.append((f, i, ln.strip()[:88], said, real, key))
    return bad


def main():
    ap = argparse.ArgumentParser(description="全仓数字事实源 ＋ 文档对账")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--audit", action="store_true", help="对账文档里的数字（不一致 exit 1）")
    a = ap.parse_args()

    st = collect()
    if a.json:
        print(json.dumps(st, ensure_ascii=False, indent=2))
    else:
        print("=" * 64)
        print("全仓数字（唯一事实源 · stats.py）")
        print("=" * 64)
        for name, gp, pat, why in SPECS:
            print(f"  {name:12} {st[name]:5}   ← {gp}  「{why}」")
        print(f"  {'CLI 脚本数':12} {st['CLI 脚本数']:5}   ← scripts/*.py 里带 __main__ 的")

    if a.audit:
        bad = audit(st)
        print()
        print("=" * 64)
        if bad:
            print(f"{NG} 文档里的数字与实测不一致 {len(bad)} 处：")
            for f, i, txt, said, real, key in bad:
                print(f"   · {f}:{i}  写的 {said}，实测 {real}（{key}）")
                print(f"       {txt}")
            print(f"\n→ 改法：把数字改成实测值，或改成「见 stats.py 输出」不再写死。")
            return 1
        print(f"{OK} 文档里的数字与实测一致（已核对 SKILL／README／AGENTS）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"{NG} 脚本执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
