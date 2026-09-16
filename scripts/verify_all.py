#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全鏈路驗證器 · verify_all.py（含 50 遍冪等壓測）

為什麼有它（2026-09-17，用戶指令「把所有东西都验证了，整条链路每一个步骤都验证了，自检50遍」）：
    `kb_audit.py` 查的是**知識庫連通性**；本腳本查的是**整條流水線本身**：
    每一支腳本的介面、每一次執行的確定性、以及端到端的真實出稿。

    其中「50 遍」不是形式主義 —— 它專抓一類**極隱蔽的 bug：非冪等**。
    實測已抓到過兩支：
      · `case_play_index.py` 第一版「下一行已有標就跳過」→ 舊標文字永不更新
      · `composer.parse_cards` 第一版只認 2 種清單寫法 → 29/32/33/51 靜默回 0 張卡
    非冪等的症狀是「每次跑都有一點點不一樣」，單跑一次看不出來，跑 50 次就現形。

做什麼（五段）：
    A 介面：每支腳本 `--help` 都能跑（不是 500、不是參數名寫錯）
    B 冪等 ×N：把所有 `--fix` 型腳本按順序跑 N 輪。
       判據＝**第 1 輪之後，每一輪跑完倉庫內容哈希必須不變**（輸入不變→輸出必須不變）
    C 只讀 ×N：只讀型校驗腳本跑 N 輪，輸出必須逐字一致、退出碼一致
    D 端到端：gate → budget → role_check → composer → selfcheck → depth_check → build_docx
       **真的產出一份 .docx**（寫到 /tmp，不污染倉庫）
    E 連通性：呼叫 `kb_audit.py` 的 7 條鏈路

用法：
    python scripts/verify_all.py              # 預設 50 遍
    python scripts/verify_all.py -n 5         # 快速（改腳本時用）
    python scripts/verify_all.py --quiet
