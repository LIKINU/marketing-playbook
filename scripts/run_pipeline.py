#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一鍵出稿 · run_pipeline.py —— **本 skill 唯一的出稿入口**

為什麼要有這個檔
----------------
單獨跑四個腳本時，執行者很容易「忘記跑」「選擇性跑」「跑不過就手工繞過」。
本檔把整條鏈串起來，**任何一關不過就中止、不生成 .docx**。

    ① gate_check     門禁 13 項 + 任務規則表已確認
    ② role_check     多 Agent 分工（5 角色產出 + 裁決記錄）—— **沒走分工就不出稿**
    ③ budget_check   預算分項加總 = 合計
    ④ selfcheck      結構 / 自檢單 / 內部文檔洩漏 / 禁用詞 / 核心方法論要素 / 知識庫引用 / 簡體
    ⑤ depth_check    9 個深度維度（**只診斷，不阻攔**）
    ⑥ build_docx     出稿（內部會再跑一次 selfcheck）

用法
----
    python scripts/run_pipeline.py \\
        --rules  rules.json \\
        --budget budget.json \\
        --plan   plan.md \\
        -o       方案.docx \\
        --title  "客戶名 營銷方案" [--subtitle "副標題"] [--date 2026-09-16]

參數
----
    --rules    《任務規則表》JSON（**必填**；沒問過門禁就沒有它 → 直接拒絕）
    --roles    多 Agent 分工記錄 JSON（**必填**；沒走分工就不出稿。格式見 role_check.py 檔頭）
    --skip-roles 跳過分工校驗（僅小案子或用戶同意時；交付時請聲明）
    --budget   預算表 JSON（建議填；缺省會警告——協議 3 第 7 項要求預算能對上）
    --plan     方案 Markdown（**必填**）
    -o         輸出 .docx 路徑（**必填**）
    --title    文檔標題（預設簡體「营销方案」）；--subtitle 副標題；--date 日期；--author 署名
    --banned   自訂禁用詞表 JSON（透傳 selfcheck／build_docx）
    --force    緊急出口：透傳 build_docx 跳過自檢（交付時必須聲明未校驗）

退出碼
------
    0 = 全鏈通過，已出稿 ｜ 1 = 有硬錯誤，**未出稿** ｜ 2 = 環境問題（缺檔案／缺依賴）

沒有代碼執行能力的平台：退回 Markdown 協議（手工跑 §六 清單 + 原樣輸出 12 項自檢單）。
**降級不等於跳步。**
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OK, NG, HINT = "✅", "❌", "→"

STEPS = [
    # (顯示名, 腳本, 是否阻斷)
    ("① 門禁校驗（gate_check）", "gate_check.py", True),
    ("② 分工校驗（role_check）", "role_check.py", True),
    ("③ 預算校驗（budget_check）", "budget_check.py", True),
    ("④ 交付前自檢（selfcheck）", "selfcheck.py", True),
    ("⑤ 深度診斷（depth_check，只診斷）", "depth_check.py", False),
    ("⑥ 出稿（build_docx）", "build_docx.py", True),
]


def run(script: str, args: list, label: str) -> int:
    path = os.path.join(HERE, script)
    if not os.path.exists(path):
        print(f"{NG} 找不到腳本：{path}")
        return 2
    print(f"\n{'─' * 64}\n{label}\n{'─' * 64}")
    r = subprocess.run([sys.executable, path] + args)
    return r.returncode


