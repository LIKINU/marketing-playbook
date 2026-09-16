#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复 `00-打法库` 的 104 条「案例」行 · fix_play_cases.py

為什麼（2026-09-17，用戶質問「为什么还是有这么多问题」）：
    `kb_audit.py` 量出：104 條打法裡**只有 19 條**的 `**案例**` 行能指到具體卡片 ——
    因為那些案例行是**早期 6 檔時代**寫的，庫長到 51 檔後從未復檢。
    這是「交付物裡看不到知識庫」的傳導軸斷點，而既有的 6 個校驗腳本沒有一個查它。

做法（**不硬編碼標題、不硬編碼檔名**）：
    本腳本只接受「品牌關鍵詞 @ 檔號前綴」，例如 `("蜜雪冰城", "01")`，
    再從 `references/cases/` 裡**解析出真實卡片**，自動生成
        `**案例**：`cases/01-餐饮与茶饮.md`（蜜雪冰城、老鄉雞）。`
    所以**引用的檔名與品牌一定是庫裡真有的**，不可能寫出空引用。

硬不變式（--fix 時）：
    1. 每條打法**只改 `**案例**` 那一行**，其餘逐行不變（用整檔逐行比對驗證）
    2. 解析不到的品牌 → 該條**整體跳過並報錯**（不寫半條）
    3. 冪等：已是目標文字就跳過

用法：
    python scripts/fix_play_cases.py            # 驗證：列出每條的解析結果與失敗項（不寫入）
    python scripts/fix_play_cases.py --fix      # 寫入
退出碼：0 = 全部解析成功（或寫入成功）；1 = 有品牌解析不到；2 = 腳本出錯
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
PLAYBOOK = os.path.join(REF, "00-打法库.md")

