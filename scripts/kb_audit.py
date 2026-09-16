#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知識庫「連通性」審計 · kb_audit.py

為什麼有它（2026-09-17，用戶質問）：
    「我不是让你质检了很多很多次了吗？为什么还是有这么多问题」

    根因：**既有的 6 個校驗腳本查的全是「檔案內性質」，沒有一個查「跨檔案連通性」。**
      · file_meta      → 這檔的檔頭五欄對不對
      · case_sections  → 這檔的章節標題一致嗎
      · case_order     → 這張卡的要素順序對嗎
      · case_upgrade   → 這張卡五要素齊、字夠 2500 嗎
      · case_lint      → 這張卡有沒有寫公司背景
      · smoke_test     → 幾個腳本還能跑嗎
    → 結果：60/60 檔頭合規、51/51 章節一致、409/409 卡達標、12/12 冒煙全綠，
      而 `composer.py`（唯一的產出引擎）還在印「來源 cases/xx.md，請展開…」這種占位符。
      **零件全合格，機器的傳動軸是斷的，而沒有一支儀器量傳動軸。**

本腳本量「傳動軸」：把知識庫當**網絡**看，逐條查「引用能不能走到終點」。

六類檢查（＝六條必須通的鏈路）：
    L1 檔案引用可解析 —— 全庫所有 `references/xx` / `cases/xx` 引用，目標檔存在嗎
       （只查「檔在不在」是不夠的，所以還有 L2–L5 的「走得到內容嗎」）
    L2 打法 → 案例 —— 104 條打法裡，有幾條的 `**案例**` 行能指到**具體某張卡**（指名品牌）
    L3 案例 → 打法 —— 649 張卡裡，有幾張能被至少一條打法指到（反向可達）
    L4 交付物注入 —— 跑一次 composer，數骨架裡實際注入的**真實卡片內容**條數 vs 占位符條數
    L5 模型 → 打法 —— `knowledge_map.json` 引用的模型碼，在 03 手冊裡真的存在嗎（死條目掃描）
    L6 全量回歸 —— 把 6 個既有校驗腳本一次跑完（以前是「改哪查哪」，現在每次全跑）

用法：
    python scripts/kb_audit.py                 # 完整審計（含 L4 實跑 composer）
    python scripts/kb_audit.py --no-compose    # 跳過 L4（不想等 composer）
    python scripts/kb_audit.py --quiet         # 只印結論與失敗項
退出碼：0 = 六條鏈路都通；1 = 有鏈路斷（會列出斷點數）；2 = 腳本出錯
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
REF = os.path.join(ROOT, "references")
CASES = os.path.join(REF, "cases")
PLAYBOOK = os.path.join(REF, "00-打法库.md")
MANUAL03 = os.path.join(REF, "03-方法论操作手册.md")
KMAP = os.path.join(HERE, "knowledge_map.json")

PY = sys.executable


def read(p):
    return open(p, encoding="utf-8").read()


def md_files():
    out = []
    for f in glob.glob(os.path.join(ROOT, "**", "*.md"), recursive=True):
        if "/.git/" in f or "/.workbuddy/" in f:
            continue
        out.append(f)
    return out


# ── L1：引用可解析 ───────────────────────────────────────────
#   只查「像檔案路徑的引用」：排除三類必然查不到的寫法（它們是模板／命令／鏈路圖，不是路徑）
#     · 帶 `{…}` 的模板（`references/cases/{行業}.md`）
#     · 帶 `→` 的鏈路（`scripts/flow.py → composer.py → …`）
#     · 以 `python ` 開頭的命令示例
REF_PAT = re.compile(r"`([^`\n]*?(?:references|scripts|cases)/[^`\n]+?\.(?:md|json|py|sh|docx))`")
REF_SKIP = ("{", "}", "→", "|")


