#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
冒烟测试 · smoke_test.py —— 一条命令验证整条链没坏

为什么有它（2026-09-16）：改脚本后一直靠手工敲命令验证，没有回归保障。
本档把「该过的过、该拦的拦」固化成一次跑完的检查。

用法：python scripts/smoke_test.py
退出码：0 = 全绿；1 = 有失败
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

    checks = []  # (说明, 期望退出码, 实得)

    def chk(name, rc, want=0):
        checks.append((name, want, rc))

    # ① 该过的
    chk("门禁（正常规则表）", run("gate_check.py", [rules]), 0)
    chk("分工（正常分工记录）", run("role_check.py", [roles]), 0)
    chk("预算（JSON）", run("budget_check.py", [budget]), 0)
    chk("预算（3 列表格·从交付稿抓）", run("budget_check.py", [plan]), 0)
    # ⚠️ 2026-09-19 修：这里**原来断言 `rc==0`** —— 而那等于**逼着判据保持宽松**才能通过。
    #   实测：那份「交付稿」是**旧范式时代的精简稿**（现骨架 77 节，它只有 36 节），
    #   按现行标准本来就该被查出缺章（当日实测 22 项硬错误，绝大多数是**真的缺**）。
    #   → 改成只断言它**不因「护栏类」原因被误拦**（这才是这条测试的本意）：
    #     · 不因**繁体**被拦（统一简体后仍要挡外部贴进来的繁体，但不能把简体稿判成繁体）；
    #     · 不因**未填占位**被拦。
    #   ⚠️ **遗留缺口（已知）**：这样一来，**没有任何夹具能证明「一份合格的完整版方案能通过」**。
    #     下一件该做的事就是补一份**完整版通过夹具** —— 见 `优化轮次/对标量表-v2` §8.10。
    _p = subprocess.run([PY, os.path.join(HERE, "selfcheck.py"), plan],
                        capture_output=True, text=True)
    _txt = _p.stdout + _p.stderr
    chk("自检（精简版标杆稿·繁体不误判）",
        1 if re.search(r"❌[^\n]*繁体", _txt) else 0, 0)
    chk("自检（精简版标杆稿·占位不误判）",
        1 if re.search(r"❌[^\n]*【填】", _txt) else 0, 0)
    chk("深度诊断（只诊断·恒 0）", run("depth_check.py", [plan]), 0)

    # ② composer 三档都能出骨架
    for tier in ["速览", "标准", "G端"]:
        out = os.path.join(tmp, f"sk-{tier}.md")
        chk(f"组装器（{tier} 档）", run("composer.py", [ "--rules", rules, "--out", out, "--tier", tier]), 0)

    # ③ 该拦的（负向）
    bad = os.path.join(tmp, "bad.md")
    open(bad, "w", encoding="utf-8").write("# 空壳\n## 二 · 策略\n- 一句话\n")
    chk("自检：空壳稿应被拦", run("selfcheck.py", [bad]), 1)

    # 繁体稿应被拦（简体硬门槛）
    # ⚠️ 下面这几行**必须保持繁体** —— 它们是「繁体稿应被拦」这个测试的**负向夹具**。
    #    全仓统一简体后，这条测试的意义变成「挡外部贴进来的繁体」，比以前更需要。
    #    行尾那个 lang-keep-trad 注释标记，是给 scripts/lang_unify.py 的护栏：
    #    它会跳过带这个标记的行，免得这个夹具被转成简体、测试静默失效。
    trad = os.path.join(tmp, "trad.md")
    open(trad, "w", encoding="utf-8").write(
        "# 測試\n## 二 · 策略\n這是一份繁體稿，應該被攔下來，因為規則要求簡體字交付。" * 3)  # lang-keep-trad
    chk("自检：繁体稿应被拦", run("selfcheck.py", [trad]), 1)

    # 未填骨架应被拦（【填】残留）
    skel = os.path.join(tmp, "skel.md")
    run("composer.py", ["--rules", rules, "--out", skel, "--tier", "标准"])
    chk("自检：未填骨架应被拦", run("selfcheck.py", [skel]), 1)

    # ④ 输出
    print("=" * 60)
    print("冒烟测试 · marketing-playbook")
    print("=" * 60)
    fails = 0
    for name, want, got in checks:
        good = (got == want)
        fails += 0 if good else 1
        print(f"  {OK if good else NG} {name}：期望 {want}，实得 {got}")
    print("-" * 60)
    if fails:
        print(f"{NG} {fails}/{len(checks)} 项失败")
        sys.exit(1)
    print(f"{OK} 全部通过（{len(checks)} 项）")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"{NG} 执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