# ─────────────────────────────────────────────────────────────
# 指派表：打法 id → [(品牌關鍵詞, 檔號前綴), …]
#   關鍵詞用**卡標題裡的連續字串**（不必完整），腳本會做子串解析。
#   檔號前綴＝`cases/NN-…md` 的 NN，用來把搜索限定在那一檔（避免同名品牌跨檔誤命中）。
# ─────────────────────────────────────────────────────────────
ASSIGN = {
    # ── §1 認知類
    "1.8": [("蜜雪冰城", "01"), ("貨拉拉", "45")],
    "1.9": [("黃天鵝", "29"), ("空刻意面", "40"), ("貓太子", "41")],
    "1.10": [("瑞幸", "27"), ("石頭科技", "20")],
    "1.11": [("老鋪黃金", "32"), ("山下有松", "33")],
    "1.12": [("足力健", "23"), ("認養一頭牛", "29")],
    "1.13": [("喜茶 × FENDI", "01"), ("蜜雪冰城", "01")],
    # ── §2 內容類
    "2.2": [("韓束", "03"), ("完美日記", "03")],
    "2.3": [("韓束", "03"), ("珀萊雅", "03")],
    "2.4": [("淄博燒烤", "15"), ("天水麻辣燙", "10")],
    "2.5": [("老鄉雞", "01"), ("蜜雪冰城", "01")],
    "2.6": [("石頭科技", "20"), ("大疆", "05")],
    "2.7": [("老鄉雞", "01")],
    "2.8": [("老鄉雞", "01"), ("衛龍", "02")],
    "2.9": [("韓束", "03"), ("金典", "26")],
    "2.10": [("韓束", "03"), ("開心麻花", "26")],
    "2.11": [("蜜雪冰城", "01"), ("泡泡瑪特", "14")],
    "2.12": [("老鄉雞", "01"), ("保險經紀人", "16")],
    "2.13": [("海底撈", "01"), ("老鄉雞", "01")],
    "2.14": [("海馬體", "42"), ("麥當勞中國", "01")],
    "2.15": [("蛋仔派對", "08"), ("蜜雪冰城", "01")],
    "2.16": [("海馬體", "42"), ("妃魚", "33")],
    "2.17": [("妃魚", "33"), ("山下有松", "33")],
    # ── §3 投放類
    "3.1": [("完美日記", "03"), ("韓束", "03")],
    "3.2": [("石頭科技", "20"), ("長城坦克", "06")],
    "3.3": [("珀萊雅", "03"), ("認養一頭牛", "29")],
    "3.4": [("淄博燒烤", "15"), ("太二", "01")],
    "3.5": [("完美日記", "03"), ("無憂傳媒", "51")],
    "3.6": [("完美日記", "03"), ("珀萊雅", "03")],
    "3.7": [("韓束", "03"), ("空刻意面", "40")],
    "3.8": [("分眾傳媒", "51"), ("愛華仕", "33")],
    "3.9": [("長城坦克", "06"), ("愛華仕", "33")],
    "3.10": [("海馬體", "42"), ("古茗", "27")],
    "3.11": [("妃魚", "33"), ("完美日記", "03")],
    # ── §4 私域類
    "4.1": [("完美日記", "03"), ("元氣森林", "02")],
    "4.2": [("寶島眼鏡", "31"), ("蜜絲卡倫", "43")],
    "4.3": [("寶島眼鏡", "31"), ("Notion", "21")],
    "4.4": [("寶島眼鏡", "31"), ("完美日記", "03")],
    "4.5": [("瑞幸", "27"), ("麥當勞中國", "01")],
    "4.6": [("瑞幸", "27"), ("寶島眼鏡", "31")],
    "4.7": [("瑞幸", "27"), ("蜜雪冰城", "01")],
    "4.8": [("瑞幸", "27"), ("寶島眼鏡", "31")],
    "4.9": [("瑞幸", "27"), ("轉轉", "24")],
    "4.10": [("蜜絲卡倫", "43"), ("寶島眼鏡", "31")],
    "4.11": [("寶島眼鏡", "31"), ("完美日記", "03")],
    # ── §5 渠道類
    "5.1": [("韓束", "03"), ("空刻意面", "40")],
    "5.2": [("妃魚", "33"), ("山下有松", "33")],
    "5.3": [("太二", "01"), ("海馬體", "42")],
    "5.4": [("喜茶 × FENDI", "01"), ("海馬體", "42")],
    "5.5": [("蜜雪冰城", "01"), ("老鳳祥", "32")],
    "5.6": [("蜜雪冰城", "01"), ("完美日記", "03")],
    "5.7": [("三全", "40"), ("錢大媽", "29")],
    "5.8": [("石頭科技", "20"), ("SHEIN", "20")],
    "5.9": [("蜜雪冰城", "01"), ("安井", "40")],
    # ── §6 事件與話題類
    "6.1": [("瑞幸 × 貴州茅台", "01"), ("喜茶 × FENDI", "01")],
    "6.2": [("麥當勞中國", "01"), ("中國婚博會", "43")],
    "6.3": [("海底撈", "01"), ("老鄉雞", "01")],
    "6.4": [("淄博燒烤", "15"), ("哈爾濱", "10"), ("天水麻辣燙", "10")],
    "6.5": [("老鄉雞", "01"), ("瑞幸 × 貴州茅台", "01")],
    "6.6": [("山下有松", "33"), ("盤子女人坊", "42")],
    "6.7": [("太二", "01"), ("老鄉雞", "01")],
    "6.8": [("老鄉雞", "01"), ("長城坦克", "06")],
    "6.9": [("鐘薛高", "02"), ("西貝", "01")],
    "6.10": [("順豐", "45"), ("白象", "02")],
    # ── §7 信任類
    "7.1": [("明月鏡片", "31"), ("石頭科技", "20")],
    "7.2": [("石頭科技", "20"), ("明月鏡片", "31")],
    "7.3": [("珀萊雅", "03"), ("寶島眼鏡", "31")],
    "7.4": [("珀萊雅", "03"), ("老鋪黃金", "32")],
    "7.5": [("黃天鵝", "29"), ("明月鏡片", "31")],
    "7.6": [("老鄉雞", "01"), ("認養一頭牛", "29")],
    "7.7": [("完美日記", "03"), ("珀萊雅", "03")],
    "7.8": [("只二", "24"), ("石頭科技", "20")],
    # ── §8 定價與轉化類
    "8.1": [("老鋪黃金", "32"), ("瑞幸", "27")],
    "8.2": [("蜜雪冰城", "01"), ("瑞幸", "27")],
    "8.3": [("海馬體", "42"), ("瑞幸", "27")],
    "8.4": [("釘釘", "21"), ("Zoom", "21")],
    "8.5": [("蜜雪冰城", "01"), ("麥當勞中國", "01")],
    "8.6": [("DR", "32"), ("海馬體", "42")],
    "8.7": [("瑞幸", "27"), ("蜜雪冰城", "01")],
    "8.8": [("韓束", "03"), ("空刻意面", "40")],
    "8.9": [("海馬體", "42"), ("寶島眼鏡", "31")],
    "8.10": [("蜜雪冰城", "01"), ("瑞幸", "27")],
    "8.11": [("完美日記", "03"), ("韓束", "03")],
    # ── §9 診斷類
    "9.1": [("海馬體", "42"), ("寶島眼鏡", "31")],
    "9.2": [("認養一頭牛", "29"), ("盤子女人坊", "42")],
    "9.3": [("蜜絲卡倫", "43"), ("寶島眼鏡", "31")],
    "9.4": [("霸王茶姬", "27"), ("瑞幸", "27")],
    "9.5": [("空刻意面", "40"), ("貓太子", "41")],
    "9.6": [("錢大媽", "29"), ("百果園", "29")],
    "9.7": [("自嗨鍋", "40"), ("認養一頭牛", "29")],
    # ── §10 特殊主體
    "10.1": [("錢大媽", "29"), ("足力健", "23")],
    "10.2": [("太二", "01"), ("海底撈", "01")],
    "10.3": [("元氣森林", "02"), ("空刻意面", "40")],
    "10.4": [("蜜雪冰城", "01"), ("名創優品", "14")],
    "10.5": [("妙鴨相機", "42"), ("Notion", "21")],
    "10.6": [("飛書", "21"), ("京東物流", "45")],
    "10.7": [("好客山東", "19"), ("淄博燒烤", "15")],
}

