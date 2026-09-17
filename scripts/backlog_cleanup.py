#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backlog_cleanup.py — 存量清理（**只标注、不批量改写**）

為什麼是「只标注」：
    案例库有三类存量问题，都是**内容问题**，不是格式问题：
      ① **空卡**：13 個行業檔的 140 張卡 `what/result/points` 全空 → 交付稿只剩品牌名
      ② **違規詞**：`case_lint` 實測 894 條「嚴禁公司背景」命中，而閾值是 900 → 報 ✅
      ③ **洞察欄**：650 卡中 251 卡無洞察欄；399 條洞察行裡 72 條是**數據複述**
    這三類**都不能靠腳本批量改寫** —— 批量改寫會「把內容改失真」，
    而案例庫是模型學寫作的教材，失真會直接污染下游交付稿。
    所以本工具只做兩件安全的事：
      · `--report`  ：導出**全量清單**（帶檔名、行號、原文片段），給人逐條處理
      · `--annotate`：給「無深度卡的清單行」補一個**純標記**（`（僅清單·無深度卡）`），
                      不改任何實質內容 —— 這是唯一機械安全的動作

用法：
    python scripts/backlog_cleanup.py --report 存量清理清单.md
    python scripts/backlog_cleanup.py --annotate --dry-run    # 先看要改多少行
    python scripts/backlog_cleanup.py --annotate              # 真寫入（純標記）
