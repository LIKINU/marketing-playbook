#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flow.py — 接案流程向导（marketing-playbook）

作用：看一眼当前工作目录，告诉你「现在在第几步、下一步跑哪条命令」。
      把 references/08-操作流程SOP.md 的流程变成**可被机械检查的状态机**。

用法：
    python scripts/flow.py                     # 看当前目录
    python scripts/flow.py --dir 案子目录
    python scripts/flow.py --dir . --check     # 另跑安全校验（selfcheck 当前 plan）

约定的产物文件名（放在同一工作目录）：
    rules.json     任务规则表（门禁产出）
    skeleton.md    composer 组装的骨架
    plan.md        模型填空后的方案
    *.docx         run_pipeline 出的稿
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

STEPS = [
    ("S0", "启动盘点", "读 SKILL.md / AGENTS.md / 09-SOP；先盘点连接器工具", "python scripts/flow.py"),
    ("S1", "门禁 13 项", "一次问全 → 出《任务规则表》并请用户确认", "python scripts/gate_check.py rules.json"),
    ("S2", "事实收集", "工具先于爬虫；每条数字标可信度", "（人工／连接器）"),
    ("S3", "组装骨架", "★ composer 机械注入知识（打法／模型／学者／案例）", "python scripts/composer.py --rules rules.json --out skeleton.md --tier 标准 --top 5"),
    ("S4", "填空在地化", "模型只补【填】＋ 确认全文简体（不得删改注入内容）", "（模型）"),
    ("S5", "交付自检", "任一硬错误＝不得交付", "python scripts/selfcheck.py plan.md"),
    ("S6", "深度诊断", "只诊断，不阻拦", "python scripts/depth_check.py plan.md"),
    ("S7", "出稿", "★ 唯一出口，不过不出稿", 'python scripts/run_pipeline.py --rules rules.json --budget budget.json --plan plan.md -o 方案.docx --title "客户名 营销方案" --date YYYY-MM-DD'),
    ("S8", "交付与沉淀", "回复原样输出 12 项自检单 ＋ 结案复盘", "（人工）"),
]


def _has(p):
    return os.path.exists(p)


def _read(p):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def detect(d):
    rules = os.path.join(d, "rules.json")
    skel = os.path.join(d, "skeleton.md")
    plan = os.path.join(d, "plan.md")
    has_rules, has_skel, has_plan = _has(rules), _has(skel), _has(plan)
    docx = [f for f in os.listdir(d) if f.endswith(".docx")] if os.path.isdir(d) else []

    if not has_rules:
        return "S1", "未见 rules.json —— 先过门禁 13 项"
    if not has_skel:
        return "S3", "未见 skeleton.md —— 跑 composer 组装骨架"
    if not has_plan:
        note = "（skeleton.md 仍含【填】，先填空再另存 plan.md）" if "【填】" in _read(skel) else ""
        return "S4", f"未见 plan.md —— 由 skeleton 填完另存 {note}"
    if "【填】" in _read(plan):
        return "S4", "plan.md 仍含【填】—— 补完再自检"

    # plan 已填 → 跑 selfcheck 判定
    try:
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, "selfcheck.py"), plan],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return "S5", "selfcheck 未过 —— 修硬错误后重跑"
    except Exception:
        return "S5", "selfcheck 无法执行 —— 检查环境"

    if not docx:
        return "S7", "未见 .docx —— 跑 run_pipeline 出稿"
    return "S8", f"已出稿（{docx[0]}）—— 交付回复输出 12 项自检单 + 复盘"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".")
    ap.add_argument("--check", action="store_true", help="另跑安全校验")
    a = ap.parse_args()
    d = os.path.abspath(a.dir)
    cur, msg = detect(d)

    print("=" * 60)
    print(f"接案流程状态 · {d}")
    print("=" * 60)
    for sid, name, what, cmd in STEPS:
        mark = "▶" if sid == cur else " "
        print(f" {mark} {sid} {name:<10} {what}")
    print("-" * 60)
    nxt = next(c for c in STEPS if c[0] == cur)
    print(f"📍 当前：{cur} {nxt[1]} —— {msg}")
    print(f"👉 下一步命令：{nxt[3]}")

    if a.check:
        plan = os.path.join(d, "plan.md")
        print("-" * 60)
        if os.path.exists(plan):
            r = subprocess.run(
                [sys.executable, os.path.join(HERE, "selfcheck.py"), plan],
                capture_output=True, text=True,
            )
            tail = [l for l in r.stdout.splitlines() if l.strip()][-1:] or ["(无输出)"]
            print(f"🔎 selfcheck：{tail[0]}（退出码 {r.returncode}）")
            sys.exit(0 if r.returncode == 0 else 1)
        print("（--check：未见 plan.md，无可校验）")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ flow 执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
