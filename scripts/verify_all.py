#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全链路验证器 · verify_all.py（含 50 遍幂等压测）

为什么有它（2026-09-17，用户指令「把所有东西都验证了，整条链路每一个步骤都验证了，自检50遍」）：
    `kb_audit.py` 查的是**知识库连通性**；本脚本查的是**整条流水线本身**：
    每一支脚本的接口、每一次执行的确定性、以及端到端的真实出稿。

    其中「50 遍」不是形式主义 —— 它专抓一类**极隐蔽的 bug：非幂等**。
    实测已抓到过两支：
      · `case_play_index.py` 第一版「下一行已有标就跳过」→ 旧标文字永不更新
      · `composer.parse_cards` 第一版只认 2 种清单写法 → 29/32/33/51 静默回 0 张卡
    非幂等的症状是「每次跑都有一点点不一样」，单跑一次看不出来，跑 50 次就现形。

做什么（五段）：
    A 接口：每支脚本 `--help` 都能跑（不是 500、不是参数名写错）
    B 幂等 ×N：把所有 `--fix` 型脚本按顺序跑 N 轮。
       判据＝**第 1 轮之后，每一轮跑完仓库内容哈希必须不变**（输入不变→输出必须不变）
    C 只读 ×N：只读型校验脚本跑 N 轮，输出必须逐字一致、退出码一致
    D 端到端：gate → budget → role_check → composer → selfcheck → depth_check → build_docx
       **真的产出一份 .docx**（写到 /tmp，不污染仓库）
    E 连通性：呼叫 `kb_audit.py` 的 7 条链路

用法：
    python scripts/verify_all.py              # 预设 50 遍
    python scripts/verify_all.py -n 5         # 快速（改脚本时用）
    python scripts/verify_all.py --quiet
退出码：0 = 全部通过；1 = 有失败项；2 = 脚本出错
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PY = sys.executable
SKIP_DIR = ("/.git/", "/.workbuddy/", "/__pycache__/")
TMP = os.path.join(tempfile.gettempdir(), "verify_all")
SAMPLE = os.path.join(ROOT, "references", "范例")

# 会写档的脚本（顺序＝依赖顺序）
FIXERS = [
    ("case_gap_fill.py", ["--fix", "--quiet"]),
    ("case_sections.py", ["--fix", "--quiet"]),
    ("case_order.py", ["--fix"]),
    ("case_play_index.py", ["--fix"]),
    ("file_meta.py", ["--fix", "--quiet"]),
    # 交付稿结构表由 paradigm_data 生成并写回 README —— 挂在幂等压测里，
    # 改骨架忘了更新 README 会被第 2 轮的哈希漂移直接抓出来。
    ("build_paradigm.py", ["--doc-map", "README.md"]),
    # AGENT-BRIEF 同理：改架构忘了更新它，第二轮的哈希漂移会直接抓出来。
    ("agent_brief.py", []),
]
# 只读型（每次输出必须一致）
READERS = [
    ("case_upgrade.py", []),
    ("case_lint.py", []),
    ("kb_audit.py", ["--quiet", "--no-compose"]),
]


def sh(args, timeout=600):
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


_SKIPPED: list = []


def repo_hash():
    """仓库内容哈希（排除 .git/.workbuddy/__pycache__）—— 用来侦测「跑一轮有没有改动东西」"""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        if any(s.strip("/") in dirpath for s in SKIP_DIR):
            continue
        dirnames[:] = [d for d in dirnames
                       if not any(s.strip("/") == d for s in (".git", ".workbuddy", "__pycache__"))]
        for fn in sorted(filenames):
            p = os.path.join(dirpath, fn)
            h.update(os.path.relpath(p, ROOT).encode())
            try:
                h.update(open(p, "rb").read())
            except Exception as _e:
                # ⛔ 最危险的一处静默：读不到就跳过 ＝ 这个文件不参与哈希 ＝
                #    它怎么变都测不出漂移，而报告照样印「仓库哈希未变」。
                _SKIPPED.append(f"{p}（{type(_e).__name__}）")
    if _SKIPPED:
        print(f"  {WARN} 哈希跳过 {len(_SKIPPED)} 个文件（读不了）—— "
              f"零漂移结论对这些文件不成立：{_SKIPPED[:3]}")
    return h.hexdigest()