RE_PLAY_H = re.compile(r"^###\s+(\d+)\.(\d+)\s+(.+?)\s*$")
RE_HIGHER = re.compile(r"^#{1,2}\s+\S")


def cards_in(prefix):
    """→ {卡標題: 檔名}"""
    out = {}
    for f in sorted(glob.glob(os.path.join(CASES, f"{prefix}-*.md"))):
        base = os.path.basename(f)
        t = open(f, encoding="utf-8").read()
        for m in re.finditer(r"(?m)^###\s+3\.\d+\s+(.+?)\s*$", t):
            out[m.group(1)] = base
    return out


CACHE = {}


def resolve(kw, prefix):
    """品牌關鍵詞 → (檔名, 卡標題)；找不到回 (None, None)"""
    if prefix not in CACHE:
        CACHE[prefix] = cards_in(prefix)
    hits = [(t, f) for t, f in CACHE[prefix].items() if kw in t]
    if not hits:
        return None, None
    # 取最短標題（最具體、最少修飾）
    hits.sort(key=lambda x: len(x[0]))
    return hits[0][1], hits[0][0]


def brand_of(title):
    return re.split(r"[｜|（(]", title)[0].strip()


def build_line(pid):
    """→ 新的案例行文字；解析不到就回 (None, 失敗清單)"""
    ok, miss, grouped = [], [], {}
    for kw, prefix in ASSIGN.get(pid, []):
        f, t = resolve(kw, prefix)
        if not f:
            miss.append(f"{kw}@{prefix}")
            continue
        grouped.setdefault(f, []).append(brand_of(t))
        ok.append(kw)
    if miss or not grouped:
        return None, miss or ["（指派表為空）"]
    parts = [f"`cases/{f}`（{'、'.join(bs)}）" for f, bs in grouped.items()]
    return "**案例**：" + "；".join(parts) + "。", []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true")
    a = ap.parse_args()

    lines = open(PLAYBOOK, encoding="utf-8").read().split("\n")
    # 定位每條打法的 **案例** 行號
    cur, hit = None, {}
    for i, l in enumerate(lines):
        m = RE_PLAY_H.match(l)
        if m:
            cur = f"{int(m.group(1))}.{m.group(2)}"
            continue
        if RE_HIGHER.match(l):
            cur = None
            continue
        if cur and l.startswith("**案例**"):
            hit[cur] = i
    # 「無案例行」的打法：行尾補一行
    append_at = {}
    cur = None
    for i, l in enumerate(lines):
        m = RE_PLAY_H.match(l)
        if m:
            cur = f"{int(m.group(1))}.{m.group(2)}"
            continue
        if RE_HIGHER.match(l):
            cur = None
            continue
    # 找出有指派但缺案例行的打法 → 插在該打法區塊末尾
    tail = {}
    cur = None
    for i, l in enumerate(lines):
        m = RE_PLAY_H.match(l)
        if m:
            if cur is not None:
                tail[cur] = i - 1
            cur = f"{int(m.group(1))}.{m.group(2)}"
            continue
        if RE_HIGHER.match(l) and not m:
            if cur is not None:
                tail[cur] = i - 1
                cur = None
    if cur is not None:
        tail[cur] = len(lines) - 1

    good, bad, unchanged = [], [], []
    for pid in sorted(ASSIGN, key=lambda x: (int(x.split(".")[0]), int(x.split(".")[1]))):
        newline, miss = build_line(pid)
        if newline is None:
            bad.append((pid, miss))
            continue
        if pid in hit:
            if lines[hit[pid]].strip() == newline:
                unchanged.append(pid)
                continue
            good.append((pid, "改", hit[pid], newline))
        else:
            if pid not in tail:
                bad.append((pid, ["找不到插入位置"]))
                continue
            good.append((pid, "補", tail[pid] + 1, newline))

    print(f"指派 {len(ASSIGN)} 條｜可寫 {len(good)} 條｜已是最新 {len(unchanged)} 條｜解析失敗 {len(bad)} 條")
    if bad:
        print("\n❌ 解析不到的品牌（需修正指派表）：")
        for pid, miss in bad:
            print(f"   §{pid} {ASSIGN and ''}{miss}")
    if not a.fix:
        print("\n前 12 條新案例行預覽：")
        for pid, mode, ln, nl in good[:12]:
            print(f"   §{pid} [{mode} L{ln + 1}] {nl[:110]}")
        print("\n（驗證模式，未寫入。加 --fix 執行）")
        sys.exit(1 if bad else 0)

    if bad:
        print("\n⚠️ 有解析失敗項 → **不寫入任何一行**（避免半套修復）")
        sys.exit(1)

    for pid, mode, ln, nl in sorted(good, key=lambda x: -x[2]):
        if mode == "改":
            lines[ln] = nl
        else:
            lines.insert(ln, nl)
    new = "\n".join(lines)
    # 硬不變式：除 `**案例**：` 行外，其餘逐行不變
    o = [x for x in open(PLAYBOOK, encoding="utf-8").read().split("\n") if not x.startswith("**案例**")]
    n = [x for x in new.split("\n") if not x.startswith("**案例**")]
    if o != n:
        d = [x for x, y in zip(o, n) if x != y]
        print(f"❌ 不變式失敗：非案例行被改動（{len(d)} 行）例：{d[0][:60]!r}")
        sys.exit(1)
    open(PLAYBOOK, "w", encoding="utf-8").write(new)
    print(f"✅ 已寫入 {len(good)} 條案例行（改 {sum(1 for g in good if g[1] == '改')}／補 "
          f"{sum(1 for g in good if g[1] == '補')}）；非案例行逐行未變")
    print("接著跑：python scripts/kb_audit.py --no-compose  與  python scripts/case_play_index.py --fix")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 執行出錯：{type(e).__name__}: {e}")
        sys.exit(2)
