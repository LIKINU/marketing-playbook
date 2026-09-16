#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
頂層工作檔「標題統一」· top_titles.py

為什麼（2026-09-17，用戶裁定）：
    「050607 為甚麼沒放在 cases 庫裏 而且要跟 cases 庫的格式一樣」
    → 裁定：**06 進 cases（由 relocate_06.py 處理）；05/07 只統一標題。**

05／07 的標題問題（不改內容、只改標題）：
    05：
      · `## 階段一｜…`～`## 階段五｜…` 與 `## 路徑一｜…`～`## 路徑三｜…`
        佔用了 `## ` 這層，但它們其實是「二、五階段路徑」與「三、三條路徑」的**下級**——
        結果 H2 序號序列被切斷（一 二 階段一…五 三 路徑一…三 四 …），
        file_meta 自動生成的目錄因此長到沒法看。
      · 末節 `## 查不到的部分` 沒有序號，與其餘 11 節不一致。
      · 「（合併版）」是內部痕跡，不是標題訊息。
    07：
      · 「（背這三句就夠）」「（一句話定位，用來快速排除）」是口語說明，不是語義限定詞。

做什麼（**只動 `## `/`### ` 標題行，正文一行不碰**）：
    1. 把 `## 階段N｜…` / `## 路徑N｜…` 降為 `### `，其下屬 `### ` 一併降為 `#### `
    2. H2 序號按出現順序重編（〇、一、二…），末節補上序號
    3. 去掉口語括注與內部痕跡，保留語義限定詞

硬不變式：
    1. **非標題行逐行不變**（含空行；用整段字串比對）
    2. `# ` 一級標題數不變
    3. 改完後所有 `## ` 都在下面 EXPLICIT 白名單裡（防止誤改）

用法：
    python scripts/top_titles.py            # 體檢
    python scripts/top_titles.py --fix
退出碼：0 = 一致（或修復成功）；1 = 異常；2 = 腳本出錯
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
REF = os.path.join(ROOT, "references")

FILES = ["05-小企业与新品牌从零打造.md", "06-选流派矩阵与对照表.md"]

# 首節序號的起點：05 有「〇、先定位你在哪一格」故從 〇 起；07 直接從 一 起
START = {"05-小企业与新品牌从零打造.md": 0, "06-选流派矩阵与对照表.md": 1}

NUMS = ["〇", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"]

RE_H2 = re.compile(r"^##\s+(.+?)\s*$")
RE_H3 = re.compile(r"^###\s+(.+?)\s*$")

# ── 降級：這些 H2 其實是下級（降成 H3），其下 `### ` 再降一級
DEMOTE_PREFIX = ("階段一｜", "階段二｜", "階段三｜", "階段四｜", "階段五｜",
                 "路徑一｜", "路徑二｜", "路徑三｜")

# ── H2 改名（精確比對，不含序號）→ (新標題正文, 是否降級)
RENAME = {
    # 05
    "合併說明": "合併說明",
    "新品牌 0→1 的五階段路徑": "新品牌 0→1 的五階段路徑",
    "小企業品牌化的三條路徑": "小企業品牌化的三條路徑",
    "各賽道從零起盤": "各賽道從零起盤",
    "零預算 / 微預算打法庫（合併版）": "零預算 / 微預算打法庫",
    "新品牌上市 90 天作戰計劃模板": "新品牌上市 90 天作戰計劃模板",
    "預算分配參考表": "預算分配參考表",
    "失敗歸因與解法（合併版）": "失敗歸因與解法",
    "騙局識別庫（代運營 / 加盟 / 投流課程）": "騙局識別庫（代運營 / 加盟 / 投流課程）",
    "對接實測清單（見小企業／新品牌客戶時照着問）": "對接實測清單（小企業／新品牌客戶照着問）",
    "小企業主決策自檢清單（可列印）": "小企業主決策自檢清單（可列印）",
    "查不到的部分": "查不到的部分",
    "先定位你在哪一格（路由表）": "先定位你在哪一格（路由表）",
    # 07
    "六組對照：同一問題，五類解法怎麼解": "六組對照：同一問題，五類解法怎麼解",
    "總覽表（橫版速查）": "總覽表（橫版速查）",
    "三條選型原則（背這三句就夠）": "三條選型原則",
    "流派速查（一句話定位，用來快速排除）": "流派速查",
}


def strip_num(s):
    return re.sub(r"^\s*[〇一二三四五六七八九十]+\s*、\s*", "", s).strip()


def tidy(text, k0=0, verbose=False):
    lines = text.split("\n")
    out, changes = [], []
    k = k0
    demoting = False          # 是否正處於「階段N／路徑N」之下

    for i, l in enumerate(lines):
        m2 = RE_H2.match(l)
        if m2:
            core = strip_num(m2.group(1).replace("**", "").strip())
            if core.startswith(DEMOTE_PREFIX):
                demoting = True
                new = "### " + core
                if new != l:
                    changes.append((i + 1, l, new))
                out.append(new)
                continue
            demoting = False
            if core not in RENAME:
                raise ValueError(f"未在白名單的 H2：{core!r}（第 {i+1} 行）")
            canon = RENAME[core]
            num = NUMS[k] if k < len(NUMS) else str(k)
            k += 1
            new = f"## {num}、{canon}"
            if new != l:
                changes.append((i + 1, l, new))
            out.append(new)
            continue

        m3 = RE_H3.match(l)
        if m3 and demoting:
            new = "#### " + m3.group(1).strip()
            if new != l:
                changes.append((i + 1, l, new))
            out.append(new)
            continue

        out.append(l)

    return "\n".join(out), changes


def verify(old, new):
    def nonhead(s):
        return [l for l in s.split("\n")
                if l.strip() and not l.lstrip().startswith("#")]
    if nonhead(old) != nonhead(new):
        d = [x for x, y in zip(nonhead(old), nonhead(new)) if x != y]
        return f"非標題行被改動（{len(d)} 行），例：{d[0][:60]!r}" if d else "非標題行數變了"
    if len(re.findall(r"(?m)^#\s", old)) != len(re.findall(r"(?m)^#\s", new)):
        return "一級標題數變了"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true")
    a = ap.parse_args()

    bad = ok = 0
    for name in FILES:
        f = os.path.join(REF, name)
        old = open(f, encoding="utf-8").read()
        try:
            new, changes = tidy(old, START.get(name, 0))
        except ValueError as e:
            print(f"❌ {name}：{e}")
            bad += 1
            continue
        if not changes:
            ok += 1
            print(f"✅ {name}：已一致")
            continue
        print(f"\n{name}（{len(changes)} 處）")
        for ln, o, n in changes:
            print(f"  L{ln}\n    - {o}\n    + {n}")
        v = verify(old, new)
        if v:
            print(f"  ⚠️ 放棄寫入：{v}")
            bad += 1
            continue
        if a.fix:
            open(f, "w", encoding="utf-8").write(new)

    print("\n" + "-" * 64)
    print(f"已一致 {ok} 檔｜需改 {len(FILES) - ok - bad} 檔｜異常 {bad} 檔")
    print("✅ 完成，接著跑 file_meta.py --fix 同步目錄" if a.fix else "（體檢模式，未寫入）")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 執行出錯：{type(e).__name__}: {e}")
        sys.exit(2)
