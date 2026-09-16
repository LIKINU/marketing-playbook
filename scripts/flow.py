#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flow.py — 接案流程嚮導（marketing-playbook）

作用：看一眼當前工作目錄，告訴你「現在在第幾步、下一步跑哪條命令」。
      把 references/09-操作流程SOP.md 的流程變成**可被機械檢查的狀態機**。

用法：
    python scripts/flow.py                     # 看當前目錄
    python scripts/flow.py --dir 案子目錄
    python scripts/flow.py --dir . --check     # 另跑安全校驗（selfcheck 當前 plan）

約定的產物檔名（放在同一工作目錄）：
    rules.json     任務規則表（門禁產出）
    skeleton.md    composer 組裝的骨架
    plan.md        模型填空後的方案
    *.docx         run_pipeline 出的稿
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

STEPS = [
    ("S0", "啟動盤點", "讀 SKILL.md / AGENTS.md / 09-SOP；先盤點連接器工具", "python scripts/flow.py"),
    ("S1", "門禁 13 項", "一次問全 → 出《任務規則表》並請用戶確認", "python scripts/gate_check.py rules.json"),
    ("S2", "事實收集", "工具先於爬蟲；每條數字標可信度", "（人工／連接器）"),
    ("S3", "組裝骨架", "★ composer 機械注入知識（打法／模型／學者／案例）", "python scripts/composer.py --rules rules.json --out skeleton.md --tier 标准 --top 5"),
    ("S4", "填空在地化", "模型只補【填】＋ 繁體→簡體（不得刪改注入內容）", "（模型）"),
    ("S5", "交付自檢", "任一硬錯誤＝不得交付", "python scripts/selfcheck.py plan.md"),
    ("S6", "深度診斷", "只診斷，不阻攔", "python scripts/depth_check.py plan.md"),
    ("S7", "出稿", "★ 唯一出口，不過不出稿", 'python scripts/run_pipeline.py --rules rules.json --budget budget.json --plan plan.md -o 方案.docx --title "客戶名 營銷方案" --date YYYY-MM-DD'),
    ("S8", "交付與沉澱", "回覆原樣輸出 12 項自檢單 ＋ 結案復盤", "（人工）"),
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
        return "S1", "未見 rules.json —— 先過門禁 13 項"
    if not has_skel:
        return "S3", "未見 skeleton.md —— 跑 composer 組裝骨架"
    if not has_plan:
        note = "（skeleton.md 仍含【填】，先填空再另存 plan.md）" if "【填】" in _read(skel) else ""
        return "S4", f"未見 plan.md —— 由 skeleton 填完另存 {note}"
    if "【填】" in _read(plan):
        return "S4", "plan.md 仍含【填】—— 補完再自檢"

    # plan 已填 → 跑 selfcheck 判定
    try:
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, "selfcheck.py"), plan],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return "S5", "selfcheck 未過 —— 修硬錯誤後重跑"
    except Exception:
        return "S5", "selfcheck 無法執行 —— 檢查環境"

    if not docx:
        return "S7", "未見 .docx —— 跑 run_pipeline 出稿"
    return "S8", f"已出稿（{docx[0]}）—— 交付回覆輸出 12 項自檢單 + 復盤"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".")
    ap.add_argument("--check", action="store_true", help="另跑安全校驗")
    a = ap.parse_args()
    d = os.path.abspath(a.dir)
    cur, msg = detect(d)

    print("=" * 60)
    print(f"接案流程狀態 · {d}")
    print("=" * 60)
    for sid, name, what, cmd in STEPS:
        mark = "▶" if sid == cur else " "
        print(f" {mark} {sid} {name:<10} {what}")
    print("-" * 60)
    nxt = next(c for c in STEPS if c[0] == cur)
    print(f"📍 當前：{cur} {nxt[1]} —— {msg}")
    print(f"👉 下一步命令：{nxt[3]}")

    if a.check:
        plan = os.path.join(d, "plan.md")
        print("-" * 60)
        if os.path.exists(plan):
            r = subprocess.run(
                [sys.executable, os.path.join(HERE, "selfcheck.py"), plan],
                capture_output=True, text=True,
            )
            tail = [l for l in r.stdout.splitlines() if l.strip()][-1:] or ["(無輸出)"]
            print(f"🔎 selfcheck：{tail[0]}（退出碼 {r.returncode}）")
            sys.exit(0 if r.returncode == 0 else 1)
        print("（--check：未見 plan.md，無可校驗）")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ flow 執行出錯：{type(e).__name__}: {e}")
        sys.exit(2)
