#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键出稿 · run_pipeline.py —— **本 skill 唯一的出稿入口**

为什么要有这个文件
----------------
单独跑四个脚本时，执行者很容易「忘记跑」「选择性跑」「跑不过就手工绕过」。
本档把整条链串起来，**任何一关不过就中止、不生成 .docx**。

    ① gate_check     门禁 13 项 + 任务规则表已确认
    ② role_check     多 Agent 分工（5 角色产出 + 裁决记录）—— **没走分工就不出稿**
    ③ budget_check   预算分项加总 = 合计
    ④ selfcheck      结构 / 自检单 / 内部文档泄漏 / 禁用词 / 核心方法论要素 / 知识库引用 / 简体
    ⑤ depth_check    9 个深度维度（**只诊断，不阻拦**）
    ⑥ build_docx     出稿（内部会再跑一次 selfcheck）

用法
----
    python scripts/run_pipeline.py \\
        --rules  rules.json \\
        --budget budget.json \\
        --plan   plan.md \\
        -o       方案.docx \\
        --title  "客户名 营销方案" [--subtitle "副标题"] [--date 2026-09-16]

参数
----
    --rules    《任务规则表》JSON（**必填**；没问过门禁就没有它 → 直接拒绝）
    --roles    多 Agent 分工记录 JSON（**必填**；没走分工就不出稿。格式见 role_check.py 文件头）
    --skip-roles 跳过分工校验（仅小案子或用户同意时；交付时请声明）
    --budget   预算表 JSON（建议填；缺省会警告——协议 3 第 7 项要求预算能对上）
    --plan     方案 Markdown（**必填**）
    -o         输出 .docx 路径（**必填**）
    --title    文档标题（预设简体「营销方案」）；--subtitle 副标题；--date 日期；--author 署名
    --banned   自订禁用词表 JSON（透传 selfcheck／build_docx）
    --force    紧急出口：透传 build_docx 跳过自检（交付时必须声明未校验）

退出码
------
    0 = 全链通过，已出稿 ｜ 1 = 有硬错误，**未出稿** ｜ 2 = 环境问题（缺文件／缺依赖）

没有代码执行能力的平台：退回 Markdown 协议（手工跑 §六 清单 + 原样输出 12 项自检单）。
**降级不等于跳步。**
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
from _common import OK, NG, WARN, HINT, INFO   # noqa: E402  统一符号，不要在各自文件里重定义

STEPS = [
    # (显示名, 脚本, 是否阻断)
    ("① 门禁校验（gate_check）", "gate_check.py", True),
    ("② 分工校验（role_check）", "role_check.py", True),
    ("③ 预算校验（budget_check）", "budget_check.py", True),
    ("④ 交付前自检（selfcheck）", "selfcheck.py", True),
    ("⑤ 深度诊断（depth_check，只诊断）", "depth_check.py", False),
    ("⑥ 出稿（build_docx）", "build_docx.py", True),
]


def run(script: str, args: list, label: str) -> int:
    path = os.path.join(HERE, script)
    if not os.path.exists(path):
        print(f"{NG} 找不到脚本：{path}")
        return 2
    print(f"\n{'─' * 64}\n{label}\n{'─' * 64}")
    r = subprocess.run([sys.executable, path] + args)
    return r.returncode