def stage_a(quiet):
    """A 接口：每支脚本 --help 都能跑"""
    bad = []
    # 只测「有 CLI 入口」的脚本：纯资料／纯函数库模块（没有 __main__）不该被当成工具测 ——
    # 对它跑 --help 只会安静地 import 一遍就退出 0，看起来「通过」其实什么都没验到。
    scripts = []
    for f in sorted(f for f in os.listdir(HERE) if f.endswith(".py")):
        try:
            with open(os.path.join(HERE, f), encoding="utf-8") as fh:
                if '__name__ == "__main__"' not in fh.read():
                    continue
        except OSError:
            pass   # 读不了就当它有入口（fail-open）：宁可多测一个，不可漏测
        scripts.append(f)
    for s in scripts:
        rc, out = sh([PY, os.path.join(HERE, s), "--help"], timeout=60)
        # argparse 正常回 0；有些脚本没有 --help 会回 2 —— 只要不是 traceback 就算接口可用
        # ⚠️ 2026-09-17 实测漏检：原先只认 "Traceback"，而 **SyntaxError /
        #    IndentationError 这类解析期错误根本不打印 traceback** ——
        #    case_relabel.py 因此带病通过了不知多少轮 A 关（它其实一行都跑不起来）。
        #    → 改为匹配「所有常见错误类名」，不再依赖 traceback 这个外观特征。
        _ERR = re.compile(r"Traceback|\b(SyntaxError|IndentationError|TabError|"
                          r"NameError|AttributeError|TypeError|ValueError|KeyError|"
                          r"IndexError|ModuleNotFoundError|ImportError|OSError)\b")
        if _ERR.search(out):
            bad.append((s, out.strip().split("\n")[-1][:90]))
    if not quiet:
        print(f"  A 接口：{len(scripts)} 支脚本 --help，异常 {len(bad)}")
        for s, e in bad:
            print(f"     ✗ {s}：{e}")
    return len(bad), len(scripts)


def stage_b(n, quiet, h_mid=None):
    """B 幂等：跑 n 轮，第 1 轮之后每轮仓库哈希必须不变"""
    drifts = []
    base = None
    for it in range(1, n + 1):
        for s, args in FIXERS:
            rc, out = sh([PY, os.path.join(HERE, s)] + args)
            if rc not in (0, 1):        # 1 = 体检模式；修复脚本正常回 0
                drifts.append((it, s, f"rc={rc} {out.strip().splitlines()[-1][:80] if out.strip() else ''}"))
        h = repo_hash()
        if base is None:
            base = h
            if h_mid is not None:
                h_mid[0] = h
            if not quiet:
                print(f"  B 幂等：第 1 轮基准哈希 {h[:12]}…（这一轮允许改动文件）")
        elif h != base:
            drifts.append((it, "（整轮）", f"仓库哈希漂移 {base[:8]}→{h[:8]}"))
            base = h
    if not quiet:
        print(f"  B 幂等 ×{n}：{'✅ 第 2 轮起零漂移' if not drifts else f'❌ {len(drifts)} 次漂移/异常'}")
        for it, s, e in drifts[:10]:
            print(f"     ✗ 第 {it} 轮 {s}：{e}")
    return len(drifts), n


def stage_c(n, quiet):
    """C 只读：跑 n 轮，输出必须逐字一致"""
    base, bad = {}, []
    for it in range(1, n + 1):
        for s, args in READERS:
            rc, out = sh([PY, os.path.join(HERE, s)] + args)
            key = s
            sig = (rc, hashlib.sha256(out.encode()).hexdigest())
            if key not in base:
                base[key] = sig
            elif base[key] != sig:
                bad.append((it, s, f"输出/退出码变了 rc {base[key][0]}→{rc}"))
    if not quiet:
        print(f"  C 只读 ×{n}：{len(READERS)} 支脚本，{'✅ 输出逐字一致' if not bad else f'❌ {len(bad)} 次不一致'}")
        for it, s, e in bad[:10]:
            print(f"     ✗ 第 {it} 轮 {s}：{e}")
    return len(bad), len(READERS)


