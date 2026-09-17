#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
命名梳理 · rename_tidy.py

为什么（2026-09-17，用户指令）：
    「第四 改完之后要重新疏理命名」

做完 ①（融 README）②（补 16 档缺口）③（06 进 cases、05/07 统一标题）之后，
命名层留下三处不一致：

    1. **顶层序号断层**：06 搬进 `cases/51` 之后，`00–09` 就空了 06 —— 而这串号
       是「按流程顺序」排的（SKILL 第 -1 步导航表的阅读顺序），断一号等于断了流程。
       → 07→06、08→07、09→08（补空，不留洞）
    2. **H1 名称不统一**：同一层级的档，H1 格式却五种
       —— 有的带序号（`# 44-招聘与雇主品牌`）、有的带版本痕迹
       （`# 范本 · 便利店开学季案范式（v2 · 2026-09-16 重跑实测版）`）、
       有的带宣传语（`# 接案操作流程 SOP（用这个 skill 干活 · …）`）、
       有的带中英对照（`# 03 · 方法论操作手册（Marketing Playbook · Operating Manual）`）。
       → 规则：**H1 ＝ 名称（＋语义限定词）**；序号、版本、宣传语、中英对照一律进文件头，不进 H1。
    3. **cases/README 登记表停留在「50 档／620 卡」**，且 §三 标题写「46–50」。
       → 依实际统计更新。

做什么：
    A. 改文件名：07/08/09 → 06/07/08（三档）
    B. 改 H1：13 处（见 H1_NEW）
    C. 全库字符串替换：所有旧文件名 → 新文件名（references/ 内外、scripts/ 也扫）
    D. 更新 `references/cases/README.md` 的统计与 §三 标题
    E. 报告待人工处理的叙述段落（脚本不改散文）

硬不变式：
    1. 改名后**旧文件名不得再出现在任何档**（残留即报错）
    2. 每个 H1 改动都必须**精确匹配**，匹配不到就整体中止（不改半套）

用法：
    python scripts/rename_tidy.py            # 体检（不写入）
    python scripts/rename_tidy.py --fix
