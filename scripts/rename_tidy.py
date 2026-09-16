#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
命名梳理 · rename_tidy.py

為什麼（2026-09-17，用戶指令）：
    「第四 改完之後要重新疏理命名」

做完 ①（融 README）②（補 16 檔缺口）③（06 進 cases、05/07 統一標題）之後，
命名層留下三處不一致：

    1. **頂層序號斷層**：06 搬進 `cases/51` 之後，`00–09` 就空了 06 —— 而這串號
       是「按流程順序」排的（SKILL 第 -1 步導航表的閱讀順序），斷一號等於斷了流程。
       → 07→06、08→07、09→08（補空，不留洞）
    2. **H1 名稱不統一**：同一層級的檔，H1 格式卻五種
       —— 有的帶序號（`# 44-招聘與僱主品牌`）、有的帶版本痕跡
       （`# 範本 · 便利店開學季案範式（v2 · 2026-09-16 重跑實測版）`）、
       有的帶宣傳語（`# 接案操作流程 SOP（用這個 skill 幹活 · …）`）、
       有的帶中英對照（`# 03 · 方法論操作手冊（Marketing Playbook · Operating Manual）`）。
       → 規則：**H1 ＝ 名稱（＋語義限定詞）**；序號、版本、宣傳語、中英對照一律進檔頭，不進 H1。
    3. **cases/README 登記表停留在「50 檔／620 卡」**，且 §三 標題寫「46–50」。
       → 依實際統計更新。

做什麼：
    A. 改檔名：07/08/09 → 06/07/08（三檔）
    B. 改 H1：13 處（見 H1_NEW）
    C. 全庫字串替換：所有舊檔名 → 新檔名（references/ 內外、scripts/ 也掃）
    D. 更新 `references/cases/README.md` 的統計與 §三 標題
    E. 報告待人工處理的敘述段落（腳本不改散文）

硬不變式：
    1. 改名後**舊檔名不得再出現在任何檔**（殘留即報錯）
    2. 每個 H1 改動都必須**精確匹配**，匹配不到就整體中止（不改半套）

用法：
    python scripts/rename_tidy.py            # 體檢（不寫入）
    python scripts/rename_tidy.py --fix
退出碼：0 = 完成；1 = 有不變式未通過；2 = 腳本出錯
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

# ── A. 檔名（頂層序號補空）
RENAME = [
    ("references/07-选流派矩阵与对照表.md", "references/06-选流派矩阵与对照表.md"),
    ("references/08-质量范式-便利店开学季案.md", "references/07-质量范式-便利店开学季案.md"),
    ("references/09-操作流程SOP.md", "references/08-操作流程SOP.md"),
]

# ── C. 全庫字串替換（先長後短；每個舊名都只出現一次、彼此不重疊）
REF_MAP = [
    ("references/07-选流派矩阵与对照表.md", "references/06-选流派矩阵与对照表.md"),
    ("07-选流派矩阵与对照表", "06-选流派矩阵与对照表"),
    ("references/08-质量范式-便利店开学季案.md", "references/07-质量范式-便利店开学季案.md"),
    ("08-质量范式-便利店开学季案", "07-质量范式-便利店开学季案"),
    ("references/09-操作流程SOP.md", "references/08-操作流程SOP.md"),
    ("09-操作流程SOP", "08-操作流程SOP"),
]

# ── B. H1 統一（精確比對）
H1_NEW = {
    "# 03 · 方法論操作手冊（Marketing Playbook · Operating Manual）": "# 方法論操作手冊",
    "# 小企業與新品牌從零打造（合併版）": "# 小企業與新品牌從零打造",
    "# 選流派矩陣與對照表（路由器）": "# 選流派矩陣與對照表",
    "# 範本 · 便利店開學季案範式（v2 · 2026-09-16 重跑實測版）":
        "# 質量範式 · 便利店開學季案",
    "# 接案操作流程 SOP（用這個 skill 幹活 · 從接案到交付 · 精確到每一步）":
        "# 接案操作流程 SOP",
    "# 44-招聘與僱主品牌": "# 招聘與僱主品牌 · 營銷案例集",
    "# 45-物流與快遞服務": "# 物流與快遞服務 · 營銷案例集",
    "# 46-國際4A與傳播集團": "# 國際4A與傳播集團 · 機構案例集",
    "# 47-戰略諮詢": "# 戰略諮詢 · 機構案例集",
    "# 48-本土創意與營銷服務商": "# 本土創意與營銷服務商 · 機構案例集",
    "# 49-營銷書籍與作者": "# 營銷書籍與作者 · 機構案例集",
    "# 50-機構出版物與觀點庫": "# 機構出版物與觀點庫 · 機構案例集",
    "# 本土數字營銷與 MCN · 機構案例集": "# 本土數字營銷與 MCN · 機構案例集",
}