def main():
    ap = argparse.ArgumentParser(description="marketing-playbook 唯一出稿入口")
    ap.add_argument("--rules", required=True, help="《任务规则表》JSON（必填）")
    ap.add_argument("--roles", default="", help="多 Agent 分工记录 JSON（**不提供会拒绝出稿**）")
    ap.add_argument("--skip-roles", action="store_true", help="跳过分工校验（仅小案子或用户同意时）")
    ap.add_argument("--budget", help="预算表 JSON（建议填）")
    ap.add_argument("--plan", required=True, help="方案 Markdown（必填）")
    ap.add_argument("-o", "--out", required=True, help="输出 .docx（必填）")
    ap.add_argument("--title", default="营销方案")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--date", default="")
    ap.add_argument("--author", default="")
    ap.add_argument("--banned", default="", help="自订禁用词表 JSON（透传给 selfcheck／build_docx）")
    ap.add_argument("--manifest", default="", help="附件核对表 JSON（透传给 delivery_check；可用其 --init 生成）")
    ap.add_argument("--cover-allow", default="", help="封面允许的要素，逗号分隔（如 项目名称,团队名称）")
    ap.add_argument("--name-pattern", default="", help="文件名规范正则（如 ^项目-团队-队长$）")
    ap.add_argument("--strict-delivery", action="store_true",
                    help="交付形态核对未通过时**直接判定本次不完成**（默认只大声报告、不阻塞 —— "
                         "因为 Demo 视频／承诺书扫描件等附件不归本管线产，管线无法区分「还没做」和「忘了做」）")
    ap.add_argument("--force", action="store_true", help="紧急出口：透传给 build_docx（交付时必须声明未校验）")
    a = ap.parse_args()

    # ---------- 前置检查：缺文件直接拒绝，不浪费后面几关 ----------
    for label, p in [("任务规则表", a.rules), ("方案 Markdown", a.plan)]:
        if not os.path.exists(p):
            print(f"{NG} 找不到{label}：{p}")
            print(f"{HINT} 没有《任务规则表》＝没问过门禁 → 回第 0 步把 13 项问全。")
            sys.exit(2)

    # ---------- 多 Agent 分工：没走分工就别出稿（SKILL：每次都走，不省略）----------
    if not a.roles and not a.skip_roles:
        print("=" * 64)
        print(f"{NG} 拒绝出稿：未提供《多 Agent 分工记录》（--roles）")
        print()
        print("SKILL 明定：**多 Agent 分工（策略／品牌／触达／文案／财务风控）每次必走、不省略**。")
        print("→ 做法：分工后填 roles.json（格式见 `scripts/role_check.py` 文件头），或小案子加 `--skip-roles`。")
        print("=" * 64)
        sys.exit(1)
    if a.roles and not os.path.exists(a.roles):
        print(f"{NG} 找不到分工记录档：{a.roles}")
        sys.exit(1)

    print("=" * 64)
    print("marketing-playbook · 一键出稿（唯一入口）")
    print(f"  规则表：{a.rules}")
    print(f"  方案稿：{a.plan}")
    print(f"  输  出：{a.out}")
    print("=" * 64)

    failures = []

    # ①–④ 阻断关
    for label, script, blocking in STEPS[:4]:
        if script == "gate_check.py":
            args = [a.rules]
        elif script == "role_check.py":
            args = [a.roles] if a.roles else []
        elif script == "budget_check.py":
            args = [a.budget] if a.budget else [a.plan]
        else:
            args = [a.plan]
        if script == "budget_check.py" and not a.budget:
            # 没给 --budget → 让 budget_check 直接吃方案稿（它会自己抓预算表）
            print(f"\n{'─' * 64}\n{label}（未提供 --budget → 自动从方案稿抓预算表）\n{'─' * 64}")
            rc_auto = run("budget_check.py", [a.plan], f"{label}（自动抓表）")
            if rc_auto != 0:
                # 旧版只记为警告、照样出稿 → 等于把「阻断关」降级了。改回阻断（协议 3 第 7 项）。
                print(f"\n{NG} 预算校验未通过（自动抓表）—— **未生成 .docx**。")
                print(f"{HINT} 建议提供 --budget budget.json（显式、可靠）；修正后重跑。")
                sys.exit(1)
            continue
        rc = run(script, args, label)
        if rc != 0:
            failures.append(f"{label} 未通过（退出码 {rc}）")
            if blocking:
                print(f"\n{NG} 在「{label}」中止 —— **未生成 .docx**。")
                print(f"{HINT} 修正后重跑本指令；同一项连续 2 次不过 → 停手，把问题摊给用户（协议 8）。")
                sys.exit(1)

    # ⑤ 深度诊断（只诊断）
    # depth_check 默认只诊断；--strict-delivery 时才对三项量化硬指标拦（R2-11）
    _dep_args = [a.plan] + (["--strict"] if a.strict_delivery else [])
    run("depth_check.py", _dep_args, STEPS[4][0])

    # ⑥ 出稿
    docx_args = [a.plan, "-o", a.out, "--rules", a.rules, "--title", a.title]
    for flag, val in [("--subtitle", a.subtitle), ("--date", a.date),
                      ("--author", a.author), ("--banned", a.banned)]:
        if val:
            docx_args += [flag, val]
    if a.force:
        docx_args += ["--force"]
    rc = run("build_docx.py", docx_args, STEPS[5][0])

    # ⑦ 交付形态核对（2026-09-17 新增）—— 附件／封面／文件名／占位符
    #    为什么放在出稿**之后**、且默认只报告不拦：
    #      必交附件里有几件（Demo 视频、承诺书签字扫描件）根本不是这条管线能产的，
    #      是人和别的工序做的。管线无法判断「还没做」和「忘了做」，
    #      所以它把缺项**大声列出来**、点名「本次不算完整交付」，
    #      由人或 `--strict-delivery` 决定要不要卡死。
    #      ⛔ 绝不能静默通过 —— 那正是这次要修的「没人管」。
    deliveries_ok = True
    _dc = os.path.join(HERE, "delivery_check.py")
    if os.path.exists(_dc):
        print("\n" + "-" * 64)
        print("⑦ 交付形态核对（delivery_check.py）")
        print("-" * 64)
        dc_args = ["--dir", os.path.dirname(os.path.abspath(a.out))]
        if a.manifest:
            dc_args += ["--manifest", a.manifest]
        if a.cover_allow:
            dc_args += ["--cover-allow", a.cover_allow]
        if a.name_pattern:
            dc_args += ["--name-pattern", a.name_pattern]
        print()
        sys.stdout.flush()   # 子进程直接写同一个 stdout；不 flush 父进程的缓冲输出会跑到它后面
        rc_dc = subprocess.call([sys.executable, _dc] + dc_args)
        if rc_dc != 0:
            deliveries_ok = False
            if a.strict_delivery:
                failures.append("交付形态核对未通过（附件／封面／文件名／占位符，见上表）")
    else:
        deliveries_ok = False
        if a.strict_delivery:
            failures.append("找不到 delivery_check.py —— 交付形态未经核对")

    print("\n" + "=" * 64)
    if rc != 0 or not os.path.exists(a.out):
        print(f"{NG} 出稿失败 —— 没有拿到 .docx，本次不算完成。")
        for f in failures:
            print(f"   · {f}")
        sys.exit(1)

    size = os.path.getsize(a.out)
    if failures:
        # 有未通过／未执行的关卡 → 不算完成（旧版照样印「全链通过」并 exit 0，会误导）
        print(f"{NG} 已出稿，但有未通过／未执行的关卡 —— **不得宣称完成**：")
        for f in failures:
            print(f"   · {f}")
        print("=" * 64)
        sys.exit(1)
    print(f"{OK} 全链通过，已出稿：{a.out}（{size // 1024} KB）")
    if not deliveries_ok:
        print(f"{WARN} 交付形态未全过 —— 见上方 ⑦ 表。**这几件不归本管线产**，"
              f"请人工补齐后再提交；用 `--strict-delivery` 可让它直接卡死。")
    print(f"{HINT} 别忘了：把 12 项《交付自检单》原样输出在回复中（协议 3）。")
    print("=" * 64)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ 已中断（Ctrl+C）。")
        sys.exit(130)
    except Exception as e:  # pragma: no cover
        print(f"\n{NG} 脚本执行出错：{type(e).__name__}: {e}")
        print("→ 依协议 8：环境问题就降级 Markdown 产出，不要卡在这里。")
        sys.exit(2)
