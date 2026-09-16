#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
composer.py — 方案组装器（marketing-playbook 的「真·skill」引擎）

為什麼要有它（用戶 2026-09-16 定調）：
    「模型根本做不了強制使用，它只做到讀取，相當於 prompt / RAG，不是 skill。」
    → 所以把「知識應用」從『模型自己讀、自願引用』改成『腳本機械組裝』：
      輸入客戶狀況 → 從 00-打法库 §0 機械匹配 3–7 條打法 → 自動拉取對應
      03 模型 / 49 學者 / cases 案例 → 輸出「知識已注入好」的方案骨架。
      模型只做填空與本地化，**繞不過知識庫**。

用法：
    python composer.py --rules rules.json --out skeleton.md
    python composer.py --rules rules.json --out skeleton.md --tier 速覽|標準|G端 --top 5

輸入：門禁《任務規則表》JSON（gate_check.py 用的那份）
輸出：方案骨架 .md（打法／理論依據／可抄案例已注入；`【填】` 處待模型補）
      輸出**天然滿足 selfcheck 第【7】【8】關**（打法組合／知識庫引用）。

退出碼：0 正常；1 輸入缺失；2 執行錯誤
"""

import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, "..", "references")
PLAYBOOK = os.path.join(REF, "00-打法库.md")
KMAP = os.path.join(HERE, "knowledge_map.json")

FILL = "【填】"
WARN = "⚠️"


def read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


# ─────────────────────────────────────────────────────────────
# 1. 解析 00-打法库：取出所有 §X.Y 打法 + 其「怎麼做／怎麼驗收／案例」等
# ─────────────────────────────────────────────────────────────
def parse_playbook(text):
    plays = []
    lines = text.splitlines()
    cur = None
    for ln in lines:
        m = re.match(r"^###\s+(\d+)\.(\d+)\s+(.+?)\s*$", ln)
        if m:
            major, minor, name = int(m.group(1)), m.group(2), m.group(3).strip()
            if major == 0:          # §0 是總表，不是打法
                cur = None
                continue
            if cur:
                plays.append(cur)
            cur = {
                "id": f"{major}.{minor}", "major": major, "name": name,
                "blk": [], "raw": "",
            }
            continue
        # 遇到更高層標題（章）就結束當前打法
        if re.match(r"^#{1,2}\s+\S", ln) and cur:
            plays.append(cur)
            cur = None
            continue
        if cur is not None:
            cur["blk"].append(ln)
    if cur:
        plays.append(cur)

    for p in plays:
        blk = "\n".join(p["blk"])
        p["raw"] = blk
        p["name"] = re.sub(r"（.*?）\s*$", "", p["name"]).strip()
        p["situation"] = _cell(blk, "什麼情況用")
        p["not_for"] = _cell(blk, "不適用")
        p["budget"] = _cell(blk, "預算量級")
        p["period"] = _cell(blk, "見效週期")
        p["who"] = _cell(blk, "誰來做")
        p["difficulty"] = _cell(blk, "難度")
        p["howto"] = _between(blk, r"\*\*怎麼做\*\*", r"\*\*關鍵技巧\*\*").strip()
        p["verify"] = _after(blk, r"\*\*怎麼驗收\*\*")
        p["cases_raw"] = _after(blk, r"\*\*案例\*\*")
        p["cases"] = re.findall(r"`?(cases/\d{2}-[^`\s（(]+\.md)`?", blk)
    return [p for p in plays if p["situation"]]


def _cell(blk, key):
    m = re.search(r"\|\s*" + re.escape(key) + r"\s*\|\s*(.+?)\s*\|", blk)
    return m.group(1).strip() if m else ""


def _between(blk, a, b):
    m = re.search(a + r".*?\n(.*?)" + b, blk, flags=re.S)
    return m.group(1) if m else ""


def _after(blk, key):
    m = re.search(key + r"[：:]\s*(.+)", blk)
    return m.group(1).strip() if m else ""


# ─────────────────────────────────────────────────────────────
# 2. 客戶狀況 → 卡點類型（A–H）＋ 文本關鍵詞
# ─────────────────────────────────────────────────────────────
CARDPOINT_KW = [
    ("A", ["記不住", "记不住", "不知道", "认知", "認知", "品牌", "没印象", "沒印象", "说不清", "說不清"]),
    ("B", ["不买", "不買", "不下单", "不下單", "转化", "轉化", "成交", "购买决策", "購買決策", "没人买", "沒人買"]),
    ("C", ["铺货", "鋪貨", "渠道", "賣不到", "卖不到", "触达", "觸達", "流量", "曝光", "鋪出去", "铺出去"]),
    ("D", ["不敢买", "不敢買", "信任", "担心", "擔心", "怕", "怀疑", "懷疑", "不信"]),
    ("E", ["复购", "復購", "回头", "回頭", "再买", "再買", "留存", "私域", "沉淀", "沉澱", "复购率"]),
    ("F", ["定价", "定價", "价格", "價格", "太贵", "太貴", "便宜", "毛利", "客单", "客單"]),
    ("G", ["团队", "團隊", "执行", "執行", "组织", "組織", "没人做", "沒人做", "人手", "人力"]),
    ("H", ["合规", "合規", "违规", "違規", "红线", "紅線", "法规", "法規", "处罚", "處罰"]),
]
CARDPOINT_NAME = {"A": "认知", "B": "交易", "C": "渠道", "D": "信任",
                  "E": "复购/私域", "F": "定价", "G": "组织", "H": "合规"}


def infer_cardpoints(gate):
    """卡點類型：以「卡在哪」為主（權重 3），其餘欄位為輔（權重 1）；取前 2，避免全命中。"""
    primary = str(gate.get("卡在哪", "")) + str(gate.get("卡點", ""))
    rest = " ".join(str(v) for k, v in gate.items() if k not in ("卡在哪", "卡點"))
    score = {}
    for c, kws in CARDPOINT_KW:
        s = sum(3 for k in kws if k in primary) + sum(1 for k in kws if k in rest)
        if s:
            score[c] = s
    top = [c for c, _ in sorted(score.items(), key=lambda x: -x[1])][:2]
    return top or ["B"]


def bigrams(s):
    s = re.sub(r"\s+", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


# ─────────────────────────────────────────────────────────────
# 3. 選打法：bigram 重疊 + 章節加成 + 預算可行性
# ─────────────────────────────────────────────────────────────
def select_plays(plays, gate, kmap, top, cardpoints):
    """選打法：① SKILL.md §二 路由表機械匹配（主） → ② bigram 補位（輔）。確定性、可調。"""
    client = " ".join(str(v) for v in gate.values())
    cb = bigrams(client)
    name_index = {p["name"]: p for p in plays}

    # ① 匹配路由规则 → 方向关键词（round-robin 交錯，保證從不同狀況各取一條）
    matched = [r for r in kmap.get("路由规则", [])
               if any(k in client for k in r["kw"])]
    buckets = [list(r["方向"]) for r in matched]
    direction, i = [], 0
    while any(len(b) > i for b in buckets):
        for b in buckets:
            if i < len(b):
                direction.append(b[i])
        i += 1

    picked, seen = [], set()

    def _take(p):
        if p and p["id"] not in seen:
            picked.append(p)
            seen.add(p["id"])

    for d in direction:
        if len(picked) >= top:
            break
        cand = name_index.get(d)
        if not cand:
            cands = [p for p in plays if d in p["name"] or p["name"] in d]
            cand = cands[0] if cands else None
        _take(cand)

    # ② 不足則用 bigram 重疊補位（並含卡點章節加成）
    if len(picked) < top:
        boost = [m for c in cardpoints for m in kmap["cardpoint_to_major"].get(c, [])]
        scored = sorted(
            plays,
            key=lambda p: -(len(bigrams(p["name"] + p["situation"] + p.get("howto", "")) & cb)
                            + (3 if p["major"] in boost else 0)),
        )
        for p in scored:
            if len(picked) >= top:
                break
            _take(p)

    # ③ 多樣性：每章最多 2 條（超出往後遞補，最後若不足則放寬）
    final, per = [], {}
    for p in picked:
        if per.get(p["major"], 0) >= 2:
            continue
        final.append(p)
        per[p["major"]] = per.get(p["major"], 0) + 1
        if len(final) >= top:
            break
    for p in picked:
        if len(final) >= top:
            break
        if p not in final:
            final.append(p)
    return final[:top]


# ─────────────────────────────────────────────────────────────
# 4. 注入「理論依據」：打法 → 03 模型碼 / 49 書籍（確定性映射）
# ─────────────────────────────────────────────────────────────
def theory_for(play, kmap):
    """這條打法的「理論依據」＝ **override 優先 ＋ 章內相關度補位**。

    ⚠️ 2026-09-17 改成「可累加」：第一版的 override 是**整組替換** ——
    那表示只要給某條打法加一個新模型，就會把它原本對的模型全擠掉。
    改成累加後，才能安全地把 03 手冊裡原本挑不到的模型逐條綁進具體打法
    （否則「接進 major_theory」只是讓 JSON 好看，`theory_for` 每類只取 3 個，
     多數模型永遠浮不上來 —— 實測：接入 33 個後仍只有 14 個能被挑中）。
    """
    # ⚠️ 2026-09-17 修：第一版取「第一個命中的 key」，而字典裡有個 2 字符的舊鍵 `'VI'`
    #    會先把 `'VI 一致性'` 擋掉（短鍵遮蔽長鍵）。改成**最長鍵優先**，
    #    與 `infer_industry()` 的規則一致 —— 越長＝越具體＝越該贏。
    ov, best_len = None, -1
    for key in kmap["play_overrides"]:
        if key in play["name"] and len(key) > best_len:
            ov, best_len = kmap["play_overrides"][key], len(key)
    major = kmap["major_theory"].get(str(play["major"]), {})
    priority = list(ov["models"]) if ov else []
    cm = list(major.get("models", []))
    bg = bigrams(play["name"] + play.get("situation", ""))

    def _rel(code):
        nm = _M03_RE.get(code.upper(), "")
        return len(bigrams(nm) & bg) if nm else 0

    rest = sorted([c for c in cm if c not in priority], key=lambda c: (-_rel(c), c))
    # override 是**人手明確指定的**，那就全部給出來（不足 3 個再用章內相關度補位）——
    # 若同樣套 [:3]，被 append 到既有清單尾端的模型會永遠浮不上來
    # （實測：接入 33 個模型後 I5 就是這樣一直挑不到）。
    models = priority + rest[:max(0, 3 - len(priority))]
    books = list(ov["books"]) if ov else list(major.get("books", []))
    if not ov:
        books = books[:2]
    return models, books


def model_label(code):
    """用模型碼在 03 手冊裡找中文名（如 C1 → 超級符號）。找不到就只給碼。"""
    m = _M03_RE.get(code)
    return f"{m}（03 §{code}）" if m else f"（03 §{code}）"


_M03_RE = {}
_M03_BRIEF = {}      # code → 「解決什麼問題」原文
_M03_STEPS = {}      # code → [「做什麼」, …]
_CARDS = {}          # cases 檔名 → [ {brand, one, what, result, points} … ]


def load_model_names(path):
    if not os.path.exists(path):
        return
    t = read(path)
    for mm in re.finditer(r"^###\s*([A-Ma-m]\d{1,2})[｜|·\s]+([^\n（(]+)", t, flags=re.M):
        _M03_RE[mm.group(1).upper()] = mm.group(2).strip()

    # ── 2026-09-17：連「內容」一起讀（原本只讀到名字，骨架裡只剩編號 → 用戶投訴：
    #    「單純寫一個文字…根本沒有辦法讓 Agent 理解並完整讀取」）。
    #    → 讀 ① 解決什麼問題（一句）＋ ② 怎麼用 表格裡的「做什麼」欄（前 3 步）。
    blocks = re.split(r"(?m)^###\s*", t)[1:]
    for b in blocks:
        m = re.match(r"([A-Ma-m]\d{1,2})[｜|\s]", b)
        if not m:
            continue
        code = m.group(1).upper()
        mo = re.search(r"\*\*①\s*解決什麼問題\*\*\s*\n+(.+?)(?:\n\s*\n|\n\*\*)", b, flags=re.S)
        if mo:
            _M03_BRIEF[code] = re.sub(r"\s+", " ", mo.group(1)).strip()
        mt = re.search(r"\*\*②\s*怎麼用.*?\*\*\s*\n(.*?)(?:\n\s*\*\*|\Z)", b, flags=re.S)
        if mt:
            steps = [re.sub(r"\s+", " ", r[1]).strip()
                     for r in re.findall(r"(?m)^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|", mt.group(1))]
            _M03_STEPS[code] = [s for s in steps if s]


def model_brief(code, nsteps=3):
    """把『模型名（03 §C1）』升級成『模型名（03 §C1）—— 解決 X；第 1–3 步：…』"""
    name = _M03_RE.get(code, "")
    head = f"{name}（03 §{code}）" if name else f"（03 §{code}）"
    prob = _M03_BRIEF.get(code, "")
    steps = _M03_STEPS.get(code, [])[:nsteps]
    if not prob and not steps:
        return head
    out = head
    if prob:
        out += f" —— 解決「{prob[:80]}」"
    if steps:
        out += "；前幾步：" + " → ".join(s[:28] for s in steps)
    return out


# ─────────────────────────────────────────────────────────────
# 案例卡讀取（2026-09-17 新增）
#    原本骨架的「可抄案例」只寫 `来源 cases/01-xxx.md，请展开…` —— 是**占位符**。
#    這裡把案例卡的真實內容抽出來，讓骨架本身就帶著證據。
#    兼容兩種案例清單格式：① 表格（`| # | 案例 | 一句話 | 最硬的一個數字 |`）
#                          ② 條列（`**1｜品牌（年份）· 誰做的：X**` ＋ 做了什麼／結果／可抄的點）
# ─────────────────────────────────────────────────────────────
def parse_cards(cases_file):
    """→ [{"brand":…, "one":…, "what":…, "result":…, "points":…}]

    兼容 **三種** 案例清單寫法（第一版只認前兩種，第三種靜默回 0 張卡 ——
    29／32／33／51 因此一直抽不出卡片，kb_audit 的 L2 才把它抓出來）：
      ① 表格：`| # | 案例 | 一句話 | 最硬的一個數字 |`
      ② 條列 A：`**1｜品牌（年份）· 誰做的：X · 深度卡 §3.1**` ＋ `- **做了什麼**：…`
      ③ 條列 B：`1. **品牌**｜角度（年份）`
    另外：**機構檔（46–51）沒有「案例清單」，卡片就是 `### 3.N 標題`** → 直接以標題為卡。
    """
    if cases_file in _CARDS:
        return _CARDS[cases_file]
    p = os.path.join(REF, "cases", os.path.basename(cases_file))
    out = []
    if os.path.exists(p):
        t = read(p)
        m = re.search(r"(?m)^##\s*[一二三四五六七八九十]*、?\s*案例清單\s*$", t)
        if m:
            body = t[m.end():]
            nxt = re.search(r"(?m)^##\s", body)
            if nxt:
                body = body[:nxt.start()]
            # ① 表格格式
            for r in re.findall(r"(?m)^\|\s*([\d.]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", body):
                if r[1].strip() in ("案例", "---"):
                    continue
                out.append({"brand": r[1].strip(), "one": r[2].strip(),
                            "result": r[3].strip(), "what": "", "points": ""})
            # ②③ 條列格式（兩種寫法）
            if not out:
                cur = None
                for ln in body.split("\n"):
                    s = ln.strip()
                    h = (re.match(r"^\*\*\d+\s*[｜|]\s*(.+?)\*\*", s)
                         or re.match(r"^\d+\s*[.、]\s*\*\*(.+?)\*\*", s))
                    if h:
                        rest = h.group(1).strip()
                        brand = re.split(r"\s*[｜|]\s*", rest)[0].strip() if re.search(r"[｜|]", rest) else rest
                        cur = {"brand": brand, "one": "", "what": "", "result": "", "points": ""}
                        out.append(cur)
                        continue
                    if cur is None:
                        continue
                    for key, field in (("做了什麼", "what"), ("結果", "result"), ("可抄的點", "points")):
                        mk = re.match(r"^[-*]\s*\*\*" + key + r"\*\*[：:]\s*(.+)$", s)
                        if mk:
                            cur[field] = mk.group(1).strip()
        if not out:
            # 機構檔（46–51）：沒有案例清單，卡片即 `### 3.N 標題`
            for mm in re.finditer(r"(?m)^###\s+3\.\d+\s+(.+?)\s*$", t):
                out.append({"brand": mm.group(1).strip(), "one": "", "what": "",
                            "result": "", "points": ""})
        else:
            # **2026-09-17 新增：清單 ∪ 深度卡**。
            #    實測 25 個檔裡有 **48 張深卡不在自己的案例清單裡** ——
            #    只讀清單的 Agent 永遠看不到它們，composer 也引用不到。
            #    這裡把「只在深度拆解」的卡一併收進來（標 deep_only 供溯源）。
            have = {re.split(r"[｜|（(]", c["brand"])[0].strip() for c in out}
            for mm in re.finditer(r"(?m)^###\s+3\.\d+\s+(.+?)\s*$", t):
                title = mm.group(1).strip()
                base = re.split(r"[｜|（(]", title)[0].strip()
                if base and not any(base == h or base.startswith(h) or h.startswith(base)
                                    for h in have if h):
                    out.append({"brand": title, "one": "", "what": "", "result": "",
                                "points": "", "deep_only": True})
                    have.add(base)
    _CARDS[cases_file] = out
    return out


def case_pairs(hint):
    """把 `**案例**` 行拆成 **[(檔名, 品牌關鍵詞)]** —— 保留「品牌屬哪一檔」的對應。

    為什麼一定要保留對應（2026-09-17）：第一版只抽出「品牌候選集」，
    再對**每一個被引用的檔**都做一次子串匹配 → 同一個品牌會從多檔各中一次
    （實測：淄博燒烤、石頭科技、瑞幸 各被抽出兩份），引用行與實際取到的卡不一致。
    """
    out = []
    for m in re.finditer(r"`(cases/\d{2}-[^`]+\.md)`\s*[（(]([^）)]*)[）)]", hint or ""):
        cf, inner = m.group(1), m.group(2)
        for x in re.split(r"[、；，,]", inner):
            x = re.sub(r"[「『].*$", "", x.strip()).strip()
            x = re.sub(r"\d{4}\s*年.*$", "", x).strip()
            if x:
                out.append((cf, x))
    return out


def hint_candidates(hint):
    """從打法的 `**案例**` 行抽出**品牌前綴候選**（跨檔合集；僅用於粗篩，正取用 case_pairs）。"""
    out = []
    for _, x in case_pairs(hint):
        for part in re.split(r"[×xX]|\s+", x):
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


def pick_cards_ex(play, ind, limit=2):
    """挑可抄案例 —— **两段式（2026-09-17 第二版）**，回 `[(file, card, 來源)]`。

    第一段（精准）：打法 `**案例**` 行**指名**的品牌。指不出来就空着，
    **绝不回落成「那个档的第一张卡」**（旧逻辑实测踩过：§4.1「包裹卡引流」的案例行
    只写「食品品牌的包裹卡引流」，回落成 `cases/02` 第一张卡 = 王老吉，与包裹卡毫无关系）。

    第二段（**行业适配**，2026-09-17 新增）：若还不足 limit，就从**客户所在行业档**
    （`ind`）里挑一张与这条打法语义最接近的卡。为什么必须加这一段：
    没有它，一个银发养老的客户会被配上美妆／茶饮的例子 ——
    **「可抄案例」不可抄，等于没有案例。**
    """
    hint = play.get("cases_raw", "")
    pairs = case_pairs(hint)
    picks, seen = [], set()
    # **配額設計（2026-09-17）**：給了行業檔時，答案要「1 張精準對標 ＋ 1 張本行業可抄」。
    #   全給指名卡 → 銀發客戶拿到美妝例子（不可抄）；全給行業卡 → 失去跨行業標桿。
    #   所以指名段最多佔 limit-1，最後一格一定留給客戶所在行業。
    named_quota = max(1, limit - 1) if ind else limit
    for cf, kw in pairs:
        for c in parse_cards(cf):
            base = re.split(r"[｜|（(]", c["brand"])[0].strip()
            if base and kw in c["brand"] and base not in seen:
                seen.add(base)                       # ← 以品牌去重，跨檔也不會重複
                picks.append((cf, c, "指名"))
                break                                # 每個（檔, 品牌）只取首次出現那張
        if len(picks) >= named_quota:
            break
    if ind and len(picks) < limit:
        for cf, c in best_cards_for_play(ind, play, (limit - len(picks)) + 2):
            base = re.split(r"[｜|（(]", c["brand"])[0].strip()
            if base not in seen:
                seen.add(base)
                picks.append((cf, c, "行業適配"))
                if len(picks) >= limit:
                    break
    return picks[:limit]


def pick_cards(play, ind, limit=2):
    """兼容層：只回 (file, card) 兩元組。"""
    return [(cf, c) for cf, c, _ in pick_cards_ex(play, ind, limit)]


def has_named_case(play):
    """這條打法的 `**案例**` 行**指名**了品牌嗎（第一段能不能取到東西）。"""
    return bool(pick_cards_ex(play, "", limit=1))


_PLAY_BG = None


def best_cards_for_play(ind, play, n=1):
    """从某个行业档里，按 bigram 重叠挑与这条打法最贴近的卡（确定性、可复现）。"""
    global _PLAY_BG
    cards = parse_cards(ind)
    if not cards:
        return []
    if _PLAY_BG is None:
        _PLAY_BG = {}
    key = (ind, play.get("id", ""), play["name"])
    q = bigrams(play["name"] + play.get("situation", ""))
    scored = []
    for c in cards:
        txt = c["brand"] + " " + (c.get("one") or "") + " " + (c.get("points") or "") + " " + (c.get("what") or "")
        g = bigrams(txt[:300])
        if not g:
            continue
        scored.append((len(q & g) / max(len(q | g), 1), c))
    scored.sort(key=lambda x: (-x[0], x[1]["brand"]))
    _PLAY_BG[key] = scored
    return [(ind, c) for ov, c in scored[:n] if ov > 0]


def uncovered_plays(plays, ind):
    """回傳「案例行指不出任何可引用卡片」的打法清單（給骨架列出待補項）。"""
    out = []
    for p in plays:
        if not has_named_case(p):
            why = ("案例行未指名品牌" if p.get("cases") else "無案例行")
            out.append((p, why))
    return out


def card_line(cf, c, maxlen=200):
    """一行卡片摘要（含出處檔名，方便回溯）。"""
    brand = re.split(r"\s*[·・]\s*", c["brand"])[0].strip()      # 去掉「· 誰做的：…」
    body = c.get("what") or c.get("one") or ""
    res = c.get("result") or ""
    txt = f"**{brand}**"
    if body:
        txt += f" —— {body}"
    if res:
        txt += f"　▶ 結果：{res}"
    if len(txt) > maxlen:
        txt = txt[:maxlen].rstrip() + "…"
    return f"{txt}（`{cf}`）"


def _book(b):
    """49 書籍字串 → 引用格式。容忍沒有「｜作者」的字串，不崩。

    ⚠️ 2026-09-17：這是**內部版**（帶 `49` 編號），只進 internal 文件。
       交付稿一律用 `book_explain()` —— 展開成白話，不帶編號。
    """
    parts = [x.strip() for x in b.split("｜")]
    name = parts[0]
    author = parts[1] if len(parts) > 1 else ""
    return f"{name}（{author}49）" if author else f"{name}（49）"


# ─────────────────────────────────────────────────────────────
# 4b. 交付稿專用：把「理論／書籍／案例」展開成白話（2026-09-17 新增）
#
#   用戶訴求（原話）：「不是只是引用了就行了，不是拿了案例就行了，
#   說有什麼理論是沒有任何意義也沒有任何作用的 —— 而是要根據這些案例、
#   這些理論、這些觀點寫具體的操作、具體的做法。」
#   「交付出來的東西應該是可以直接看的，而不是有例如像（打法库 §4.1）
#    這樣的引用。」
#
#   → 所以：**知識含量只增不減，座標全部剝掉**。
#     §X.X／03 §C1／（作者49）／`cases/xx.md` 這些內部座標對客戶毫無意義
#     （他不知道去哪查，也不知道那是什麼），全部改寫成可讀的內容。
# ─────────────────────────────────────────────────────────────
_B49 = {}          # 《書名》 → {"what": 核心主張, "effect": 效果}


def load_books(path):
    """讀 49 書籍檔，抽出每本書的「③ 做了什麼（核心主張）」＋「⑤ 效果」。

    為什麼要讀內容而不只給書名（與 `load_model_names` 同一個教訓）：
    只給一個書名＝「說有什麼理論沒有任何意義」，執行 AI 據此寫不出具體做法。
    """
    if not os.path.exists(path):
        return
    t = read(path)
    for b in re.split(r"(?m)^###\s*", t)[1:]:
        m = re.match(r"[\d.]+\s*(《[^》]+》)", b)
        if not m:
            continue
        d = {"what": "", "effect": ""}
        mw = re.search(r"\*\*③\s*做了什麼\*\*[：:]?\s*(.*?)(?=\n\s*[-*]\s*\*\*⑤|\Z)",
                       b, flags=re.S)
        if mw:
            d["what"] = re.sub(r"\s+", " ", mw.group(1).replace("**", "")).strip()
        me = re.search(r"\*\*⑤\s*效果\*\*[：:]?\s*(.*?)(?=\n\s*[-*]\s*\*\*[⑥⑦]|\Z)",
                       b, flags=re.S)
        if me:
            d["effect"] = re.sub(r"\s+", " ", me.group(1).replace("**", "")).strip()
        _B49[m.group(1)] = d


def _load_t2s():
    """载入内置繁→简单字表（`scripts/t2s_data.py`，机械生成）。

    為什麼不用 opencc／zhconv：那要多一個依賴，跨平台（沒網／沒 pip 的環境）就掛。
    這張表覆蓋本知識庫實際用到的全部繁體字，零依賴、純 dict 查表。
    載入失敗（檔案被刪）→ 退回不轉換，**不拋錯** —— 繁體最終由 selfcheck 兜底。
    """
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        from t2s_data import T2S_PAIRS as _P
        return {_P[i]: _P[i + 1] for i in range(0, len(_P) - 1, 2)}
    except Exception:
        return {}


_T2S_MAP = _load_t2s()


def _t2s_light(s):
    """繁→简（逐字查表）。知識庫原文是繁體，交付稿必須簡體 —— 在注入時就轉掉，
    不要留給模型（模型會漏，selfcheck 就會卡在交付前）。"""
    if not s or not _T2S_MAP:
        return s
    return "".join(_T2S_MAP.get(ch, ch) for ch in s)


def book_explain(b, maxlen=150):
    """書籍 → 「《書名》（作者）：核心主張…」白話，**不帶 `49` 編號**。"""
    name = b.split("｜")[0].strip()
    author = b.split("｜")[1].strip() if "｜" in b else ""
    d = _B49.get(name, {})
    txt = name
    if author:
        txt += f"（{author}）"
    body = d.get("what") or d.get("effect") or ""
    if body:
        txt += f"：{body}"
    if len(txt) > maxlen:
        txt = txt[:maxlen].rstrip() + "…"
    return _t2s_light(txt)


def model_explain(code, nsteps=4):
    """模型碼 → 「模型名：解決什麼問題。具體用法：第1步…；第2步…」

    與 `model_brief()` 的差別：**不帶（03 §C1）座標**，且步驟給到 4 步（更詳盡）。
    座標拿掉、內容加長 —— 對客戶來說可讀性與可操作性都更高。
    """
    name = _M03_RE.get(code, "")
    prob = _M03_BRIEF.get(code, "")
    steps = _M03_STEPS.get(code, [])[:nsteps]
    if not name and not prob and not steps:
        return ""
    out = name or ""
    if prob:
        out += f"：解决的是「{prob[:100]}」"
    if steps:
        out += "。具体用法：" + "；".join(
            f"第{i}步 {s[:40]}" for i, s in enumerate(steps, 1))
    return _t2s_light(out)


def card_line_public(c, maxlen=260):
    """案例卡 → 交付稿用的一行（**不帶 `cases/xx.md` 路徑與卡號**）。

    形態（用戶 2026-09-17 選定）：`**品牌** —— 他做了什麼　▶ 结果：數字`
    保留品牌名作佐證（可信度），不暴露內部檔名。
    """
    brand = re.split(r"\s*[·・]\s*", c["brand"])[0].strip()
    body = c.get("what") or c.get("one") or ""
    res = c.get("result") or ""
    txt = f"**{brand}**" if brand else ""
    if body:
        txt += f" —— {body}"
    if res:
        txt += f"　▶ 结果：{res}"
    txt = _t2s_light(txt).strip()
    if len(txt) > maxlen:
        txt = txt[:maxlen].rstrip() + "…"
    return txt


# ─────────────────────────────────────────────────────────────
# 5. 產出骨架
# ─────────────────────────────────────────────────────────────
def parse_steps(howto):
    """把打法库的「怎麼做」拆成结构化步骤：[(动作, 产出), ...]"""
    steps = []
    for ln in howto.splitlines():
        m = re.match(r"^\s*\d+[.、]\s*(.+)$", ln)
        if not m:
            continue
        body = m.group(1).strip()
        out = ""
        mo = re.search(r"產出[：:]\s*(.+)$", body)
        if mo:
            out = mo.group(1).strip().rstrip("。")
            body = body[:mo.start()].strip().rstrip("。")
        if body:
            steps.append((body, out))
    return steps


def infer_industry(gate, kmap):
    """從『賣什麼／品類／賣給誰』推 cases 行業檔（確定性關鍵詞匹配）。"""
    txt = " ".join(str(gate.get(k, "")) for k in ("賣什麼", "品类", "品類", "賣給誰", "行业", "行業"))
    # 取「最長命中關鍵詞」（最長＝最具體），避免「城市」「区域」這類泛詞誤命中（2026-09-16）
    best, best_len = "", 0
    for kw, f in kmap.get("industry_to_cases", {}).items():
        if kw in txt and len(kw) > best_len:
            best, best_len = f, len(kw)
    return best


def play_block(i, p, kmap, ind=""):
    """交付稿用的打法段 —— **零內部座標**（2026-09-17 重寫）。

    舊版長這樣，客戶全看不懂：
        **打法 1｜包裹卡引流**（打法库 §4.1）
        - 理论依据：AIDA（03 §C1）＋《影响力》（西奥迪尼49）＋（打法库 §4.1）
        - 可抄案例：xx —— …（`cases/12-xxx.md`）

    新版：座標全剝，知識展開成「別人怎麼做的」＋「為什麼這麼做」。
    """
    models, books = theory_for(p, kmap)
    # 理論：**不帶編號**，且比舊版更詳盡（模型：解決什麼問題 ＋ 前 4 步用法）
    mtxt = "　".join(x for x in (model_explain(c, 4) for c in models) if x)
    btxt = "　".join(book_explain(b) for b in books)
    picks = pick_cards_ex(p, ind)
    if picks:
        cases = "\n" + "\n".join(f"  - {card_line_public(c)}" for cf, c, src in picks)
    else:
        cases = (f"\n  - 暂无可直接参照的公开案例 —— 本条按下方原理推导执行，"
                 f"上线前先小范围试跑一周再决定是否放量")
    # 逐步骤实操：每步都写清「动作 / 谁做 / 时间 / 物料·话术 / 产出」
    steps = parse_steps(p["howto"])
    if steps:
        s_lines = [
            f"  {k}. {_t2s_light(act)} ｜ 时间：{FILL} ｜ 谁做：{FILL} ｜ 物料·话术：{FILL} ｜ 产出：{_t2s_light(out) or FILL}"
            for k, (act, out) in enumerate(steps, 1)
        ]
        howto = "\n".join(s_lines)
    else:
        howto = "  1. " + FILL
    why = "　".join(x for x in (mtxt, f"参考观点：{btxt}" if btxt else "") if x) or FILL
    return (
        f"**打法 {i}｜{_t2s_light(p['name'])}**\n"
        f"- **为什么用它**：{_t2s_light(p['situation']) or FILL}\n"
        f"- **具体动作（精准到每一步）**：\n{howto}\n"
        f"- **谁做｜花多少｜多久见效**：{_t2s_light(p['who']) or FILL}｜"
        f"{_t2s_light(p['budget']) or FILL}｜{_t2s_light(p['period']) or FILL}\n"
        f"- **验收指标**：{_t2s_light(p['verify']) or FILL}\n"
        f"- **可抄案例（别人怎么做的、结果如何）**：{cases}\n"
        f"- **为什么这么做（背后的道理，照这个改就不会跑偏）**：{why}\n"
    )


def build_lite(rules, plays, kmap, cardpoints, today):
    """速覽檔：給小微企業／個案「快速看懂打法」——1–2 頁，只留決策要素。"""
    client = rules.get("client", "客户")
    gate = rules.get("gate", {})
    cp = "／".join(f"{c}（{CARDPOINT_NAME.get(c, c)}）" for c in cardpoints)
    ind = infer_industry(gate, kmap)
    lines = [
        f"# {client} · 打法速览\n",
        f"> 一页看懂「该打哪几条、怎么打、花多少」。\n",
        f"> 生成日期：{today}\n\n",
        f"## 一、卡点一句话\n- 问题类型：**{cp}**\n- 真正的卡点：{FILL}（不是 X —— 是 Y）\n\n",
        f"## 二、建议打法（{len(plays)} 条）\n",
    ]
    for i, p in enumerate(plays, 1):
        models, books = theory_for(p, kmap)
        steps = parse_steps(p["howto"])[:3]
        s = "；".join(f"{k}) {_t2s_light(a)}" for k, (a, _) in enumerate(steps, 1))
        picks = pick_cards_ex(p, ind, limit=1)
        cl = (f"\n- 可抄案例：{card_line_public(picks[0][1], 180)}" if picks else "")
        why = "；".join(x for x in (model_explain(c, 3) for c in models) if x)
        if books:
            why = (why + "；" if why else "") + "、".join(book_explain(b) for b in books)
        lines.append(
            f"**{i}. {_t2s_light(p['name'])}** —— {_t2s_light(p['situation'])}\n"
            f"- 怎么打：{s or FILL}\n"
            f"- 谁做｜花多少｜多久见效：{_t2s_light(p['who']) or FILL}｜"
            f"{_t2s_light(p['budget']) or FILL}｜{_t2s_light(p['period']) or FILL}\n"
            f"- 验收指标：{_t2s_light(p['verify']) or FILL}\n"
            f"- 为什么这么做：{why or FILL}{cl}\n"
        )
    lines += [
        f"\n## 三、预算量级\n{FILL}（各条打法预算相加；含盈亏线测算）\n\n",
        f"## 四、下一步（只写一件）\n{FILL}\n",
    ]
    return "\n".join(lines)


def build_skeleton(rules, plays, kmap, tier, cardpoints):
    client = rules.get("client", "客户")
    gate = rules.get("gate", {})
    today = datetime.date.today().isoformat()
    cp = "／".join(f"{c}（{CARDPOINT_NAME.get(c, c)}）" for c in cardpoints)
    ind = infer_industry(gate, kmap)      # 同一個行業檔在「案例庫提示」與「案例注入」共用

    if tier == "速览":
        return build_lite(rules, plays, kmap, cardpoints, today)

    # 2026-09-17：頭部施工說明全部移除（「本骨架由 composer.py 機械組裝」「打法匹配自
    #   `00-打法库 §0 总表`」「同類行業案例庫：references/cases/xx.md」…）。
    #   這些是給執行 AI 的工單，客戶看不懂也不需要看 —— 改寫進 internal 文件。
    head = (
        f"# {client} · 营销方案\n\n"
        f"> 生成日期：{today}\n\n"
        f"## 执行摘要\n- 目标：{FILL}\n- 主线一句话：{FILL}\n"
        f"- 核心打法：{'、'.join(_t2s_light(p['name']) for p in plays)}\n"
        f"- 预期 KPI：{FILL}\n- 盈亏线：{FILL}\n\n"
    )

    diagnosis = (
        f"## 一 · 现状分析\n### 1.1 问题类型与目标\n"
        f"- 问题类型：**{cp}**（八类：认知／交易／渠道／信任／复购／定价／组织／合规）\n"
        f"- 生意目标：{FILL}\n\n### 1.2 真正的卡点\n"
        f"> {FILL}：不是 X —— 是 Y\n\n### 1.3 已排除的假设\n{FILL}\n\n"
        f"### 1.4 竞争与关联品牌扫描\n- 头号对手（按业务环节全链条拆：获客→信任→成交→履约→复购）：{FILL}\n"
        f"- 其他对手逐个：{FILL}\n- 核心差异点一句话：{FILL}\n\n"
        f"### 1.5 约束与风险底线\n{FILL}\n\n"
    )

    strategy = "## 二 · 策略\n### 2.0 打法组合（核心）\n\n"
    strategy += "".join(play_block(i + 1, p, kmap, ind) + "\n" for i, p in enumerate(plays))
    strategy += "### 2.0.1 可抄案例（别人是怎么做的、结果如何、我们怎么用）\n"
    for i, p in enumerate(plays):
        picks = pick_cards_ex(p, ind, limit=2)
        if picks:
            strategy += f"- **打法 {i+1}（{_t2s_light(p['name'])}）**：\n"
            for cf, c, src in picks:
                strategy += f"  - {card_line_public(c, 320)}\n"
                if c.get("points"):
                    strategy += f"    - 可抄的点：{_t2s_light(c['points'])[:200]}\n"
            strategy += f"    - **我们怎么用**：{FILL}（面对的问题／我们改哪一步／预期结果）\n"
        else:
            strategy += (f"- **打法 {i+1}（{_t2s_light(p['name'])}）**：{FILL}"
                         "（暂无可直接参照的公开案例，按该打法的原理推导执行）\n")

    # 2026-09-17：原「2.0.2 知识库缺口」整章移出交付稿 —— 那是**我們自己的維護待辦**
    #   （哪条打法的案例行没指名品牌、要去补哪个文件），客户既看不懂也无义务替我们补库。
    #   改寫進 internal 文件（`--internal`），執行 AI 與維護者看那份即可。
    strategy += (
        f"\n### 2.1 三次收窄（时间／人群／动作）\n{FILL}\n\n"
        f"### 2.2 货盘与机制\n{FILL}\n\n"
    )

    positioning = (
        "## 三 · 定位与口径\n### 3.1 定位与差异化支点\n"
        f"- 定位语（一句话）：{FILL}\n"
        f"- 学理依据：{'；'.join(x for x in (model_explain(c, 3) for c in ['B5', 'C1']) if x)}；"
        f"{book_explain(kmap['major_theory']['1']['books'][0])} —— 说明用在定位的哪一步\n"
        f"- 三个支点（各跟一个可查证事实）：{FILL}\n\n"
        f"### 3.2 禁用词与红线（什么话绝不能说）\n{FILL}\n\n"
        f"### 3.3 对不同人说什么\n{FILL}\n\n"
    )

    reach = f"## 四 · 触达与渠道\n- 渠道选择（为什么用/不用）：{FILL}\n- 用户路径：{FILL}\n- 硬风险：{FILL}\n\n"
    copy_ = f"## 五 · 落地文案与物料\n- 物料清单（放在哪／写什么／多少钱）：{FILL}\n- 一线话术：{FILL}\n\n"
    kpi = f"## 六 · KPI 与追踪机制\n- 追踪工具（土办法＋成本）：{FILL}\n- 每日/每周只看这几个数：{FILL}\n- 决策节奏：{FILL}\n\n"
    budget = f"## 七 · 预算明细\n| # | 分项 | 金额（元） |\n|---|---|---|\n| 1 | {FILL} | {FILL} |\n| — | **合计** | **{FILL}** |\n\n### 7.2 盈亏线测算\n{FILL}\n\n"
    exec_ = (
        f"## 八 · 执行与风控\n### 8.1 行动清单（做什么／谁做／什么时候／花多少／验收）\n{FILL}\n\n"
        f"### 8.2 执行人力检查（人力不足时的删减顺序）\n{FILL}\n\n"
        f"### 8.3 风险清单（每条写清四件套：为什么会发生／预警信号／兜底预案／预防动作）\n{FILL}\n\n"
        f"### 8.4 关键假设与验证\n{FILL}\n\n"
        f"### 8.5 待解决问题清单\n{FILL}\n\n"
        f"### 8.6 不承诺的事\n{FILL}\n\n"
    )

    # ── G端专章 ──
    g_extra = ""
    if tier == "G端":
        g_extra = (
            "## 九 · 政策依据与项目背景（G端必写）\n"
            "- 政策依据（上位规划／文件号／条款）：【填】\n- 项目背景与必要性：【填】\n"
            "- 与上级规划的对应关系：【填】\n- 资金来源与预算合规：【填】\n\n"
            "## 十 · 汇报与评审\n### 10.1 汇报稿/PPT 骨架\n"
            "- 封面／背景／目标／方案／预算／进度／预期成效／保障措施：【填】\n\n"
            "### 10.2 评审答疑口径（预判评委问题＋标准答法）\n【填】\n\n"
            "## 十一 · 合规与舆情红线\n"
            "- 公文格式与字数【规范】：符合公文排版/章节/字数/页数要求\n"
            "- 广告法与平台政策红线：【填】\n- 舆情风险清单与应对：【填】\n\n"
        )

    # 2026-09-17：原「附件 · 交付自检单」整章移出交付稿 —— 自檢單是**內部質檢記錄**，
    #   按協定它就該原樣輸出在 AI 的**回覆中**給用戶看，而不是印在客戶方案的最後一頁。
    #   → 改寫進 internal 文件（見 `build_internal`），交付稿只留客戶要看的內容。
    body = head + diagnosis + strategy + positioning + reach + copy_ + kpi + budget + exec_ + g_extra
    return body


# ─────────────────────────────────────────────────────────────
# 5b. 內部文件（2026-09-17 新增）
#     交付稿要「乾淨可直接提交」，但施工說明／知識庫缺口／自檢單**不能丟** ——
#     那就另開一份檔：只有執行 AI 與維護者看，永遠不進 .docx。
# ─────────────────────────────────────────────────────────────
SELFCHECK_ROWS = [
    "门禁 13 项已问全（含目标字数）并写入《任务规则表》",
    "未经验证的假设已在文首单独标注",
    "文档结构完整（八篇）",
    "字数达标（任务规则表确认）",
    "每条打法五要素（做什么/谁/何时/花多少/怎么验收）",
    "禁用词与口径章节存在，物料文案已逐字对照",
    "预算分项加总＝合计；引用数字全部有来源",
    "KPI 可测（基准值＋观测方式）＋决策节奏已写",
    "执行人力检查＋删减顺序已写",
    "关键假设＋验证＋Plan B 已写",
    "交付稿无内部坐标（§／文件路径／模型码／49 编号／脚本名）",
    "交付回复中已附本自检单",
]


def build_internal(rules, plays, kmap, ind, tier, today):
    """施工說明 ＋ 知識庫缺口 ＋ 自檢單 —— **不進交付稿**。`--internal` 輸出。"""
    client = rules.get("client", "客户")
    lines = [
        f"# {client} · 内部施工说明（禁止写入交付稿）\n",
        f"> 本文件由 `composer.py` 生成，仅给执行 AI 与知识库维护者看。",
        f"**其中任何一行都不得出现在给客户的 .docx 里**。\n\n",
        f"## 一、本次组装参数\n",
        f"- 生成日期：{today}　档位：{tier}\n",
        f"- 客户：{client}\n",
        f"- 命中行业档：`{ind or '未识别（按品类自选 cases/01–45）'}`\n",
        f"- 选中打法：{len(plays)} 条\n\n",
        f"## 二、施工要求\n",
        f"1. 骨架由脚本机械组装：**打法／理论依据／可抄案例均已注入，请勿删改**。\n",
        f"2. 你只需补 `【填】` 处的数字与本地化描述。\n",
        f"3. 注入的知识原文可能残留繁体（已做轻量转换，但不彻底）",
        f"—— 交付前务必全文转简体，selfcheck 会按繁体字数卡（>15 种＝硬错误）。\n",
        f"4. 注入内容可能含广告法禁用词，逐字对照禁用词表后再交付。\n",
        f"5. **不得新增任何内部坐标**：§X.X、`cases/xx.md`、`references/`、",
        f"`03 §C1`、`（作者49）`、`模式 NN`、`composer.py`、`SKILL.md` —— ",
        f"selfcheck 第【10】关会拦截。\n\n",
        f"## 三、知识库缺口（要去补的维护待办）\n",
    ]
    gaps = uncovered_plays(plays, ind)
    if gaps:
        lines.append(f"> 以下 {len(gaps)} 条打法的 `00-打法库` 案例行**未指名品牌**，"
                     f"因此未能自动注入卡片。交付前二选一：\n")
        lines.append(f"> ① 去 `references/cases/{ind or '（本行业档）'}` 的「案例清單」"
                     f"挑 1–2 张，把「品牌＋做了什麼＋結果」抄进骨架；\n")
        lines.append(f"> ② 补 `references/00-打法库.md` 对应条目 `**案例**` 行的指名品牌"
                     f"（一次性修复，全库受益）。\n")
        lines.append(f"> ⛔ 既不补卡片也不补案例行，就在交付稿写"
                     f"「暂无可直接参照的公开案例」—— **不许编案例**。\n\n")
        for p, why in gaps:
            lines.append(f"- **{p['name']}**（打法库 §{p['id']}）—— {why}\n")
    else:
        lines.append("> 无缺口：本方案引用的每条打法都指得出具体案例卡。\n")
    lines.append(f"\n## 四、打法溯源（内部对照用，交付稿里已改为白话）\n")
    for i, p in enumerate(plays, 1):
        models, books = theory_for(p, kmap)
        lines.append(f"- 打法 {i} `{p['name']}` → 打法库 §{p['id']}；"
                     f"模型 {', '.join(models) or '—'}；"
                     f"书籍 {', '.join(_book(b) for b in books) or '—'}\n")
        for cf, c, src in pick_cards_ex(p, ind, limit=2):
            lines.append(f"    - 案例卡（`{cf}`）：{card_line(cf, c, 200)}〔{src}〕\n")
    lines.append("\n## 五、交付自检单（12 项 —— 原样输出到回复里，不要放进文档）\n")
    lines.append("| # | 自检项 | 结果 |\n|---|---|---|\n")
    for n, r in enumerate(SELFCHECK_ROWS, 1):
        lines.append(f"| {n} | {r} | 【填】 |\n")
    return "\n".join(lines)


def _dump(path, text):
    """寫檔（自動建父目錄）—— 免去「目錄不存在」這類低級失敗。"""
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ─────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tier", default="标准", choices=["速览", "标准", "G端"])
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--internal", default="",
                    help="額外輸出「內部施工說明」到這個路徑（施工要求／知識庫缺口／"
                         "打法溯源／自檢單）。**這份不進交付稿**，只給執行 AI 與維護者看。")
    a = ap.parse_args()
    a.top = max(3, min(7, a.top))   # 打法數鎖在 3–7（與 SKILL「3–7 條為宜」一致）

    if not os.path.exists(a.rules):
        print(f"❌ 找不到规则表：{a.rules}")
        sys.exit(1)
    try:
        rules = json.loads(read(a.rules))
    except Exception as e:
        print(f"❌ 规则表不是合法 JSON：{e}")
        sys.exit(1)
    if not isinstance(rules, dict):
        print("❌ 规则表顶层必须是 JSON 对象（{...}）")
        sys.exit(1)
    kmap = json.loads(read(KMAP))
    load_model_names(os.path.join(REF, "03-方法论操作手册.md"))
    load_books(os.path.join(REF, "cases", "49-营销书籍与作者.md"))
    plays = parse_playbook(read(PLAYBOOK))
    if not plays:
        print("❌ 解析 00-打法库 失败（0 条打法）")
        sys.exit(2)

    gate = rules.get("gate") or {}
    if not isinstance(gate, dict) or not gate:
        print(f"{WARN} 規則表缺少 gate（門禁內容）—— 打法匹配將退化成盲選；建議先跑 gate_check.py")
    elif sum(len(str(v)) for v in gate.values()) < 40:
        print(f"{WARN} gate 內容過短（<40 字）—— 匹配會不準，建議把門禁 13 項的客戶狀況補足")

    cardpoints = infer_cardpoints(gate)
    picked = select_plays(plays, rules.get("gate", {}), kmap, a.top, cardpoints)
    md = build_skeleton(rules, picked, kmap, a.tier, cardpoints)
    _dump(a.out, md)
    print(f"✅ 已生成骨架（交付稿用）：{a.out}")

    if a.internal:
        ind = infer_industry(rules.get("gate", {}), kmap)
        _dump(a.internal, build_internal(rules, picked, kmap, ind, a.tier,
                                         datetime.date.today().isoformat()))
        print(f"✅ 已生成内部施工说明（**不进交付稿**）：{a.internal}")
    else:
        print(f"{WARN} 未指定 --internal：施工说明／知识库缺口／自检单**没有落盘**"
              f"（建议补 `--internal <路径>`，执行 AI 才知道要补什么）")

    print(f"   档位：{a.tier} ｜ 识别卡点：{'／'.join(cardpoints)} ｜ 注入打法 {len(picked)} 条")
    for i, p in enumerate(picked):
        print(f"   {i+1}. {_t2s_light(p['name'])}")
    print("   → 下一步：模型只填【填】处；再跑 run_pipeline 出稿。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ composer 执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