退出碼：0 = 全部通過；1 = 有失敗項；2 = 腳本出錯
"""

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PY = sys.executable
SKIP_DIR = ("/.git/", "/.workbuddy/", "/__pycache__/")
TMP = os.path.join(tempfile.gettempdir(), "verify_all")
SAMPLE = os.path.join(ROOT, "references", "范例")

# 會寫檔的腳本（順序＝依賴順序）
FIXERS = [
    ("case_gap_fill.py", ["--fix", "--quiet"]),
    ("case_sections.py", ["--fix", "--quiet"]),
    ("case_order.py", ["--fix"]),
    ("case_play_index.py", ["--fix"]),
    ("file_meta.py", ["--fix", "--quiet"]),
]
# 只讀型（每次輸出必須一致）
READERS = [
    ("case_upgrade.py", []),
    ("case_lint.py", []),
    ("kb_audit.py", ["--quiet", "--no-compose"]),
]


def sh(args, timeout=600):
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def repo_hash():
    """倉庫內容哈希（排除 .git/.workbuddy/__pycache__）—— 用來偵測「跑一輪有沒有改動東西」"""
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
            except Exception:
                pass
    return h.hexdigest()


def stage_a(quiet):
    """A 介面：每支腳本 --help 都能跑"""
    bad = []
    scripts = sorted(f for f in os.listdir(HERE) if f.endswith(".py"))
    for s in scripts:
        rc, out = sh([PY, os.path.join(HERE, s), "--help"], timeout=60)
        # argparse 正常回 0；有些腳本沒有 --help 會回 2 —— 只要不是 traceback 就算介面可用
        if "Traceback" in out:
            bad.append((s, out.strip().split("\n")[-1][:90]))
    if not quiet:
        print(f"  A 介面：{len(scripts)} 支腳本 --help，異常 {len(bad)}")
        for s, e in bad:
            print(f"     ✗ {s}：{e}")
    return len(bad), len(scripts)


def stage_b(n, quiet, h_mid=None):
    """B 冪等：跑 n 輪，第 1 輪之後每輪倉庫哈希必須不變"""
    drifts = []
    base = None
    for it in range(1, n + 1):
        for s, args in FIXERS:
            rc, out = sh([PY, os.path.join(HERE, s)] + args)
            if rc not in (0, 1):        # 1 = 體檢模式；修復腳本正常回 0
                drifts.append((it, s, f"rc={rc} {out.strip().splitlines()[-1][:80] if out.strip() else ''}"))
        h = repo_hash()
        if base is None:
            base = h
            if h_mid is not None:
                h_mid[0] = h
            if not quiet:
                print(f"  B 冪等：第 1 輪基準哈希 {h[:12]}…（這一輪允許改動檔案）")
        elif h != base:
            drifts.append((it, "（整輪）", f"倉庫哈希漂移 {base[:8]}→{h[:8]}"))
            base = h
    if not quiet:
        print(f"  B 冪等 ×{n}：{'✅ 第 2 輪起零漂移' if not drifts else f'❌ {len(drifts)} 次漂移/異常'}")
        for it, s, e in drifts[:10]:
            print(f"     ✗ 第 {it} 輪 {s}：{e}")
    return len(drifts), n


def stage_c(n, quiet):
    """C 只讀：跑 n 輪，輸出必須逐字一致"""
    base, bad = {}, []
    for it in range(1, n + 1):
        for s, args in READERS:
            rc, out = sh([PY, os.path.join(HERE, s)] + args)
            key = s
            sig = (rc, hashlib.sha256(out.encode()).hexdigest())
            if key not in base:
                base[key] = sig
            elif base[key] != sig:
                bad.append((it, s, f"輸出/退出碼變了 rc {base[key][0]}→{rc}"))
    if not quiet:
        print(f"  C 只讀 ×{n}：{len(READERS)} 支腳本，{'✅ 輸出逐字一致' if not bad else f'❌ {len(bad)} 次不一致'}")
        for it, s, e in bad[:10]:
            print(f"     ✗ 第 {it} 輪 {s}：{e}")
    return len(bad), len(READERS)


def stage_d(quiet):
    """D 端到端：真的走完唯一出稿鏈，產出一份 .docx"""
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
        return len(missing), 5, [("範例檔缺失", m) for m in missing]

    for name, args, allow in [
        # ⚠️ 實測修正：gate_check／role_check 收的是**位置參數**，不是 --rules／--roles
        ("gate_check.py", [rules], (0,)),
        ("role_check.py", [roles], (0,)),
        ("budget_check.py", [budget], (0,)),
        ("composer.py", ["--rules", rules, "--out", skel, "--tier", "标准"], (0,)),
        ("selfcheck.py", [plan], (0,)),
        ("depth_check.py", [plan], (0, 1)),      # 只診斷不阻攔
    ]:
        rc, out = sh([PY, os.path.join(HERE, name)] + args)
        steps.append((name, rc))
        if rc not in allow:
            bad.append((name, f"rc={rc}｜{(out.strip().splitlines() or [''])[-1][:90]}"))
    # 出稿
    # build_docx 會先跑 selfcheck；範例交付稿沒有《任務規則表》標記 → 必須顯式給 --rules
    rc, out = sh([PY, os.path.join(HERE, "build_docx.py"), plan, "-o", docx,
                  "--title", "验证用方案", "--date", "2026-09-17",
                  "--rules", rules], timeout=300)
    steps.append(("build_docx.py", rc))
    if rc != 0 or not os.path.exists(docx):
        bad.append(("build_docx.py", f"rc={rc}｜{(out.strip().splitlines() or [''])[-1][:90]}"))
    elif os.path.getsize(docx) < 5000:
        bad.append(("build_docx.py", f"產出過小 {os.path.getsize(docx)} bytes"))
    # run_pipeline 也走一遍（唯一入口，任一關不過就中止 → 這裡預期「非 0 且說明清楚」）
    rc, out = sh([PY, os.path.join(HERE, "run_pipeline.py"), "--rules", rules,
                  "--roles", roles, "--budget", budget, "--plan", plan,
                  "-o", os.path.join(TMP, "pipeline.docx")], timeout=300)
    steps.append(("run_pipeline.py", rc))
    ok_pipeline = os.path.exists(os.path.join(TMP, "pipeline.docx"))
    if not ok_pipeline:
        bad.append(("run_pipeline.py", f"未產出 .docx（rc={rc}）｜{out.strip().splitlines()[-1][:80]}"))
    if not quiet:
        print("  D 端到端：" + " → ".join(f"{n}(rc={r})" for n, r in steps))
        if os.path.exists(docx):
            print(f"     build_docx 產出 {os.path.getsize(docx) / 1024:.0f} KB ✅"
                  f"｜run_pipeline {'✅' if ok_pipeline else '❌'}")
        for n, e in bad:
            print(f"     ✗ {n}：{e}")
    return len(bad), len(steps) + 1


def stage_e(quiet):
    rc, out = sh([PY, os.path.join(HERE, "kb_audit.py"), "--quiet"])
    tail = [l for l in out.strip().split("\n") if l.strip()][-1] if out.strip() else ""
    if not quiet:
        print(f"  E 連通性：{tail}")
    return (0 if rc == 0 else 1), 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--rounds", type=int, default=50)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    q = a.quiet

    h0 = repo_hash()
    print("=" * 70)
    print(f"全鏈路驗證 · verify_all.py（冪等壓測 {a.rounds} 遍）")
    print(f"起點倉庫哈希 {h0[:16]}…")
    print("=" * 70)

    h_mid = [None]
    r = []
    r.append(("A 介面可跑", *stage_a(q)))
    r.append((f"B 冪等 ×{a.rounds}", *stage_b(a.rounds, q, h_mid)))
    r.append((f"C 只讀 ×{a.rounds}", *stage_c(a.rounds, q)))
    r.append(("D 端到端出稿", *stage_d(q)))
    r.append(("E 連通性 7 鏈路", *stage_e(q)))

    h1 = repo_hash()
    if h_mid[0] is not None:
        h0 = h_mid[0]          # 基線＝B 第一輪之後（第一輪本來就允許寫入）
    print("-" * 70)
    total = 0
    for name, bad, tot in r:
        total += bad
        print(f"  {'✅' if bad == 0 else '✗'} {name}：{bad}（基數 {tot}）")
    print(f"  倉庫哈希 {'未變 ✅' if h0 == h1 else '變了 ✗'}（{h0[:12]}… → {h1[:12]}…）")
    print("-" * 70)
    if total == 0 and h0 == h1:
        print(f"✅ 全鏈路通過，且 {a.rounds} 遍壓測後倉庫零漂移")
    else:
        print(f"⚠️ {total} 個失敗項" + ("" if h0 == h1 else "；且倉庫在驗證過程中被改動"))
    sys.exit(0 if (total == 0 and h0 == h1) else 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 執行出錯：{type(e).__name__}: {e}")
        sys.exit(2)