def l1(quiet):
    bad, total, skipped = [], 0, 0
    for f in md_files():
        base_dir = os.path.dirname(f)
        for m in REF_PAT.finditer(read(f)):
            raw = m.group(1).strip()
            if any(s in raw for s in REF_SKIP) or raw.startswith(("python ", "$ ", "bash ")):
                skipped += 1
                continue
            # 佔位寫法（`cases/xx.md`、`cases/NN-行业.md`）—— 是「舉例說明長什麼樣」，
            # 不是真實引用。2026-09-17：文檔開始教「不要寫這種座標」，這類舉例暴增。
            _fn = os.path.basename(raw)
            if re.match(r"^(?:xx|XX|NN|N+|X+)[\-_.]", _fn):
                skipped += 1
                continue
            total += 1
            cands = [os.path.join(ROOT, raw),
                     os.path.join(base_dir, raw),
                     os.path.join(REF, raw),
                     os.path.join(CASES, os.path.basename(raw))]
            if not any(os.path.exists(c) for c in cands):
                bad.append((os.path.relpath(f, ROOT), raw))
    if not quiet:
        print(f"  L1 檔案引用可解析：{total} 處可查引用（另有 {skipped} 處模板／命令／鏈路寫法不查），"
              f"**{len(bad)} 處指向不存在的檔**")
        for f, r in bad[:15]:
            print(f"     ✗ {f} → {r}")
    return len(bad), total


# ── L2/L3：打法 ↔ 案例 ──────────────────────────────────────
def _parse_plays():
    t = read(PLAYBOOK)
    plays, cur = {}, None
    for ln in t.split("\n"):
        m = re.match(r"^###\s+(\d+)\.(\d+)\s+(.+?)\s*$", ln)
        if m:
            major, minor = int(m.group(1)), m.group(2)
            if major == 0:
                cur = None
                continue
            cur = f"{major}.{minor}"
            plays[cur] = {"name": m.group(3).strip(), "case_line": ""}
            continue
        if re.match(r"^#{1,2}\s+\S", ln):
            cur = None
            continue
        if cur and ln.startswith("**案例**"):
            plays[cur]["case_line"] = ln
    return plays


def _cards():
    out = []
    for f in sorted(glob.glob(os.path.join(CASES, "*.md"))):
        base = os.path.basename(f)
        if not re.match(r"\d", base):
            continue
        for m in re.finditer(r"(?m)^###\s+3\.\d+\s+(.+?)\s*$", read(f)):
            out.append((base, m.group(1)))
    return out


def _universe():
    """卡片宇宙 —— **必须与 picker 操作的对象一致**。

    第一版這裡數的是 `### 3.N` 深度卡（609 張），而 `composer.parse_cards` 操作的是
    「案例清單條目 ∪ 深度卡」（約 983 條）→ **兩個分母對不上，覆蓋率算出來是假的**。
    （這正是本腳本要防的那類錯：指標與被測對象不一致。）
    """
    sys.path.insert(0, HERE)
    import composer as C
    uni = set()
    for f in sorted(glob.glob(os.path.join(CASES, "*.md"))):
        b = os.path.basename(f)
        if not re.match(r"\d", b):
            continue
        for c in C.parse_cards("cases/" + b):
            base = re.split(r"[｜|（(]", c["brand"])[0].strip()
            if base:
                uni.add((b, base))
    return uni


