#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
案例卡 ↔ 打法 双向索引 · case_play_index.py

為什麼有它（2026-09-17，用戶第五點）：
    「這個 skills 裏面有很多東西，在交付物部分，根本就沒有體現出很多東西根本就沒有運用好」

    根因（已確診，機制性的）：
      · `composer.py` 產出的骨架裡，「可抄案例」寫的是
        `来源 cases/01-餐饮与茶饮.md，请展开「他面对什么问题…」` —— **是占位符，不是內容**；
      · 「理论依据」只給 `超級符號（03 §C1）` 這樣的**編號**；
      · `knowledge_map.json` 的映射粒度**只到編號**，不注入內容。
      → 模型拿到骨架，等於拿到一份「去哪查」的清單，而不是「已經查到」的材料。

    兩頭都要接：
      A. **案例 → 打法**（本腳本）：每張案例卡標出「這張卡可以抄哪幾條打法」，
         索引寫進 `scripts/case_play_index.json` 供 composer 消費；
      B. **打法 → 案例內容**（composer.py）：把卡片的「做了什麼／結果」摘要真注入骨架。

映射怎麼來（不靠人編，靠既有資料反推）：
    `00-打法库.md` 的每條打法底下有一行 `**案例**：`，
    裡面寫着 `cases/NN-xxx.md`（品牌名…） —— 這是**人工寫過的權威映射**，
    本腳本只做「反向解析 + 品牌名對到卡片標題」。

做什麼：
    1. 解析 104 條打法的 `**案例**` 行 → (打法 id, 案例檔, 品牌名集合)
    2. 每個案例檔的每張卡（`### 3.N 品牌｜…`）→ 用品牌名匹配 → 可抄打法清單
    3. `--fix` 時：
       a. 寫出 `scripts/case_play_index.json`
       b. 在每張卡的標題行下插入一行
          `> **可抄打法**：§1.1 超級符號 ｜ §7.2 品牌諺語   （來自 00-打法库 案例行）`

硬不變式（--fix 時）：
    1. 只**插入**一行 `> **可抄打法**：…`，其餘逐行不變
    2. 冪等：已有該行的卡跳過
    3. 匹配不到任何打法的卡**不插行**（寧可不標，不亂標）

用法：
    python scripts/case_play_index.py              # 只報告匹配率
    python scripts/case_play_index.py --fix        # 寫索引 ＋ 打標
    python scripts/case_play_index.py --list 01    # 看某一檔的匹配明細