# ── D. cases/README.md 的替換（舊字串 → 新字串）
README_FIX = [
    ("# references/cases/ · 導航（**50 個檔，但你只需要 1 個**）",
     "# references/cases/ · 導航（**51 個檔，但你只需要 1 個**）"),
    ("**規模**：50 個大類 / **620 張深度案例卡** ＝ 01–45 行業檔 **411 張** ＋ 46–50 機構與方法論檔 **209 張**。",
     "**規模**：51 個大類 / **649 張深度案例卡** ＝ 01–45 行業檔 **411 張** ＋ 46–51 機構與方法論檔 **238 張**。"),
    ("## 三、46–50 機構與方法論檔（**做行業方案時不需要讀**）",
     "## 三、46–51 機構與方法論檔（**做行業方案時不需要讀**）"),
    ("| 本行業常見死法 | 29 檔 |", "| 本行業常見死法 | **45/45 檔** |"),
    ("| 查不到的部分 | 30 檔 |", "| 查不到的部分 | 47 檔 |"),
    ("| 相關 | 32 檔 |", "| 相關 | 33 檔 |"),
    ("`46–50`（機構／出版物類）是**另一套結構**", "`46–51`（機構／出版物類）是**另一套結構**"),
    ("- **例外**：`46–50` 機構／書籍類可保留", "- **例外**：`46–51` 機構／書籍類可保留"),
    ("| `50-机构出版物与观点库` | 17 | 機構年度報告／數據源／演講 IP（含「動機—用法」速查） |",
     "| `50-机构出版物与观点库` | 17 | 機構年度報告／數據源／演講 IP（含「動機—用法」速查） |\n"
     "| `51-本土数字营销与MCN` | 29 | 省廣／利歐／天下秀／分眾、無憂／遙望／蜂群／Papitube、"
     "新消費操盤複盤、平台官方模型（AIPL／FAST／O-5A／5R） |"),
]


def md_files():
    out = []
    for f in glob.glob(os.path.join(ROOT, "**", "*.md"), recursive=True):
        if "/.git/" in f or "/.workbuddy/" in f:
            continue
        out.append(f)
    return out


def scan_files():
    """要掃描字串的檔：所有 .md ＋ scripts/*.py（**不含本腳本自己**——
    它的 REF_MAP 就是舊名的定義處，掃自己會永遠報「有殘留」）"""
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
            errs.append(f"找不到 {old}（可能已改過）")
        plan.append((old, new))

    # ── B（先確認每個 H1 都精確匹配，否則整體中止）
    targets = {}
    for f in md_files():
        s = open(f, encoding="utf-8").read()
        m = re.search(r"(?m)^# .+$", s)
        if not m:
            continue
        if m.group(0) in H1_NEW and m.group(0) != H1_NEW[m.group(0)]:
            targets[f] = (m.group(0), H1_NEW[m.group(0)])

    # ── C（統計將受影響的檔）
    ref_hits = {}
    for f in scan_files():
        s = open(f, encoding="utf-8").read()
        n = 0
        for old, new in REF_MAP:
            n += s.count(old)
        if n:
            ref_hits[f] = n

    print(f"[A] 改檔名 {len(plan)} 個")
    for old, new in plan:
        print(f"    {old}\n      → {new}")
    print(f"\n[B] 改 H1 {len(targets)} 處")
    for f, (o, n) in sorted(targets.items()):
        print(f"    {os.path.relpath(f, ROOT)}\n      - {o}\n      + {n}")
    print(f"\n[C] 引用替換：{len(ref_hits)} 檔／{sum(ref_hits.values())} 處")
    for f, n in sorted(ref_hits.items()):
        print(f"    {os.path.relpath(f, ROOT)}（{n}）")
    print(f"\n[D] cases/README.md：{len(README_FIX)} 條")
    for o, n in README_FIX:
        print(f"    - {o[:60]}\n      + {n.splitlines()[0][:60]}")
    if errs:
        print("\n❌ 中止：\n  " + "\n  ".join(errs))
        sys.exit(1)
    if not a.fix:
        print("\n（體檢模式，未寫入。加 --fix 執行）")
        sys.exit(0)

    # ── 執行（順序很重要：先在舊路徑上改內容，最後才改檔名）
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
        print(f"⚠️ cases/README.md 有 {len(miss)} 條沒匹配到（未寫入該檔）：")
        for x in miss:
            print(f"    {x[:70]}")
    else:
        for o, n in README_FIX:
            s = s.replace(o, n)
        open(rf, "w", encoding="utf-8").write(s)
        print("✅ cases/README.md 已更新")

    # ── 硬不變式：舊檔名不得殘留
    left = []
    for f in scan_files():
        s = open(f, encoding="utf-8").read()
        for old, _ in REF_MAP:
            if old in s:
                left.append((os.path.relpath(f, ROOT), old))
    print(f"\n✅ 執行完成｜殘留舊名 {len(left)} 處")
    for f, o in left[:20]:
        print(f"    ⚠️ {f}：仍含 {o}")
    sys.exit(1 if left else 0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 執行出錯：{type(e).__name__}: {e}")
        sys.exit(2)