"""
import argparse
import glob
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CASES = os.path.join(ROOT, "references", "cases")

OK, NG, WARN, HINT = "✅", "❌", "⚠️", "→"

# 「嚴禁公司背景」的偵測詞（與 case_lint 同源；此處獨立實現是為了**導清單**而非**判達標**）
BG_WORDS = ["創始人", "创始人", "成立於", "成立于", "融資", "融资", "估值",
            "營收", "营收", "淨利", "净利", "員工", "员工", "董事長", "董事长"]
# 這些欄位裡出現背景詞是合法的（卡片結構本身要寫「誰做的」）
BG_SAFE_FIELDS = ("**誰做的**", "**谁做的**", "**為什麼**", "**为什么**")


def read(p):
    return io.open(p, encoding="utf-8").read()


def scan_cases():
    """→ {"empty": [(file, line, text)], "bg": [...], "insight_missing": [...], "insight_data": [...]}"""
    out = {"empty": [], "bg": [], "insight_missing": [], "insight_data": [], "nodc": []}
    for f in sorted(glob.glob(os.path.join(CASES, "*.md"))):
        base = os.path.basename(f)
        t = read(f)
        # ① 空卡：清單行裡有品牌名但「做了什麼／結果」為空
        for m in re.finditer(r"(?m)^\|\s*[\d.]+\s*\|\s*([^|]+?)\s*\|\s*\|", t):
            out["empty"].append((base, t[:m.start()].count("\n") + 1, m.group(1).strip()))
        for m in re.finditer(r"(?m)^\d+\.\s+\*\*([^*]+)\*\*\s*[｜|]\s*[^\n]{0,10}$", t):
            out["empty"].append((base, t[:m.start()].count("\n") + 1, m.group(1).strip()))
        # ② 違規詞（排除合法欄位所在行）
        for i, ln in enumerate(t.split("\n"), 1):
            if any(s in ln for s in BG_SAFE_FIELDS):
                continue
            for w in BG_WORDS:
                if w in ln:
                    out["bg"].append((base, i, w, ln.strip()[:60]))
                    break
        # ③ 洞察欄
        heads = list(re.finditer(r"(?m)^###\s+", t))
        for j, hm in enumerate(heads):
            blk = t[hm.start():heads[j + 1].start() if j + 1 < len(heads) else len(t)]
            title = blk.split("\n", 1)[0][:32]
            if "**洞察**" not in blk and "洞察" not in blk:
                out["insight_missing"].append((base, title))
            else:
                for m in re.finditer(r"洞察[^\n]*?[：:]\s*(.+)", blk):
                    line = m.group(1)
                    if len(re.findall(r"\d+(?:\.\d+)?\s*[%％]", line)) >= 1:
                        out["insight_data"].append((base, title, line.strip()[:50]))
        # ④ 清單行是否帶深度卡節號（無節號＝暫無深度卡 → 可標記）
        for m in re.finditer(r"(?m)^(\d+\.\s+\*\*[^*]+\*\*[^\n]*)$", t):
            if "§" not in m.group(1) and "僅清單" not in m.group(1):
                out["nodc"].append((base, t[:m.start()].count("\n") + 1, m.group(1)[:50]))
    return out


def main():
    ap = argparse.ArgumentParser(description="案例庫存量清理（只标注、不批量改写）")
    ap.add_argument("--report", default="", help="導出全量清單（Markdown）")
    ap.add_argument("--annotate", action="store_true",
                    help="給無深度卡的清單行補標記（**純標記，不改實質內容**）")
    ap.add_argument("--dry-run", action="store_true", help="配合 --annotate，只顯示不寫入")
    a = ap.parse_args()

    r = scan_cases()
    print("=" * 66)
    print("案例庫存量清理 · backlog_cleanup.py")
    print("=" * 66)
    print(f"  ① 疑似空卡（清單行無做法／結果）：{len(r['empty'])}")
    print(f"  ② 「嚴禁公司背景」命中（排除合法欄位）：{len(r['bg'])}")
    print(f"  ③ 無洞察欄的卡：{len(r['insight_missing'])}")
    print(f"  ④ **數據複述型洞察**（含百分比）：{len(r['insight_data'])}")
    print(f"  ⑤ 無深度卡節號的清單行（可安全標記）：{len(r['nodc'])}")

    if a.report:
        L = ["# 案例庫存量清理清單\n",
             "> 由 `scripts/backlog_cleanup.py` 導出。**只列不改** —— 這三類都是內容問題，",
             "> 批量改寫會讓教材失真，而教材失真會直接污染下游交付稿。\n",
             f"\n## 一、疑似空卡（{len(r['empty'])} 條）\n",
             "| 檔 | 行 | 品牌 |\n|---|---|---|\n"]
        for f, ln, b in r["empty"][:200]:
            L.append(f"| {f} | {ln} | {b} |\n")
        L.append(f"\n## 二、「嚴禁公司背景」命中（{len(r['bg'])} 條，已排除合法欄位）\n")
        L.append("> 分兩類處理：**A 類**＝純背景描述（可直接刪）；"
                 "**B 類**＝動作主體（改寫進「誰做的」）。\n\n| 檔 | 行 | 詞 | 片段 |\n|---|---|---|---|\n")
        for f, ln, w, s in r["bg"][:200]:
            L.append(f"| {f} | {ln} | {w} | {s} |\n")
        L.append(f"\n## 三、無洞察欄的卡（{len(r['insight_missing'])} 張）\n\n| 檔 | 卡 |\n|---|---|\n")
        for f, ti in r["insight_missing"][:200]:
            L.append(f"| {f} | {ti} |\n")
        L.append(f"\n## 四、數據複述型洞察（{len(r['insight_data'])} 條，需改寫成人心話）\n\n"
                 "> 判據：**主語要是「人」**，不是「平台／渠道／品牌」。\n\n| 檔 | 卡 | 原文 |\n|---|---|---|\n")
        for f, ti, s in r["insight_data"][:200]:
            L.append(f"| {f} | {ti} | {s} |\n")
        io.open(a.report, "w", encoding="utf-8").write("".join(L))
        print(f"{OK} 已導出清單：{a.report}")

    if a.annotate:
        n_file = n_line = 0
        for f in sorted(glob.glob(os.path.join(CASES, "*.md"))):
            t = read(f)
            if "僅清單·無深度卡" in t or "仅清单·无深度卡" in t:
                continue
            lines = t.split("\n")
            # ⚠️ 必須**限定在「案例清單」區段內**：深度卡裡也有不縮排的編號行
            #   （如 `- **落地拆解**：` 下的 `  1. …` 雖縮排，但個別檔有例外），
            #   不限範圍就會把深度卡內容誤標成「僅清單」—— 那就把教材改錯了。
            hit = 0
            _sec = None
            for i, ln in enumerate(lines):
                if re.match(r"^##\s*[一二三四五六七八九十]*、?\s*案例清單", ln):
                    _sec = i
                    continue
                if _sec is not None and re.match(r"^##\s", ln):
                    _sec = None
                    continue
                if _sec is None:
                    continue
                if re.match(r"^\d+\.\s+\*\*[^*]+\*\*", ln) and "§" not in ln:
                    lines[i] = ln.rstrip() + "（仅清单·无深度卡）"
                    hit += 1
            if hit:
                n_file += 1
                n_line += hit
                if not a.dry_run:
                    io.open(f, "w", encoding="utf-8").write("\n".join(lines))
        print(f"{OK if not a.dry_run else WARN} 標記{'（dry-run 未寫入）' if a.dry_run else '完成'}："
              f"{n_line} 行、{n_file} 個檔")
        print(f"{HINT} 這是**純標記**（只在行尾加「（仅清单·无深度卡）」），不改任何實質內容。")
    if not a.report and not a.annotate:
        print(f"\n{WARN} 未指定動作。用 --report 導清單，或 --annotate 補標記。")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{WARN} 已中斷。")
        sys.exit(130)
    except Exception as e:
        print(f"\n{NG} backlog_cleanup 執行出錯：{type(e).__name__}: {e}")
        print(f"{HINT} 依協議 8：修正後重跑；環境問題就人工逐檔清理，不要卡在這裡。")
        sys.exit(2)
