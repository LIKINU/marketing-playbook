#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
冒烟測試 · smoke_test.py —— 一條命令驗證整條鏈沒壞

為什麼有它（2026-09-16）：改腳本後一直靠手工敲命令驗證，沒有回歸保障。
本檔把「該過的過、該攔的攔」固化成一次跑完的檢查。

用法：python scripts/smoke_test.py
退出碼：0 = 全綠；1 = 有失敗
"""

import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
PY = sys.executable
from _common import OK, NG, WARN, HINT, INFO   # noqa: E402  统一符号，不要在各自文件里重定义


def run(script, args):
    return subprocess.run([PY, os.path.join(HERE, script)] + args,
                          capture_output=True, text=True).returncode


def main():
    ex = os.path.join(ROOT, "references", "范例")
    rules = os.path.join(ex, "便利店开学季战役-任务规则表.json")
    roles = os.path.join(ex, "便利店开学季战役-分工记录.json")
    budget = os.path.join(ex, "便利店开学季战役-预算表.json")
    plan = os.path.join(ex, "便利店开学季战役-交付稿.md")
    tmp = tempfile.mkdtemp(prefix="mp-smoke-")

    checks = []  # (說明, 期望退出碼, 實得)

    def chk(name, rc, want=0):
        checks.append((name, want, rc))

    # ① 該過的
    chk("門禁（正常規則表）", run("gate_check.py", [rules]), 0)
    chk("分工（正常分工記錄）", run("role_check.py", [roles]), 0)
    chk("預算（JSON）", run("budget_check.py", [budget]), 0)
    chk("預算（3 列表格·從交付稿抓）", run("budget_check.py", [plan]), 0)
    chk("自檢（簡體標杆稿）", run("selfcheck.py", [plan]), 0)
    chk("深度診斷（只診斷·恆 0）", run("depth_check.py", [plan]), 0)

    # ② composer 三檔都能出骨架
    for tier in ["速览", "标准", "G端"]:
        out = os.path.join(tmp, f"sk-{tier}.md")
        chk(f"組裝器（{tier} 档）", run("composer.py", [ "--rules", rules, "--out", out, "--tier", tier]), 0)

    # ③ 該攔的（負向）
    bad = os.path.join(tmp, "bad.md")
    open(bad, "w", encoding="utf-8").write("# 空殼\n## 二 · 策略\n- 一句話\n")
    chk("自檢：空殼稿應被攔", run("selfcheck.py", [bad]), 1)

    # 繁体稿應被攔（簡體硬門檻）
    trad = os.path.join(tmp, "trad.md")
    open(trad, "w", encoding="utf-8").write(
        "# 測試\n## 二 · 策略\n這是一份繁體稿，應該被攔下來，因為規則要求簡體字交付。" * 3)
    chk("自檢：繁體稿應被攔", run("selfcheck.py", [trad]), 1)

    # 未填骨架應被攔（【填】殘留）
    skel = os.path.join(tmp, "skel.md")
    run("composer.py", ["--rules", rules, "--out", skel, "--tier", "标准"])
    chk("自檢：未填骨架應被攔", run("selfcheck.py", [skel]), 1)

    # ④ 輸出
    print("=" * 60)
    print("冒煙測試 · marketing-playbook")
    print("=" * 60)
    fails = 0
    for name, want, got in checks:
        good = (got == want)
        fails += 0 if good else 1
        print(f"  {OK if good else NG} {name}：期望 {want}，實得 {got}")
    print("-" * 60)
    if fails:
        print(f"{NG} {fails}/{len(checks)} 項失敗")
        sys.exit(1)
    print(f"{OK} 全部通過（{len(checks)} 項）")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"{NG} 執行出錯：{type(e).__name__}: {e}")
        sys.exit(2)