def l23(quiet):
    """L2 斷鏈類：每條打法都要「引用行 = 實際取得到的卡」；
    L3 覆蓋率類：把 **每一條打法 × 每一個行業檔** 都跑一次 pick_cards，
                 其中「**空手**的組合」才是斷鏈，「含本行業卡的組合」是品質指標。

    回傳 (l2_breaks, plays_total, l3_zero, l3_pairs, l3_ind_ok, covered, universe)
    """
    sys.path.insert(0, HERE)
    import composer as C
    C.load_model_names(MANUAL03)
    plays = _parse_plays()
    all_files = [os.path.basename(f) for f in sorted(glob.glob(os.path.join(CASES, "*.md")))
                 if re.match(r"\d", os.path.basename(f))]

    broken, mismatch = [], []
    for pid, info in plays.items():
        line = info["case_line"]
        if not line:
            broken.append((pid, info["name"], "無 `**案例**` 行"))
            continue
        files = re.findall(r"`?(cases/\d{2}-[^`\s（(]+\.md)`?", line)
        p = {"id": pid, "name": info["name"], "cases": files, "cases_raw": line,
             "situation": ""}
        if not C.pick_cards(p, "", limit=1):
            broken.append((pid, info["name"], "取不到任何指名卡片"))
            continue
        declared = [kw for cf, kw in C.case_pairs(line)]
        got = [re.split(r"[｜|（(]", c["brand"])[0].strip()
               for cf, c in C.pick_cards(p, "", limit=9)]
        miss = [d for d in declared
                if not any(d[:4] in g or g[:4] in d for g in got)]
        if miss:
            mismatch.append((pid, info["name"], miss, got))

    zero, ind_ok, covered = 0, 0, set()
    for pid, info in plays.items():
        files = re.findall(r"`?(cases/\d{2}-[^`\s（(]+\.md)`?", info["case_line"])
        p = {"id": pid, "name": info["name"], "cases": files,
             "cases_raw": info["case_line"], "situation": ""}
        for ind in all_files:
            got = C.pick_cards_ex(p, ind, limit=2)
            if not got:
                zero += 1
                continue
            if any(os.path.basename(cf) == ind for cf, c, _ in got):
                ind_ok += 1
            for cf, c, _ in got:
                covered.add((os.path.basename(cf),
                             re.split(r"[｜|（(]", c["brand"])[0].strip()))

    uni = _universe()
    pairs = len(plays) * len(all_files)
    if not quiet:
        print(f"  L2 打法 → 案例：{len(plays)} 條打法，取不到卡片的 {len(broken)} 條；"
              f"**引用行與實際取到的卡不一致的 {len(mismatch)} 條**")
        for pid, name, why in broken[:10]:
            print(f"     ✗ §{pid} {name} —— {why}")
        for pid, name, miss, got in mismatch[:10]:
            print(f"     ✗ §{pid} {name}：宣稱 {miss} ≠ 實得 {got}")
        print(f"  L3 打法 × 行業（{len(plays)} × {len(all_files)} = {pairs} 組）："
              f"**空手 {zero} 組**｜含本行業卡 {ind_ok} 組（{ind_ok / max(pairs, 1) * 100:.0f}%）｜"
              f"覆蓋卡片 {len(covered)}/{len(uni)}")
    return len(broken) + len(mismatch), len(plays), zero, pairs, ind_ok, len(covered), len(uni)


