#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
案例卡體檢 · case_lint.py  （把「案例集硬規則」變成機械檢查）

為什麼有它（2026-09-16）：
    SKILL 寫了「案例集硬規則：嚴禁公司背景（創始人／成立年份／股權／融資／營收／人事）」，
    但**沒有任何腳本檢查**，於是庫裡積累了大量與營銷無關的背景資訊（營收 1000+ 處）。
    規則只寫在文字裡＝模型不會看＝等於沒有。本腳本把它變成可跑的檢查。

用法：
    python scripts/case_lint.py                    # 掃全庫，出報告
    python scripts/case_lint.py cases/14-*.md      # 只掃指定檔
    python scripts/case_lint.py --max 900          # 容忍上限（超過則退出碼 1）
    python scripts/case_lint.py --strict           # 關閉「身份欄／歸因欄」豁免（回到裸計數）
    python scripts/case_lint.py --quiet

兩處**已記錄的計數豁免**（用戶 2026-09-17 決策，選項 A：維持現狀、只調整上限）：
    1. `- **誰做的**：` —— 格式規定的**身份欄**，按設計就要寫「誰做的（甲方自建／創始人／成立年份）」。
       它回答的是「這個案例屬於誰」，不是公司傳記；把它計入「公司背景違規」等於與格式衝突。
    2. `- ⚠️ **歸因提醒**：` —— 它的**職能就是口徑溯源**，必須指名「某人在某場合披露」才能讓人核到源頭。
       去掉人名會讓這一欄失去意義。用 `--strict` 可恢復裸計數。

上限：**預設 900**（2026-09-17 實測基準：裸計數 1043 → 剔身份欄 868 → 再剔歸因欄 768；
     取 900 保留約 17% 餘量，用於攔截**新增**的背景膨脹，而不是要求清理既有存量）。
     下限只作趨勢預警，**不是硬門檻**——不想讓它報警就 `--max` 傳更大的值。

退出碼：0 = 未超上限；1 = 超出（建議清理）；2 = 腳本出錯
規則來源：`references/cases/README.md` §六「卡片內容硬規則」（＋兩項計數例外）
"""

import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")

OK, NG, WARN = "✅", "❌", "⚠️"

# 公司背景詞（與 SKILL「案例集硬規則」對應）。機構／書籍／出版物類（46–51）豁免。
BG_WORDS = ["創始人", "创始人", "成立於", "成立于", "股權", "股权", "融資", "融资",
            "營收", "营收", "財報", "财报", "估值", "董事長", "董事长", "CEO",
            "裁員", "裁员", "IPO", "上市首日", "招股書", "招股书", "創辦人", "创办人"]
EXEMPT_SKIP = {49}   # 只豁免 49（營銷書籍與作者：作者名/書名本身即重點）
# 註：46/47/48/50（機構/出版物類）同樣按規則清理 —— 只保留「理解其方法所必需」的背景

# 計數豁免行（前綴匹配）。見檔頭說明（1）（2）。
EXEMPT_PREFIX = ("- **誰做的**", "- ⚠️ **歸因提醒**")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser(description="案例卡體檢（禁公司背景）")
    ap.add_argument("paths", nargs="*", help="指定檔案；不給則掃全庫")
    ap.add_argument("--max", type=int, default=None, help="全庫容忍上限（預設：豁免模式 900；--strict 模式不設閘）")
    ap.add_argument("--strict", action="store_true", help="關閉身份欄／歸因欄豁免（裸計數，報告用）")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    # --strict 是「量測模式」：只報數，不設閘（避免每次跑都紅）。
    limit = a.max if a.max is not None else (None if a.strict else 900)
    ex_prefix = () if a.strict else EXEMPT_PREFIX
    files = a.paths or sorted(glob.glob(os.path.join(ROOT, "references", "cases", "*.md")))
    if not files:
        print(f"{NG} 找不到案例檔")
        sys.exit(2)

    total = 0
    excl_total = 0
    rows = []
    worst_cards = []
    for f in files:
        base = os.path.basename(f)
        m = re.match(r"(\d+)", base)
        if not m:
            continue          # 非編號檔（README.md 等）不是案例卡，跳過
        n = int(m.group(1))
        raw = read(f)
        # 標題（品牌名+角度）＝參考對象，不計入「公司背景」違規
        lines = [l for l in raw.splitlines() if not re.match(r"^#{1,6}\s", l)]
        kept, dropped = [], 0
        for l in lines:
            if ex_prefix and l.startswith(ex_prefix):
                dropped += sum(l.count(w) for w in BG_WORDS)
            else:
                kept.append(l)
        t = "\n".join(kept)
        hits = {w: t.count(w) for w in BG_WORDS if t.count(w)}
        cnt = sum(hits.values())
        if n not in EXEMPT_SKIP:
            total += cnt
            excl_total += dropped
        if cnt:
            rows.append((cnt, base, n in EXEMPT_SKIP, hits))
            # 逐卡定位重災區
            for cm in re.finditer(r"(?m)^###\s+(\d+\.\d+)\s+(.+)$", t):
                end = re.search(r"(?m)^#{1,3}\s", t[cm.end():])
                seg = t[cm.end(): cm.end() + (end.start() if end else len(t))]
                c = sum(seg.count(w) for w in BG_WORDS)
                if c >= 5:
                    worst_cards.append((c, base, cm.group(1), cm.group(2)[:34]))

    if not a.quiet:
        print("=" * 64)
        print("案例卡體檢 · 「嚴禁公司背景」")
        print("=" * 64)
        print(f"掃描 {len(files)} 個檔；違規詞計入 {total}｜上限 {limit if limit else '—（量測模式，不設閘）'}"
              f"｜豁免 {excl_total}（{'裸計數，無豁免' if a.strict else '身份欄／歸因欄'}）")
        rows.sort(reverse=True)
        for cnt, base, exempt, hits in rows[:15]:
            tag = "（49 書籍作者類·豁免）" if exempt else ""
            top = "、".join(f"{k}×{v}" for k, v in sorted(hits.items(), key=lambda x: -x[1])[:4])
            print(f"  {cnt:>5}  {base}{tag}\n         {top}")
        if worst_cards:
            print("\n重災卡（單卡 ≥5 處背景詞；這是既有存量，非新問題）：")
            for c, base, cid, title in sorted(worst_cards, reverse=True)[:10]:
                print(f"  {c:>3}  {base} §{cid} {title}")

    print("\n" + "-" * 64)
    print("規則：案例卡應只留「營銷動作 ＋ 結果」；創始人／融資／營收／人事屬應剔除的背景。")
    print("例外一：46–51（機構／書籍／出版物類）可保留「理解其方法所必需」的背景。")
    if not a.strict:
        print("例外二（2026-09-17 決策 A）：`- **誰做的**` 身份欄 與 `- ⚠️ **歸因提醒**` 口徑溯源欄"
              " 不計入；加 `--strict` 可恢復裸計數。")
    if limit is None:
        print(f"{OK} 量測模式（--strict）：裸計數 {total}，本輪不設閘。")
        sys.exit(0)
    if total > limit:
        print(f"{NG} 超上限（{total} > {limit}）—— 建議按上面清單清理案例卡。")
        sys.exit(1)
    print(f"{OK} 未超上限（{total} ≤ {limit}）。")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"{NG} 執行出錯：{type(e).__name__}: {e}")
        sys.exit(2)