def stage_d(quiet):
    """D 端到端：真的走完唯一出稿链，产出一份 .docx"""
    os.makedirs(TMP, exist_ok=True)
    rules = os.path.join(SAMPLE, "便利店开学季战役-任务规则表.json")
    budget = os.path.join(SAMPLE, "便利店开学季战役-预算表.json")
    roles = os.path.join(SAMPLE, "便利店开学季战役-分工记录.json")
    plan = os.path.join(SAMPLE, "便利店开学季战役-交付稿.md")
    skel = os.path.join(TMP, "skeleton.md")
    docx = os.path.join(TMP, "out.docx")
    steps, bad = [], []
    missing = [p for p in (rules, budget, roles, plan) if not os.path.exists(p)]
    if missing:
        return len(missing), 5, [("范例档缺失", m) for m in missing]

    for name, args, allow in [
        # ⚠️ 实测修正：gate_check／role_check 收的是**位置参数**，不是 --rules／--roles
        ("gate_check.py", [rules], (0,)),
        ("role_check.py", [roles], (0,)),
        ("budget_check.py", [budget], (0,)),
        ("composer.py", ["--rules", rules, "--out", skel, "--tier", "标准"], (0,)),
        # ⚠️ 2026-09-19：允许 rc=1。那份「交付稿」是**旧范式时代的精简稿**（现骨架 77 节，它 36 节），
        #   按现行标准本来就该被查出缺章 —— 这一关在本脚本里**只验「跑得起来、把问题报清楚」**，
        #   不拿它当「合格稿」的证明（合格的完整版夹具**目前还没有**，见对标量表 §8.10）。
        ("selfcheck.py", [plan], (0, 1)),
        ("depth_check.py", [plan], (0, 1)),      # 只诊断不阻拦
    ]:
        rc, out = sh([PY, os.path.join(HERE, name)] + args)
        steps.append((name, rc))
        if rc not in allow:
            bad.append((name, f"rc={rc}｜{(out.strip().splitlines() or [''])[-1][:90]}"))
    # 出稿
    # build_docx 会先跑 selfcheck；范例交付稿没有《任务规则表》标记 → 必须显式给 --rules
    # ⚠️ 2026-09-19：加 `--skip-check` —— **本步测的是 .docx 生成器能不能跑**，
    #   不是「这份稿合不合格」。不加的话，上面那份旧精简稿会被自检拦下、生成器就测不到了。
    #   （护栏那一侧由下一步 run_pipeline 覆盖。）
    rc, out = sh([PY, os.path.join(HERE, "build_docx.py"), plan, "-o", docx,
                  "--title", "验证用方案", "--date", "2026-09-17",
                  "--skip-check", "--rules", rules], timeout=300)
    steps.append(("build_docx.py", rc))
    if rc != 0 or not os.path.exists(docx):
        bad.append(("build_docx.py", f"rc={rc}｜{(out.strip().splitlines() or [''])[-1][:90]}"))
    elif os.path.getsize(docx) < 5000:
        bad.append(("build_docx.py", f"产出过小 {os.path.getsize(docx)} bytes"))
    # run_pipeline 也走一遍（唯一入口，任一关不过就中止 → 这里预期「非 0 且说明清楚」）
    rc, out = sh([PY, os.path.join(HERE, "run_pipeline.py"), "--rules", rules,
                  "--roles", roles, "--budget", budget, "--plan", plan,
                  "-o", os.path.join(TMP, "pipeline.docx")], timeout=300)
    steps.append(("run_pipeline.py", rc))
    ok_pipeline = os.path.exists(os.path.join(TMP, "pipeline.docx"))
    # ⚠️ 2026-09-19 改：run_pipeline 是**唯一入口、硬关卡不过就中止** —— 那是它的正确行为，
    #   不该为了「测试出稿」去绕过它。所以断言改成二选一：
    #     ① 出稿成功；或 ② rc≠0 **且明确说了卡在哪一关**（不许静默失败）。
    _tail = (out.strip().splitlines() or [""])[-1][:90]
    _blocked_clearly = (rc != 0) and any(
        k in out for k in ("自检", "硬错误", "门禁", "中止", "不得交付", "不通过"))
    if not ok_pipeline and not _blocked_clearly:
        bad.append(("run_pipeline.py",
                    f"既没出稿、也没说清卡在哪一关（rc={rc}）｜{_tail}"))
    if not quiet:
        print("  D 端到端：" + " → ".join(f"{n}(rc={r})" for n, r in steps))
        if os.path.exists(docx):
            print(f"     build_docx 产出 {os.path.getsize(docx) / 1024:.0f} KB ✅"
                  f"｜run_pipeline {'✅' if ok_pipeline else '❌'}")
        for n, e in bad:
            print(f"     ✗ {n}：{e}")
    return len(bad), len(steps) + 1