# ── L4：交付物注入（實跑 composer，數真實內容 vs 占位符）──────
def l4(quiet):
    rules = os.path.join(REF, "范例", "（示例）区域茶饮新品牌-任务规则表.json")
    if not os.path.exists(rules):
        cands = glob.glob(os.path.join(REF, "范例", "*规则表*.json"))
        if not cands:
            if not quiet:
                print("  L4 交付物注入：找不到示例規則表，跳過")
            return 0, 0
        rules = cands[0]
    out = "/tmp/kb_audit_skeleton.md"
    r = subprocess.run([PY, os.path.join(HERE, "composer.py"), "--rules", rules,
                        "--out", out, "--tier", "标准"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        if not quiet:
            print(f"  L4 交付物注入：composer 跑不起來（rc={r.returncode}）")
            print("     " + (r.stdout or r.stderr).strip().splitlines()[-1][:120])
        return 99, 0
    t = read(out)
    # 卡片摘要行的出處標記用**全形括號**（`（`cases/xx.md`）`）—— 第一版用半形 `\(` 去數，
    # 結果 count 恆為 0，差點又把「兩邊都 0」誤讀成「沒注入」（這種 bug 正是本腳本要防的）。
    # 2026-09-17：交付稿**不再帶 `cases/xx.md` 路徑**（那是內部座標，客戶看不懂）。
    #   所以「有沒有真的注入」不能再靠數路徑 —— 改成數**真實卡片內容**：
    #   `**品牌** —— 他做了什麼 ▶ 结果：數字`
    injected = len(re.findall(r"\*\*[^*]{2,24}\*\*\s*——", t))
    results = len(re.findall(r"▶\s*结果", t))
    placeholder = len(re.findall(r"暂无可直接参照的公开案例|请展开", t))
    # 同時查交付稿是否殘留內部座標（與 selfcheck 第【10】關同一套判據）
    coords = len(re.findall(r"§\s*\d|cases/\d{2}-|打法[庫库]|"
                            r"03\s*[·§]\s*[A-Ma-m]\d|模式\s*\d{1,2}", t))
    if not quiet:
        print(f"  L4 交付物注入：骨架 {len(t)} 字｜真實卡片內容 **{injected} 處**"
              f"（含結果數字 {results} 處）｜占位符 {placeholder} 處"
              f"｜**殘留內部座標 {coords} 處**")
        if coords:
            print(f"     ✗ 交付稿出現內部座標 —— 客戶看不懂，selfcheck 第【10】關會攔")
    return placeholder + coords, injected


# ── L5：模型引用可解析（死條目掃描）──────────────────────────
def l5(quiet):
    m03 = set(m.group(1).upper() for m in
              re.finditer(r"(?m)^###\s*([A-Ma-m]\d{1,2})[｜|·\s]", read(MANUAL03)))
    km = json.loads(read(KMAP))
    used = set()
    for k, v in km.get("major_theory", {}).items():
        used |= {str(x).upper() for x in v.get("models", [])}
    for k, v in km.get("play_overrides", {}).items():
        used |= {str(x).upper() for x in v.get("models", [])}
    dead = sorted(used - m03)
    unused = len(m03 - used)
    total_models = len(m03)
    # **2026-09-17 補：「被 JSON 引用」≠「挑得到」。**
    #   實測接入 33 個模型後仍只有 14 個能被 theory_for 選中 ——
    #   因為 major_theory 每類只取前 3，多數模型永遠浮不上來。
    #   所以真正的指標是**可達率**：把所有打法的 theory_for 跑一遍，看哪些模型從未出現。
    sys.path.insert(0, HERE)
    import composer as C
    _km = json.loads(read(KMAP))          # 只讀一次（寫在迴圈裡會讀 104 次盤，×50 遍直接拖死）
    reach = set()
    for pid, info in _parse_plays().items():
        major = int(pid.split(".")[0])
        p = {"id": pid, "name": info["name"], "situation": "",
             "major": major, "cases": [], "cases_raw": ""}
        ms, _ = C.theory_for(p, _km)
        reach |= set(ms)
    unreachable = sorted(m03 - reach)
    if not quiet:
        print(f"  L5 模型 → 打法：03 手冊 {len(m03)} 個模型；映射表引用 {len(used)} 個；"
              f"**死條目 {len(dead)} 個**（引用但手冊裡不存在）")
        if dead:
            print(f"     ✗ 死條目：{'、'.join(dead[:20])}")
        print(f"     **能被 theory_for 挑中的：{total_models - len(unreachable)}/{total_models}**"
              f"（映射表未引用的 {unused} 個；引用了但挑不到的 {len(unreachable) - unused} 個）")
        if unreachable:
            print(f"     ✗ 永遠挑不到：{'、'.join(unreachable[:24])}")
    # 斷鏈＝死條目（引用不存在的碼）＋ 永遠挑不到（引用了卻浮不上來）
    return len(dead) + len(unreachable), total_models, unused, total_models - len(unreachable)


# ── L7：私有痕跡掃描（公開倉庫紅線）──────────────────────────
#   為什麼放進審計：2026-09-17 推送前掃到**兩個腳本硬編碼了本機絕對路徑**，
#   以及「去識別化」那一輪漏下的具名主體。**這類洩漏不會被任何既有腳本發現**，
#   而它是公開倉庫唯一「一旦推出去就收不回」的錯誤 —— 所以必須機械化。
PRIVATE_PAT = re.compile(r"/Users/|/home/[a-z]|C:\\\\|\\bzuel\\b|ZUEL|campaign-zuel|00-项目背景",
                         re.I)
PRIVATE_SKIP_DIR = ("/.git/", "/.workbuddy/")


def l7(quiet):
    """注意：**必須排除本腳本自己** —— 判定的正則裡必然含 `/Users/` 這種字面，
    不排除就會永遠自己舉報自己（同 rename_tidy 對自身的處理）。"""
    bad = []
    me = os.path.basename(__file__)
    for f in md_files() + glob.glob(os.path.join(HERE, "*.py")) \
            + glob.glob(os.path.join(HERE, "*.json")) + glob.glob(os.path.join(ROOT, "*.md")):
        if any(s in f for s in PRIVATE_SKIP_DIR) or os.path.basename(f) == me:
            continue
        try:
            t = read(f)
        except Exception:
            continue
        for i, l in enumerate(t.split("\n"), 1):
            if PRIVATE_PAT.search(l):
                bad.append((os.path.relpath(f, ROOT), i, l.strip()[:80]))
    if not quiet:
        print(f"  L7 私有痕跡（公開倉庫紅線）：**{len(bad)} 處**")
        for f, i, l in bad[:12]:
            print(f"     ✗ {f}:{i} {l}")
    return len(bad), 1


# ── L6：全量回歸（6 個既有腳本一次跑完）──────────────────────
SCRIPTS = ["file_meta.py", "case_sections.py", "case_order.py",
           "case_upgrade.py", "case_lint.py", "smoke_test.py"]


def l6(quiet):
    bad = []
    for s in SCRIPTS:
        p = os.path.join(HERE, s)
        if not os.path.exists(p):
            bad.append((s, "不存在"))
            continue
        r = subprocess.run([PY, p], capture_output=True, text=True)
        tail = (r.stdout or "").strip().split("\n")[-1][:90]
        ok = r.returncode == 0
        if not ok:
            bad.append((s, tail))
        if not quiet:
            print(f"     {'✅' if ok else '✗'} {s}：{tail}")
    if not quiet:
        print(f"  L6 全量回歸：{len(SCRIPTS)} 個校驗腳本，{len(bad)} 個未通過")
    return len(bad), len(SCRIPTS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-compose", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    q = a.quiet

    print("=" * 68)
    print("知識庫連通性審計 · kb_audit.py")
    print("（既有 6 個腳本查『檔案內性質』；本腳本查『跨檔案連通性』—— 兩者是不同的東西）")
    print("=" * 68)

    f1, t1 = l1(q)
    f2, t2, z3, tp3, i3, cov3, t3 = l23(q)
    if a.no_compose:
        f4, inj = 0, -1
        if not q:
            print("  L4 交付物注入：（--no-compose，跳過）")
    else:
        f4, inj = l4(q)
    f5, t5, unused5, reach5 = l5(q)
    if not q:
        print("  L6 全量回歸（6 個既有腳本）：")
    f6, t6 = l6(q)
    f7, t7 = l7(q)

    print("-" * 68)
    # 斷鏈類（L1/L2/L4/L6/L7）＝機器能不能動；覆蓋率類（L3/L5 未用）＝還有多少沒接上，
    # **只有斷鏈才決定退出碼** —— 否則「649 張卡必須全被某條打法引用」這種非要求
    # 會讓審計永遠紅燈，久了就沒人看（這正是上一輪「綠燈但其實斷了」的反面陷阱）。
    rows = [
        ("L1 檔案引用可解析", f1, t1),
        ("L2 打法→案例（含「引用行＝實取」一致）", f2, t2),
        ("L3 (打法×行業) 空手的組數", z3, tp3),
        ("L4 交付物占位符", f4, inj),
        ("L6 既有校驗未通過", f6, t6),
        ("L7 私有痕跡（公開倉庫紅線）", f7, t7),
    ]
    covered = [
        ("L3 含本行業卡的組數（品質指標）", tp3 - i3, tp3),
        ("L3 覆蓋到的卡片數（覆蓋率）", t3 - cov3, t3),
        ("L5 模型未被映射表用到（覆蓋率，非要求）", unused5, t5),
        ("L5 模型能被挑中（可達率，越高越好）", reach5, t5),
    ]
    total_bad = sum(x[1] for x in rows)
    for name, bad, tot in rows:
        flag = "✅" if bad == 0 else "✗"
        print(f"  {flag} {name}：{bad}（基數 {tot}）")
    for name, cov, tot in covered:
        print(f"  ○ {name}：{cov}/{tot}")
    print("-" * 68)
    if total_bad == 0:
        print("✅ 五類斷鏈全通 —— 知識庫是「連通的」，不只是「零件合格」")
    else:
        print(f"⚠️ 共 {total_bad} 個斷點。**零件合格 ≠ 機器能動** —— 這些斷點不會被前 6 個腳本發現。")
    sys.exit(0 if total_bad == 0 else 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 執行出錯：{type(e).__name__}: {e}")
        sys.exit(2)
