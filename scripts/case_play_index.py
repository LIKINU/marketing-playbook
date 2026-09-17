#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
案例卡 ↔ 打法 双向索引 · case_play_index.py

为什么有它（2026-09-17，用户第五点）：
    「这个 skills 里面有很多东西，在交付物部分，根本就没有体现出很多东西根本就没有运用好」

    根因（已确诊，机制性的）：
      · `composer.py` 产出的骨架里，「可抄案例」写的是
        `来源 cases/01-餐饮与茶饮.md，请展开「他面对什么问题…」` —— **是占位符，不是内容**；
      · 「理论依据」只给 `超级符号（03 §C1）` 这样的**编号**；
      · `knowledge_map.json` 的映射粒度**只到编号**，不注入内容。
      → 模型拿到骨架，等于拿到一份「去哪查」的清单，而不是「已经查到」的材料。

    两头都要接：
      A. **案例 → 打法**（本脚本）：每张案例卡标出「这张卡可以抄哪几条打法」，
         索引写进 `scripts/case_play_index.json` 供 composer 消费；
      B. **打法 → 案例内容**（composer.py）：把卡片的「做了什么／结果」摘要真注入骨架。

映射怎么来（不靠人编，靠既有资料反推）：
    `00-打法库.md` 的每条打法底下有一行 `**案例**：`，
    里面写着 `cases/NN-xxx.md`（品牌名…） —— 这是**人工写过的权威映射**，
    本脚本只做「反向解析 + 品牌名对到卡片标题」。

做什么：
    1. 解析 104 条打法的 `**案例**` 行 → (打法 id, 案例档, 品牌名集合)
    2. 每个案例档的每张卡（`### 3.N 品牌｜…`）→ 用品牌名匹配 → 可抄打法清单
    3. `--fix` 时：
       a. 写出 `scripts/case_play_index.json`
       b. 在每张卡的标题行下插入一行
          `> **可抄打法**：§1.1 超级符号 ｜ §7.2 品牌谚语   （来自 00-打法库 案例行）`

硬不变式（--fix 时）：
    1. 只**插入**一行 `> **可抄打法**：…`，其余逐行不变
    2. 幂等：已有该行的卡跳过
    3. 匹配不到任何打法的卡**不插行**（宁可不标，不乱标）

用法：
    python scripts/case_play_index.py              # 只报告匹配率
    python scripts/case_play_index.py --fix        # 写索引 ＋ 打标
    python scripts/case_play_index.py --list 01    # 看某一档的匹配明细
退出码：0 正常；2 脚本出错
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
    """从「（蜜雪冰城「雪王」，2018 年起、旺旺旺仔）」抽出品牌名候选"""
    p = (paren or "").strip()
    p = re.sub(r"^[（(]|[）)]$", "", p)        # 先脱掉最外层括号
    p = re.sub(r"[（(][^）)]*[）)]", "", p)     # 再去掉内层括注
    out = []
    for x in re.split(r"[、；，,]", p):
        x = x.strip()
        x = re.sub(r"[「『].*$", "", x).strip()          # 「雪王」之后不要
        x = re.sub(r"\d{4}\s*年.*$", "", x).strip()      # 「2018 年起」不要
        x = re.sub(r"^(见|参见|另见)\s*", "", x)
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
            # §0.1–0.3 是「§0 总表」的分块标题，不是打法；打法从 §1.1 起
            if pid.startswith("0.") or "§" in m.group(2):
                cur = None
                continue
            cur = pid
            plays[cur] = {"name": m.group(2), "refs": []}
            continue
        if cur is None:
            continue
        if l.startswith("### "):        # 下一节（非打法）→ 收尾
            cur = None
            continue
        if l.startswith("**案例**"):
            for m2 in RE_CASEREF.finditer(l):
                plays[cur]["refs"].append((m2.group(1), hint_candidates(m2.group(2))))
            # 例外：案例行整行的品牌名（「见 cases/01-... 各品牌的定位起点段落」这种）
            plays[cur]["raw"] = l
    return plays


def hint_candidates(hint):
    """从打法的 `**案例**` 行抽出「可用来对卡片标题的品牌候选」。

    为什么要抽「前缀」：案例行写的是描述句——「瑞幸 × 茅台酱香拿铁，2023」、
    「成分党口播帐号开头结构」——而卡片标题是「瑞幸 × 贵州茅台｜酱香拿铁（2023）」。
    直接整串比对命中率只有 1.8%（2026-09-17 实测）；切成 2–6 字前缀后升到 31%，
    且抽样检查全部正确（超级符号→蜜雪冰城、品牌谚语→王老吉、包装即媒体→农夫山泉…）。
    **多出来的部分一律进「缺口清单」，不硬凑。**
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
    print(f"打法 {len(plays)} 条｜其中有案例指向的 {len(plays) - len(no_ref)} 条")
    if no_ref:
        print(f"  无案例行（{len(no_ref)}）：{'、'.join('§' + x for x in sorted(no_ref)[:20])}"
              + (" …" if len(no_ref) > 20 else ""))
    print(f"案例卡 {len(cards)} 张｜可对上至少一条打法的 {len(tagged)} 张"
          f"（{len(tagged) / max(len(cards), 1) * 100:.1f}%）")

    # 每张卡对上的打法数分布
    dist = {}
    for k in card2play:
        dist[len(card2play[k])] = dist.get(len(card2play[k]), 0) + 1
    print("  每卡打法数分布：" + "｜".join(f"{k} 条→{v} 卡" for k, v in sorted(dist.items())))

    # 每条打法指向几张卡
    empty = [p for p in plays if plays[p]["refs"] and not play2card.get(p)]
    if empty:
        print(f"  ⚠️ 有案例指向但对不上任何卡片（{len(empty)} 条）：{'、'.join('§' + x for x in sorted(empty))}")

    if a.list:
        for cf, title in cards:
            if cf.startswith(a.list):
                got = card2play.get((cf, title))
                print(f"  {'✔' if got else '·'} {title[:52]:<54} "
                      + ("｜".join(f"§{p} {n}" for p, n in got) if got else "—"))

    if not a.fix:
        print("\n（报告模式，未写入。加 --fix 产出索引并打标）")
        sys.exit(0)

    # ── 写索引
    idx = {
        "_note": "案例卡 ↔ 打法 双向索引（由 case_play_index.py 从 00-打法库 的案例行反推）。"
                 "composer.py 消费此档注入真实案例内容。改映射请改 00-打法库 的案例行后重跑。",
        "_version": "2026-09-17",
        "play_to_cards": {p: [{"file": f, "card": t} for f, t in v] for p, v in play2card.items()},
        "card_to_plays": {f"{f}||{t}": [{"play": p, "name": n} for p, n in v]
                          for (f, t), v in card2play.items()},
    }
    json.dump(idx, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n✅ 索引已写入 {os.path.relpath(OUT_JSON, ROOT)}")

    # ── 打标
    #    先**剥掉所有旧标**再重打 —— 因为标里的文字（打法名、覆盖率提示）会随
    #    00-打法库 的修复而变化，「下一行已有标就跳过」会让旧标永远留著（第一版就这样）。
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
                         "**未标记 ≠ 不适用**，只代表该卡尚未被任何打法指名）")
            ins += 1
        if had == ins and raw == raw:
            skipped += 1
        if "\n".join(out) != "\n".join(raw):
            open(f, "w", encoding="utf-8").write("\n".join(out))
            changed += 1
        total_ins += ins
    print(f"✅ 打标完成：{changed} 档更新／{total_ins} 张卡有标｜未变 {skipped} 档")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