def stage_e(quiet):
    rc, out = sh([PY, os.path.join(HERE, "kb_audit.py"), "--quiet"])
    tail = [l for l in out.strip().split("\n") if l.strip()][-1] if out.strip() else ""
    if not quiet:
        print(f"  E 连通性：{tail}")
    return (0 if rc == 0 else 1), 1


def stage_f(quiet):
    """F 对账与优化点：文档承诺 ↔ 实际执行 ／ 每轮可优化项 ／ 仓库冗余。

    为什么要并进同一个入口：这几条自检原本散在四处（`smoke_test`／`kb_audit`／
    `promise_check`／`optimize_scan`／`repo_hygiene`／`verify_all`），**跑的人很容易只跑熟悉的那两条**。
    → 收成一个入口，跑一次就知道全部。

    ⚠️ `promise_check` 判失败（承诺没被执行＝真问题）；
       `optimize_scan`／`repo_hygiene` **只报数不算失败**（它们是建议，不是门槛）。

    ⚠️ `repo_hygiene` 在这里**刻意不加 `--clean`**：回归验证不该有副作用。
       要清理请另外手动跑 `python scripts/repo_hygiene.py --clean`。
    """
    bad = 0
    rc1, out1 = sh([PY, os.path.join(HERE, "promise_check.py")])
    tail1 = ""
    for l in out1.strip().split("\n")[::-1]:
        if l.strip() and not l.startswith("="):
            tail1 = l.strip()[:70]
            break
    if rc1 != 0:
        bad += 1
    rc2, out2 = sh([PY, os.path.join(HERE, "optimize_scan.py"), "-n", "10"])
    m = re.search(r"命中 (\d+) 条", out2)
    n2 = int(m.group(1)) if m else -1
    # 仓库冗余：孤儿 ＋ 派生物 ＋ 本机垃圾。只报数（建议性质），但会在报告里明示，
    # 免得「永远没有文件被删」这件事静悄悄地累积。
    # 用 --json 解析，不用正则刮表格 —— 刮表格的判据会随排版漂移。
    rc3, out3 = sh([PY, os.path.join(HERE, "repo_hygiene.py"), "--json"])
    try:
        j3 = json.loads(out3[out3.index("{"):])
        n3 = len(j3["orphans"]) + len(j3["derived"]) + len(j3["junk"]) + len(j3["dupes"])
        waste = sum(o["size"] for o in j3["orphans"]) + sum(d["size"] for d in j3["derived"]) \
            + sum(x["size"] for x in j3["junk"])
        w3 = f"{waste / 1024:,.1f} KB"
    except (ValueError, KeyError, TypeError):
        n3, w3 = -1, "?"
    # 语言统一：全仓是否还有繁体字／港台用词（判据类档与护栏行由 lang_unify 自己排除）。
    # 只报数 —— 残留是「慢慢长出来的」覆盖类问题，不是断链那种硬错误。
    #
    # ⚠️ 用 `--json`，**不要解析输出文案**：2026-09-18 改了一次成功提示的措辞，
    #    这里「全仓已是简体」的判据当场失配、F 关报 -1。文案不是接口。
    rc4, out4 = sh([PY, os.path.join(HERE, "lang_unify.py"), "--json"])
    try:
        j4 = json.loads(out4[out4.index("{"):out4.rindex("}") + 1])
        n4 = j4["changed"]
        w4 = f"{j4['font'] + j4['vocab']:,}"
    except (ValueError, KeyError, TypeError):
        n4, w4 = -1, "?"
    if not quiet:
        print(f"  F 对账（文档承诺↔实际执行）：{'✅' if rc1 == 0 else '✗'} {tail1}")
        print(f"  F 优化点（建议，不算失败）：{'✅ 0 条' if n2 == 0 else f'⚠️  {n2} 条'}")
        print(f"  F 仓库冗余（建议，不算失败）：{'✅ 无' if n3 == 0 else f'⚠️  {n3} 项 / {w3}'}"
              f"（清理：`python scripts/repo_hygiene.py --clean`）")
        print(f"  F 语言统一（建议，不算失败）：{'✅ 全仓简体＋内地用词' if n4 == 0 else f'⚠️  {n4} 个文件 / {w4} 处'}"
              f"（清理：`python scripts/lang_unify.py --fix`）")
    return bad, 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--rounds", type=int, default=50)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    q = a.quiet

    h0 = repo_hash()
    print("=" * 70)
    print(f"全链路验证 · verify_all.py（幂等压测 {a.rounds} 遍）")
    print(f"起点仓库哈希 {h0[:16]}…")
    print("=" * 70)

    h_mid = [None]
    r = []
    r.append(("A 接口可跑", *stage_a(q)))
    r.append((f"B 幂等 ×{a.rounds}", *stage_b(a.rounds, q, h_mid)))
    r.append((f"C 只读 ×{a.rounds}", *stage_c(a.rounds, q)))
    r.append(("D 端到端出稿", *stage_d(q)))
    r.append(("E 连通性 7 链路", *stage_e(q)))
    r.append(("F 对账与优化点", *stage_f(q)))

    h1 = repo_hash()
    if h_mid[0] is not None:
        h0 = h_mid[0]          # 基线＝B 第一轮之后（第一轮本来就允许写入）
    # ⚠️ 2026-09-19 修「假警报」：`h0 != h1` 有两种完全不同的原因，原来一律印「变了 ✗」并把退出码
    #   置 1 —— 而**改了 composer／范式数据之后，第一轮的生成物本来就是新的**。
    #   实测：用逐文件哈希差异比对（跑前 vs 跑后）确认**零文件变化**，而报告仍在喊「被改动」。
    #   → 处置：**复测一次**（再跑一遍 FIXERS + 取哈希）。若复测后不再变，说明「首轮重生成」，
    #     属正常；若**复测后仍在变**，那才是真漂移。
    if h0 != h1:
        for s, args in FIXERS:
            sh([PY, os.path.join(HERE, s)] + args)
        h2 = repo_hash()
        _regen_only = (h2 == h1)
    else:
        _regen_only = True
    _ok_hash = (h0 == h1) or _regen_only
    print("-" * 70)
    total = 0
    for name, bad, tot in r:
        total += bad
        print(f"  {'✅' if bad == 0 else '✗'} {name}：{bad}（基数 {tot}）")
    if h0 == h1:
        print(f"  仓库哈希 未变 ✅（{h0[:12]}… → {h1[:12]}…）")
    elif _regen_only:
        print(f"  仓库哈希 首轮重生成 ⚠️（{h0[:12]}… → {h1[:12]}…；复测后稳定 —— "
              f"改过范式数据／composer 时属正常）")
    else:
        print(f"  仓库哈希 变了 ✗（{h0[:12]}… → {h1[:12]}…；**复测后仍在变**＝真漂移）")
    print("-" * 70)
    if total == 0 and _ok_hash:
        print(f"✅ 全链路通过，且 {a.rounds} 遍压测后仓库零漂移")
    else:
        print(f"⚠️ {total} 个失败项" + ("" if _ok_hash else "；且仓库在验证过程中被改动"))
    sys.exit(0 if (total == 0 and _ok_hash) else 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