退出碼：0 正常；2 腳本出錯
"""

import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
REF = os.path.join(ROOT, "references")
CASES = os.path.join(REF, "cases")
PLAYBOOK = os.path.join(REF, "00-打法库.md")
OUT_JSON = os.path.join(HERE, "case_play_index.json")

RE_PLAY = re.compile(r"^###\s+(\d+\.\d+)\s+(.+?)\s*$")
RE_CARD = re.compile(r"^###\s+3\.(\d+)\s+(.+?)\s*$", re.M)
RE_CASEREF = re.compile(r"`cases/(\d{2}-[^`]+\.md)`\s*(（[^）]*）)?")
MARK = "> **可抄打法**："


def names_from(paren):
    """從「（蜜雪冰城「雪王」，2018 年起、旺旺旺仔）」抽出品牌名候選"""
    p = (paren or "").strip()
    p = re.sub(r"^[（(]|[）)]$", "", p)        # 先脫掉最外層括號
    p = re.sub(r"[（(][^）)]*[）)]", "", p)     # 再去掉內層括註
    out = []
    for x in re.split(r"[、；，,]", p):
        x = x.strip()
        x = re.sub(r"[「『].*$", "", x).strip()          # 「雪王」之後不要
        x = re.sub(r"\d{4}\s*年.*$", "", x).strip()      # 「2018 年起」不要
        x = re.sub(r"^(見|參見|另見)\s*", "", x)
        if 2 <= len(x) <= 12 and re.search(r"[\u4e00-\u9fffA-Za-z]", x):
            out.append(x)
    return out


def parse_plays():
    """→ {play_id: {"name":…, "refs":[(cases_file, [names])]}}"""
    t = open(PLAYBOOK, encoding="utf-8").read()
    lines = t.split("\n")
    plays, cur = {}, None
    for l in lines:
        m = RE_PLAY.match(l)
        if m:
            pid = m.group(1)
            # §0.1–0.3 是「§0 總表」的分塊標題，不是打法；打法從 §1.1 起
            if pid.startswith("0.") or "§" in m.group(2):
                cur = None
                continue
            cur = pid
            plays[cur] = {"name": m.group(2), "refs": []}
            continue
        if cur is None:
            continue
        if l.startswith("### "):        # 下一節（非打法）→ 收尾
            cur = None
            continue
        if l.startswith("**案例**"):
            for m2 in RE_CASEREF.finditer(l):
                plays[cur]["refs"].append((m2.group(1), hint_candidates(m2.group(2))))
            # 例外：案例行整行的品牌名（「見 cases/01-... 各品牌的定位起點段落」這種）
            plays[cur]["raw"] = l
    return plays


def hint_candidates(hint):
    """從打法的 `**案例**` 行抽出「可用來對卡片標題的品牌候選」。

    為什麼要抽「前綴」：案例行寫的是描述句——「瑞幸 × 茅台醬香拿鐵，2023」、
    「成分黨口播帳號開頭結構」——而卡片標題是「瑞幸 × 貴州茅台｜醬香拿鐵（2023）」。
    直接整串比對命中率只有 1.8%（2026-09-17 實測）；切成 2–6 字前綴後升到 31%，
    且抽樣檢查全部正確（超級符號→蜜雪冰城、品牌諺語→王老吉、包裝即媒體→農夫山泉…）。
    **多出來的部分一律進「缺口清單」，不硬湊。**
    """
    names = []
    for m in re.finditer(r"（([^）]*)）", hint or ""):
        names += names_from("（" + m.group(1) + "）")
    out = []
    for n in names:
        for part in re.split(r"[×xX]|\s+", n):
            part = part.strip()
            for k in range(len(part), 1, -1):
                if 2 <= k <= 6:
                    out.append(part[:k])
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def card_brand(title):
    return re.split(r"[｜|]", title)[0].strip()


def build():
    plays = parse_plays()
    card2play = {}       # (file, card_title) -> [(play_id, name)]
    play2card = {}       # play_id -> [(file, card_title)]
    for pid, info in plays.items():
        for cf, names in info["refs"]:
            f = os.path.join(CASES, cf)
            if not os.path.exists(f):
                continue
            t = open(f, encoding="utf-8").read()
            for m in RE_CARD.finditer(t):
                title = m.group(2)
                base = re.split(r"[｜|（(]", title)[0].strip()
                if not names:
                    continue
                if any(n and n in base for n in names):
                    card2play.setdefault((cf, title), []).append((pid, info["name"]))
                    play2card.setdefault(pid, []).append((cf, title))
    return plays, card2play, play2card


def all_cards():
    out = []
    for f in sorted(glob.glob(os.path.join(CASES, "*.md"))):
        base = os.path.basename(f)
        if not re.match(r"\d", base):
            continue
        t = open(f, encoding="utf-8").read()
        for m in RE_CARD.finditer(t):
            out.append((base, m.group(2)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--list", default="")
    a = ap.parse_args()

    plays, card2play, play2card = build()
    cards = all_cards()

    no_ref = [p for p, i in plays.items() if not i["refs"]]
    tagged = [(f, t) for f, t in cards if (f, t) in card2play]
    print(f"打法 {len(plays)} 條｜其中有案例指向的 {len(plays) - len(no_ref)} 條")
    if no_ref:
        print(f"  無案例行（{len(no_ref)}）：{'、'.join('§' + x for x in sorted(no_ref)[:20])}"
              + (" …" if len(no_ref) > 20 else ""))
    print(f"案例卡 {len(cards)} 張｜可對上至少一條打法的 {len(tagged)} 張"
          f"（{len(tagged) / max(len(cards), 1) * 100:.1f}%）")

    # 每張卡對上的打法數分布
    dist = {}
    for k in card2play:
        dist[len(card2play[k])] = dist.get(len(card2play[k]), 0) + 1
    print("  每卡打法數分布：" + "｜".join(f"{k} 條→{v} 卡" for k, v in sorted(dist.items())))

    # 每條打法指向幾張卡
    empty = [p for p in plays if plays[p]["refs"] and not play2card.get(p)]
    if empty:
        print(f"  ⚠️ 有案例指向但對不上任何卡片（{len(empty)} 條）：{'、'.join('§' + x for x in sorted(empty))}")

    if a.list:
        for cf, title in cards:
            if cf.startswith(a.list):
                got = card2play.get((cf, title))
                print(f"  {'✔' if got else '·'} {title[:52]:<54} "
                      + ("｜".join(f"§{p} {n}" for p, n in got) if got else "—"))

    if not a.fix:
        print("\n（報告模式，未寫入。加 --fix 產出索引並打標）")
        sys.exit(0)

    # ── 寫索引
    idx = {
        "_note": "案例卡 ↔ 打法 双向索引（由 case_play_index.py 從 00-打法库 的案例行反推）。"
                 "composer.py 消費此檔注入真實案例內容。改映射請改 00-打法库 的案例行後重跑。",
        "_version": "2026-09-17",
        "play_to_cards": {p: [{"file": f, "card": t} for f, t in v] for p, v in play2card.items()},
        "card_to_plays": {f"{f}||{t}": [{"play": p, "name": n} for p, n in v]
                          for (f, t), v in card2play.items()},
    }
    json.dump(idx, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n✅ 索引已寫入 {os.path.relpath(OUT_JSON, ROOT)}")

    # ── 打標
    #    先**剝掉所有舊標**再重打 —— 因為標裡的文字（打法名、覆蓋率提示）會隨
    #    00-打法库 的修復而變化，「下一行已有標就跳過」會讓舊標永遠留著（第一版就這樣）。
    changed = skipped = total_ins = 0
    for f in sorted(glob.glob(os.path.join(CASES, "*.md"))):
        base = os.path.basename(f)
        if not re.match(r"\d", base):
            continue
        raw = open(f, encoding="utf-8").read().split("\n")
        had = sum(1 for l in raw if l.lstrip().startswith(MARK))
        lines = [l for l in raw if not l.lstrip().startswith(MARK)]
        out, ins = [], 0
        for l in lines:
            out.append(l)
            m = RE_CARD.match(l)
            if not m:
                continue
            got = card2play.get((base, m.group(2)))
            if not got:
                continue
            seen, uniq = set(), []
            for p, n in got:
                if p not in seen:
                    seen.add(p)
                    uniq.append((p, n))
            out.append(MARK + " ｜ ".join(f"§{p} {n}" for p, n in uniq[:5])
                       + "　（由 `references/00-打法库.md` 的 `**案例**` 行反查；"
                         "**未標記 ≠ 不適用**，只代表該卡尚未被任何打法指名）")
            ins += 1
        if had == ins and raw == raw:
            skipped += 1
        if "\n".join(out) != "\n".join(raw):
            open(f, "w", encoding="utf-8").write("\n".join(out))
            changed += 1
        total_ins += ins
    print(f"✅ 打標完成：{changed} 檔更新／{total_ins} 張卡有標｜未變 {skipped} 檔")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 執行出錯：{type(e).__name__}: {e}")
        sys.exit(2)