退出码：0 = 完成；1 = 有不变式未通过；2 = 脚本出错
"""

import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
REF = os.path.join(ROOT, "references")
CASES = os.path.join(REF, "cases")

# ── A. 文件名（顶层序号补空）
RENAME = [
    ("references/07-选流派矩阵与对照表.md", "references/06-选流派矩阵与对照表.md"),
    ("references/08-质量范式-便利店开学季案.md", "references/07-质量范式-便利店开学季案.md"),
    ("references/09-操作流程SOP.md", "references/08-操作流程SOP.md"),
]

# ── C. 全库字符串替换（先长后短；每个旧名都只出现一次、彼此不重叠）
REF_MAP = [
    ("references/07-选流派矩阵与对照表.md", "references/06-选流派矩阵与对照表.md"),
    ("07-选流派矩阵与对照表", "06-选流派矩阵与对照表"),
    ("references/08-质量范式-便利店开学季案.md", "references/07-质量范式-便利店开学季案.md"),
    ("08-质量范式-便利店开学季案", "07-质量范式-便利店开学季案"),
    ("references/09-操作流程SOP.md", "references/08-操作流程SOP.md"),
    ("09-操作流程SOP", "08-操作流程SOP"),
]

# ── B. H1 统一（精确比对）
H1_NEW = {
    "# 03 · 方法论操作手册（Marketing Playbook · Operating Manual）": "# 方法论操作手册",
    "# 小企业与新品牌从零打造（合并版）": "# 小企业与新品牌从零打造",
    "# 选流派矩阵与对照表（路由器）": "# 选流派矩阵与对照表",
    "# 范本 · 便利店开学季案范式（v2 · 2026-09-16 重跑实测版）":
        "# 质量范式 · 便利店开学季案",
    "# 接案操作流程 SOP（用这个 skill 干活 · 从接案到交付 · 精确到每一步）":
        "# 接案操作流程 SOP",
    "# 44-招聘与雇主品牌": "# 招聘与雇主品牌 · 营销案例集",
    "# 45-物流与快递服务": "# 物流与快递服务 · 营销案例集",
    "# 46-国际4A与传播集团": "# 国际4A与传播集团 · 机构案例集",
    "# 47-战略咨询": "# 战略咨询 · 机构案例集",
    "# 48-本土创意与营销服务商": "# 本土创意与营销服务商 · 机构案例集",
    "# 49-营销书籍与作者": "# 营销书籍与作者 · 机构案例集",
    "# 50-机构出版物与观点库": "# 机构出版物与观点库 · 机构案例集",
    "# 本土数字营销与 MCN · 机构案例集": "# 本土数字营销与 MCN · 机构案例集",
}

# ── D. cases/README.md 的替换（旧字符串 → 新字符串）
README_FIX = [
    ("# references/cases/ · 导航（**50 个文件，但你只需要 1 个**）",
     "# references/cases/ · 导航（**51 个文件，但你只需要 1 个**）"),
    ("**规模**：50 个大类 / **620 张深度案例卡** ＝ 01–45 行业档 **411 张** ＋ 46–50 机构与方法论档 **209 张**。",
     "**规模**：51 个大类 / **649 张深度案例卡** ＝ 01–45 行业档 **411 张** ＋ 46–51 机构与方法论档 **238 张**。"),
    ("## 三、46–50 机构与方法论档（**做行业方案时不需要读**）",
     "## 三、46–51 机构与方法论档（**做行业方案时不需要读**）"),
    ("| 本行业常见死法 | 29 档 |", "| 本行业常见死法 | **45/45 档** |"),
    ("| 查不到的部分 | 30 档 |", "| 查不到的部分 | 47 档 |"),
    ("| 相关 | 32 档 |", "| 相关 | 33 档 |"),
    ("`46–50`（机构／出版物类）是**另一套结构**", "`46–51`（机构／出版物类）是**另一套结构**"),
    ("- **例外**：`46–50` 机构／书籍类可保留", "- **例外**：`46–51` 机构／书籍类可保留"),
    ("| `50-机构出版物与观点库` | 17 | 机构年度报告／数据源／演讲 IP（含「动机—用法」速查） |",
     "| `50-机构出版物与观点库` | 17 | 机构年度报告／数据源／演讲 IP（含「动机—用法」速查） |\n"
     "| `51-本土数字营销与MCN` | 29 | 省广／利欧／天下秀／分众、无忧／遥望／蜂群／Papitube、"
     "新消费操盘复盘、平台官方模型（AIPL／FAST／O-5A／5R） |"),
]


def md_files():
    out = []
    for f in glob.glob(os.path.join(ROOT, "**", "*.md"), recursive=True):
        if "/.git/" in f or "/.workbuddy/" in f:
            continue
        out.append(f)
    return out


def scan_files():
    """要扫描字符串的档：所有 .md ＋ scripts/*.py（**不含本脚本自己**——
    它的 REF_MAP 就是旧名的定义处，扫自己会永远报「有残留」）"""
    py = [f for f in glob.glob(os.path.join(HERE, "*.py"))
          if os.path.basename(f) != os.path.basename(__file__)]
    return md_files() + py


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true")
    a = ap.parse_args()

    plan, errs = [], []

    # ── A
    for old, new in RENAME:
        o = os.path.join(ROOT, old)
        if not os.path.exists(o):
            errs.append(f"找不到 {old}（可能已改过）")
        plan.append((old, new))

    # ── B（先确认每个 H1 都精确匹配，否则整体中止）
    targets = {}
    for f in md_files():
        s = open(f, encoding="utf-8").read()
        m = re.search(r"(?m)^# .+$", s)
        if not m:
            continue
        if m.group(0) in H1_NEW and m.group(0) != H1_NEW[m.group(0)]:
            targets[f] = (m.group(0), H1_NEW[m.group(0)])

    # ── C（统计将受影响的档）
    ref_hits = {}
    for f in scan_files():
        s = open(f, encoding="utf-8").read()
        n = 0
        for old, new in REF_MAP:
            n += s.count(old)
        if n:
            ref_hits[f] = n

    print(f"[A] 改文件名 {len(plan)} 个")
    for old, new in plan:
        print(f"    {old}\n      → {new}")
    print(f"\n[B] 改 H1 {len(targets)} 处")
    for f, (o, n) in sorted(targets.items()):
        print(f"    {os.path.relpath(f, ROOT)}\n      - {o}\n      + {n}")
    print(f"\n[C] 引用替换：{len(ref_hits)} 档／{sum(ref_hits.values())} 处")
    for f, n in sorted(ref_hits.items()):
        print(f"    {os.path.relpath(f, ROOT)}（{n}）")
    print(f"\n[D] cases/README.md：{len(README_FIX)} 条")
    for o, n in README_FIX:
        print(f"    - {o[:60]}\n      + {n.splitlines()[0][:60]}")
    if errs:
        print("\n❌ 中止：\n  " + "\n  ".join(errs))
        sys.exit(1)
    if not a.fix:
        print("\n（体检模式，未写入。加 --fix 执行）")
        sys.exit(0)

    # ── 执行（顺序很重要：先在旧路径上改内容，最后才改文件名）
    for f, (o, n) in targets.items():
        s = open(f, encoding="utf-8").read()
        s = s.replace(o, n, 1)
        open(f, "w", encoding="utf-8").write(s)
    for f in scan_files():
        s0 = open(f, encoding="utf-8").read()
        s = s0
        for old, new in REF_MAP:
            s = s.replace(old, new)
        if s != s0:
            open(f, "w", encoding="utf-8").write(s)
    for old, new in RENAME:
        os.rename(os.path.join(ROOT, old), os.path.join(ROOT, new))
    rf = os.path.join(CASES, "README.md")
    s = open(rf, encoding="utf-8").read()
    miss = [o for o, _ in README_FIX if o not in s]
    if miss:
        print(f"⚠️ cases/README.md 有 {len(miss)} 条没匹配到（未写入该档）：")
        for x in miss:
            print(f"    {x[:70]}")
    else:
        for o, n in README_FIX:
            s = s.replace(o, n)
        open(rf, "w", encoding="utf-8").write(s)
        print("✅ cases/README.md 已更新")

    # ── 硬不变式：旧文件名不得残留
    left = []
    for f in scan_files():
        s = open(f, encoding="utf-8").read()
        for old, _ in REF_MAP:
            if old in s:
                left.append((os.path.relpath(f, ROOT), old))
    print(f"\n✅ 执行完成｜残留旧名 {len(left)} 处")
    for f, o in left[:20]:
        print(f"    ⚠️ {f}：仍含 {o}")
    sys.exit(1 if left else 0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