def main():
    ap = argparse.ArgumentParser(description="marketing-playbook 唯一出稿入口")
    ap.add_argument("--rules", required=True, help="《任務規則表》JSON（必填）")
    ap.add_argument("--roles", default="", help="多 Agent 分工記錄 JSON（**不提供會拒絕出稿**）")
    ap.add_argument("--skip-roles", action="store_true", help="跳過分工校驗（僅小案子或用戶同意時）")
    ap.add_argument("--budget", help="預算表 JSON（建議填）")
    ap.add_argument("--plan", required=True, help="方案 Markdown（必填）")
    ap.add_argument("-o", "--out", required=True, help="輸出 .docx（必填）")
    ap.add_argument("--title", default="营销方案")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--date", default="")
    ap.add_argument("--author", default="")
    ap.add_argument("--banned", default="", help="自訂禁用詞表 JSON（透傳給 selfcheck／build_docx）")
    ap.add_argument("--force", action="store_true", help="緊急出口：透傳給 build_docx（交付時必須聲明未校驗）")
    a = ap.parse_args()

    # ---------- 前置檢查：缺檔案直接拒絕，不浪費後面幾關 ----------
    for label, p in [("任務規則表", a.rules), ("方案 Markdown", a.plan)]:
        if not os.path.exists(p):
            print(f"{NG} 找不到{label}：{p}")
            print(f"{HINT} 沒有《任務規則表》＝沒問過門禁 → 回第 0 步把 13 項問全。")
            sys.exit(2)

    # ---------- 多 Agent 分工：沒走分工就別出稿（SKILL：每次都走，不省略）----------
    if not a.roles and not a.skip_roles:
        print("=" * 64)
        print(f"{NG} 拒絕出稿：未提供《多 Agent 分工記錄》（--roles）")
        print()
        print("SKILL 明定：**多 Agent 分工（策略／品牌／觸達／文案／財務風控）每次必走、不省略**。")
        print("→ 做法：分工後填 roles.json（格式見 `scripts/role_check.py` 檔頭），或小案子加 `--skip-roles`。")
        print("=" * 64)
        sys.exit(1)
    if a.roles and not os.path.exists(a.roles):
        print(f"{NG} 找不到分工記錄檔：{a.roles}")
        sys.exit(1)

    print("=" * 64)
    print("marketing-playbook · 一鍵出稿（唯一入口）")
    print(f"  規則表：{a.rules}")
    print(f"  方案稿：{a.plan}")
    print(f"  輸  出：{a.out}")
    print("=" * 64)

    failures = []

    # ①–④ 阻斷關
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
            # 沒給 --budget → 讓 budget_check 直接吃方案稿（它會自己抓預算表）
            print(f"\n{'─' * 64}\n{label}（未提供 --budget → 自動從方案稿抓預算表）\n{'─' * 64}")
            rc_auto = run("budget_check.py", [a.plan], f"{label}（自動抓表）")
            if rc_auto != 0:
                # 舊版只記為警告、照樣出稿 → 等於把「阻斷關」降級了。改回阻斷（協議 3 第 7 項）。
                print(f"\n{NG} 預算校驗未通過（自動抓表）—— **未生成 .docx**。")
                print(f"{HINT} 建議提供 --budget budget.json（顯式、可靠）；修正後重跑。")
                sys.exit(1)
            continue
        rc = run(script, args, label)
        if rc != 0:
            failures.append(f"{label} 未通過（退出碼 {rc}）")
            if blocking:
                print(f"\n{NG} 在「{label}」中止 —— **未生成 .docx**。")
                print(f"{HINT} 修正後重跑本指令；同一項連續 2 次不過 → 停手，把問題攤給使用者（協議 8）。")
                sys.exit(1)

    # ⑤ 深度診斷（只診斷）
    run("depth_check.py", [a.plan], STEPS[4][0])

    # ⑥ 出稿
    docx_args = [a.plan, "-o", a.out, "--rules", a.rules, "--title", a.title]
    for flag, val in [("--subtitle", a.subtitle), ("--date", a.date),
                      ("--author", a.author), ("--banned", a.banned)]:
        if val:
            docx_args += [flag, val]
    if a.force:
        docx_args += ["--force"]
    rc = run("build_docx.py", docx_args, STEPS[5][0])

    print("\n" + "=" * 64)
    if rc != 0 or not os.path.exists(a.out):
        print(f"{NG} 出稿失敗 —— 沒有拿到 .docx，本次不算完成。")
        for f in failures:
            print(f"   · {f}")
        sys.exit(1)

    size = os.path.getsize(a.out)
    if failures:
        # 有未通過／未執行的關卡 → 不算完成（舊版照樣印「全鏈通過」並 exit 0，會誤導）
        print(f"{NG} 已出稿，但有未通過／未執行的關卡 —— **不得宣稱完成**：")
        for f in failures:
            print(f"   · {f}")
        print("=" * 64)
        sys.exit(1)
    print(f"{OK} 全鏈通過，已出稿：{a.out}（{size // 1024} KB）")
    print(f"{HINT} 別忘了：把 12 項《交付自檢單》原樣輸出在回覆中（協議 3）。")
    print("=" * 64)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ 已中斷（Ctrl+C）。")
        sys.exit(130)
    except Exception as e:  # pragma: no cover
        print(f"\n{NG} 腳本執行出錯：{type(e).__name__}: {e}")
        print("→ 依協議 8：環境問題就降級 Markdown 產出，不要卡在這裡。")
        sys.exit(2)
