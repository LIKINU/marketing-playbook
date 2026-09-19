#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
composer.py — 方案组装器（marketing-playbook 的「真·skill」引擎）

为什么要有它（用户 2026-09-16 定调）：
    「模型根本做不了强制使用，它只做到读取，相当于 prompt / RAG，不是 skill。」
    → 所以把「知识应用」从『模型自己读、自愿引用』改成『脚本机械组装』：
      输入客户状况 → 从 00-打法库 §0 机械匹配 3–7 条打法 → 自动拉取对应
      03 模型 / 49 学者 / cases 案例 → 输出「知识已注入好」的方案骨架。
      模型只做填空与本地化，**绕不过知识库**。

用法：
    python composer.py --rules rules.json --out skeleton.md
    python composer.py --rules rules.json --out skeleton.md --tier 速览|标准|大赛|B端|G端|投标 --top 5

输入：门禁《任务规则表》JSON（gate_check.py 用的那份）
输出：方案骨架 .md（打法／理论依据／可抄案例已注入；`【填】` 处待模型补）
      输出**天然满足 selfcheck 第【7】【8】关**（打法组合／知识库引用）。

退出码：0 正常；1 输入缺失；2 执行错误
"""

import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paradigm_data as _PD   # noqa: E402  范式库（六档骨架指引，见 build_paradigm.py）
import _common as _C         # noqa: E402  关键口径常量（回本警戒线／LTV 公式的唯一真相）
# 受监管行业的资质与宣称边界（2026-09-19 · C 批「体系6 #2」）——
#   原先「合规角色读到了案例，却没有字段承接」，医美／保健食品／教育客户拿到的骨架
#   与茶饮客户一模一样。这份数据表把「行业 → 资质／禁语／依据」变成可注入的章节。
# ⚠️ 导入失败**不阻断出稿**（数据表缺失时退化为「不注入这一节」，由 selfcheck 兜底报警）。
try:
    import industry_rules as _IND   # noqa: E402
except Exception as _e:             # pragma: no cover
    # 数据表缺失**不阻断出稿**（缺的是「行业专门规定」这一节，不是主线能力），
    # 但**必须说出来** —— 静默降级会让「受监管行业客户没拿到资质章」看起来像正常结果。
    print(f"{WARN} 未能加载 industry_rules（{type(_e).__name__}: {_e}）—— "
          f"受监管行业不会注入 3.5 行业资质与宣称边界", file=sys.stderr)
    _IND = None

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
# 1. 解析 00-打法库：取出所有 §X.Y 打法 + 其「怎么做／怎么验收／案例」等
# ─────────────────────────────────────────────────────────────
def parse_playbook(text):
    plays = []
    lines = text.splitlines()
    cur = None
    for ln in lines:
        m = re.match(r"^###\s+(\d+)\.(\d+)\s+(.+?)\s*$", ln)
        if m:
            major, minor, name = int(m.group(1)), m.group(2), m.group(3).strip()
            if major == 0:          # §0 是总表，不是打法
                cur = None
                continue
            if cur:
                plays.append(cur)
            cur = {
                "id": f"{major}.{minor}", "major": major, "name": name,
                "blk": [], "raw": "",
            }
            continue
        # 遇到更高层标题（章）就结束当前打法
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
        p["situation"] = _cell(blk, "什么情况用")
        p["not_for"] = _cell(blk, "不适用")
        p["budget"] = _cell(blk, "预算量级")
        p["period"] = _cell(blk, "见效周期")
        p["who"] = _cell(blk, "谁来做")
        p["difficulty"] = _cell(blk, "难度")
        p["howto"] = _between(blk, r"\*\*怎么做\*\*", r"\*\*关键技巧\*\*").strip()
        p["verify"] = _after(blk, r"\*\*怎么验收\*\*")
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
# 2. 客户状况 → 卡点类型（A–H）＋ 文本关键词
# ─────────────────────────────────────────────────────────────
CARDPOINT_KW = [
    ("A", ["记不住", "记不住", "不知道", "认知", "认知", "品牌", "没印象", "没印象", "说不清", "说不清"]),
    ("B", ["不买", "不买", "不下单", "不下单", "转化", "转化", "成交", "购买决策", "购买决策", "没人买", "没人买"]),
    ("C", ["铺货", "铺货", "渠道", "卖不到", "卖不到", "触达", "触达", "流量", "曝光", "铺出去", "铺出去"]),
    ("D", ["不敢买", "不敢买", "信任", "担心", "担心", "怕", "怀疑", "怀疑", "不信"]),
    ("E", ["复购", "复购", "回头", "回头", "再买", "再买", "留存", "私域", "沉淀", "沉淀", "复购率"]),
    ("F", ["定价", "定价", "价格", "价格", "太贵", "太贵", "便宜", "毛利", "客单", "客单"]),
    ("G", ["团队", "团队", "执行", "执行", "组织", "组织", "没人做", "没人做", "人手", "人力"]),
    ("H", ["合规", "合规", "违规", "违规", "红线", "红线", "法规", "法规", "处罚", "处罚"]),
]
CARDPOINT_NAME = {"A": "认知", "B": "交易", "C": "渠道", "D": "信任",
                  "E": "复购/私域", "F": "定价", "G": "组织", "H": "合规"}


def infer_cardpoints(gate):
    """卡点类型：以「卡在哪」为主（权重 3），其余字段为辅（权重 1）；取前 2，避免全命中。"""
    primary = str(gate.get("卡在哪", "")) + str(gate.get("卡点", ""))
    rest = " ".join(str(v) for k, v in gate.items() if k not in ("卡在哪", "卡点"))
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
# 3. 选打法：bigram 重叠 + 章节加成 + 预算可行性
# ─────────────────────────────────────────────────────────────
def select_plays(plays, gate, kmap, top, cardpoints):
    """选打法：① SKILL.md §二 路由表机械匹配（主） → ② bigram 补位（辅）。确定性、可调。"""
    client = " ".join(str(v) for v in gate.values())
    cb = bigrams(client)
    name_index = {p["name"]: p for p in plays}

    # §11 特殊场景打法（B端／投标／G端）的名称集合 —— 用它来判断一条路由规则是否「场景专用」
    s11_names = {p["name"] for p in plays if p.get("major") == 11}

    # ① 匹配路由规则 → 方向关键词（round-robin 交错，保证从不同状况各取一条）
    all_rules = kmap.get("路由规则", [])
    hits = {id(r): [k for k in r["kw"] if k in client] for r in all_rules}
    matched = [r for r in all_rules if hits[id(r)]]
    # ①a 场景优先：若客户状况命中了「特殊场景」规则（方向含 §11 打法，如 B端／投标／G端），
    #     就只用这些场景规则的方向，避免被通用规则稀释（否则 B 端客户只拿到 2／4 条 B 端打法）。
    #     ⚠️ 但必须是**强信号**：同一条规则至少命中 2 个关键词才算。
    #        2026-09-17 实测踩到的坑：某 C 端美妆品牌案的客户状况里出现了一个孤立的「B2B」字样，
    #        就让 B 端规则单词命中 → 场景优先生效 → 把「门店／线上／复购／造节」四条正确规则全挤掉，
    #        选出来的 5 条打法有 4 条是 B 端商务条款那类。**单一弱词不得改写整个客户的场景判定。**
    #     → 因此：① 弱命中（<2 词）的 §11 规则**整条丢弃**（不进 buckets）；
    #              ② 有强命中的 §11 规则时，只用这些规则（避免被通用规则稀释）。
    def _is_scene_rule(r):
        return any(d in s11_names for d in r["方向"])

    special = [r for r in matched if _is_scene_rule(r) and len(hits[id(r)]) >= 2]
    matched = [r for r in matched if not _is_scene_rule(r) or r in special]
    if special:
        matched = special
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

    # ② 不足则用 bigram 重叠补位（并含卡点章节加成）
    #     ⚠️ §11 特殊场景打法（B端／投标／G端）**只在上面 explicit 场景路由时才进**，
    #        不得靠 bigram 相似度「顺手捞」进来 —— 否则一个 C 端美妆案会莫名其妙长出
    #        「生意拆解／单位经济模型」这种 B 端章节，客户一看就知道不是给他写的。
    if len(picked) < top:
        boost = [m for c in cardpoints for m in kmap["cardpoint_to_major"].get(c, [])]
        pool = plays if special else [p for p in plays if p.get("major") != 11]
        scored = sorted(
            pool,
            key=lambda p: -(len(bigrams(p["name"] + p["situation"] + p.get("howto", "")) & cb)
                            + (3 if p["major"] in boost else 0)),
        )
        for p in scored:
            if len(picked) >= top:
                break
            _take(p)

    # ③ 多样性：每章最多 2 条（超出往后递补，最后若不足则放宽）
    #     ⚠️ §11 特殊场景打法（major == 11）豁免：场景章节本就要求「这类交付必须全收」，
    #        若按「每章最多 2 条」限制，B 端客户只会拿到 2／4 条打法，场景骨架就不完整了。
    final, per = [], {}
    for p in picked:
        if p["major"] == 11:
            final.append(p)
            continue
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
# 4. 注入「理论依据」：打法 → 03 模型码 / 49 书籍（确定性映射）
# ─────────────────────────────────────────────────────────────
def theory_for(play, kmap):
    """这条打法的「理论依据」＝ **override 优先 ＋ 章内相关度补位**。

    ⚠️ 2026-09-17 改成「可累加」：第一版的 override 是**整组替换** ——
    那表示只要给某条打法加一个新模型，就会把它原本对的模型全挤掉。
    改成累加后，才能安全地把 03 手册里原本挑不到的模型逐条绑进具体打法
    （否则「接进 major_theory」只是让 JSON 好看，`theory_for` 每类只取 3 个，
     多数模型永远浮不上来 —— 实测：接入 33 个后仍只有 14 个能被挑中）。
    """
    # ⚠️ 2026-09-17 修：第一版取「第一个命中的 key」，而字典里有个 2 字符的旧键 `'VI'`
    #    会先把 `'VI 一致性'` 挡掉（短键遮蔽长键）。改成**最长键优先**，
    #    与 `infer_industry()` 的规则一致 —— 越长＝越具体＝越该赢。
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
    # override 是**人手明确指定的**，那就全部给出来（不足 3 个再用章内相关度补位）——
    # 若同样套 [:3]，被 append 到既有清单尾端的模型会永远浮不上来
    # （实测：接入 33 个模型后 I5 就是这样一直挑不到）。
    models = priority + rest[:max(0, 3 - len(priority))]
    books = list(ov["books"]) if ov else list(major.get("books", []))
    if not ov:
        books = books[:2]
    return models, books


def model_label(code):
    """用模型码在 03 手册里找中文名（如 C1 → 超级符号）。找不到就只给码。"""
    m = _M03_RE.get(code)
    return f"{m}（03 §{code}）" if m else f"（03 §{code}）"


_M03_RE = {}
# 知识库里标了「不得引用／待核实」的模型码（由 build 时扫描 03 手册生成）
_M03_BANNED = set()


def _load_m03_banned():
    """扫 03 手册，把标「不得引用／待核实」的模型码收进黑名单。"""
    try:
        t = read(os.path.join(REF, "03-方法论操作手册.md"))
    except Exception:
        return
    for m in re.finditer(r"(?m)^#{2,4}\s*([A-M]\d{1,2})\b[^\n]*\n(?:[^\n]*\n){0,3}?[^\n]*(不得引用|待核实|待核实|⛔)", t):
        _M03_BANNED.add(m.group(1).upper())


_load_m03_banned()

_M03_BRIEF = {}      # code → 「解决什么问题」原文
_M03_STEPS = {}      # code → [「做什么」, …]
_CARDS = {}          # cases 文件名 → [ {brand, one, what, result, points} … ]


def load_model_names(path):
    if not os.path.exists(path):
        return
    t = read(path)
    for mm in re.finditer(r"^###\s*([A-Ma-m]\d{1,2})[｜|·\s]+([^\n（(]+)", t, flags=re.M):
        _M03_RE[mm.group(1).upper()] = mm.group(2).strip()

    # ── 2026-09-17：连「内容」一起读（原本只读到名字，骨架里只剩编号 → 用户投诉：
    #    「单纯写一个文字…根本没有办法让 Agent 理解并完整读取」）。
    #    → 读 ① 解决什么问题（一句）＋ ② 怎么用 表格里的「做什么」栏（前 3 步）。
    blocks = re.split(r"(?m)^###\s*", t)[1:]
    for b in blocks:
        m = re.match(r"([A-Ma-m]\d{1,2})[｜|\s]", b)
        if not m:
            continue
        code = m.group(1).upper()
        mo = re.search(r"\*\*①\s*解决什么问题\*\*\s*\n+(.+?)(?:\n\s*\n|\n\*\*)", b, flags=re.S)
        if mo:
            _M03_BRIEF[code] = re.sub(r"\s+", " ", mo.group(1)).strip()
        mt = re.search(r"\*\*②\s*怎么用.*?\*\*\s*\n(.*?)(?:\n\s*\*\*|\Z)", b, flags=re.S)
        if mt:
            steps = [re.sub(r"\s+", " ", r[1]).strip()
                     for r in re.findall(r"(?m)^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|", mt.group(1))]
            _M03_STEPS[code] = [s for s in steps if s]


def model_brief(code, nsteps=3):
    """把『模型名（03 §C1）』升级成『模型名（03 §C1）—— 解决 X；第 1–3 步：…』"""
    name = _M03_RE.get(code, "")
    head = f"{name}（03 §{code}）" if name else f"（03 §{code}）"
    # ⚠️ 2026-09-17（连锁加盟视角第 7 条，实测）：知识库里有标「⛔待核实 · 不得引用」的模型，
    #   而 card_line_public 对「未核实」有过滤、model_explain **没有** —— 同一条规则两处不一致，
    #   禁用内容会从模型这条路径进交付稿。
    if _M03_BANNED.get(code):
        return ""
    prob = _M03_BRIEF.get(code, "")
    steps = _M03_STEPS.get(code, [])[:nsteps]
    if not prob and not steps:
        return head
    out = head
    if prob:
        out += f" —— 解决「{prob[:80]}」"
    if steps:
        out += "；前几步：" + " → ".join(s[:28] for s in steps)
    return out


# ─────────────────────────────────────────────────────────────
# 案例卡读取（2026-09-17 新增）
#    原本骨架的「可抄案例」只写 `来源 cases/01-xxx.md，请展开…` —— 是**占位符**。
#    这里把案例卡的真实内容抽出来，让骨架本身就带著证据。
#    兼容两种案例清单格式：① 表格（`| # | 案例 | 一句话 | 最硬的一个数字 |`）
#                          ② 条列（`**1｜品牌（年份）· 谁做的：X**` ＋ 做了什么／结果／可抄的点）
# ─────────────────────────────────────────────────────────────
def parse_cards(cases_file):
    """→ [{"brand":…, "one":…, "what":…, "result":…, "points":…}]

    兼容 **三种** 案例清单写法（第一版只认前两种，第三种静默回 0 张卡 ——
    29／32／33／51 因此一直抽不出卡片，kb_audit 的 L2 才把它抓出来）：
      ① 表格：`| # | 案例 | 一句话 | 最硬的一个数字 |`
      ② 条列 A：`**1｜品牌（年份）· 谁做的：X · 深度卡 §3.1**` ＋ `- **做了什么**：…`
      ③ 条列 B：`1. **品牌**｜角度（年份）`
    另外：**机构档（46–51）没有「案例清单」，卡片就是 `### 3.N 标题`** → 直接以标题为卡。
    """
    if cases_file in _CARDS:
        return _CARDS[cases_file]
    p = os.path.join(REF, "cases", os.path.basename(cases_file))
    out = []
    if os.path.exists(p):
        t = read(p)
        m = re.search(r"(?m)^##\s*[一二三四五六七八九十]*、?\s*案例清单\s*$", t)
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
            # ②③ 条列格式（两种写法）
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
                    for key, field in (("做了什么", "what"), ("结果", "result"), ("可抄的点", "points")):
                        mk = re.match(r"^[-*]\s*\*\*" + key + r"\*\*[：:]\s*(.+)$", s)
                        if mk:
                            cur[field] = mk.group(1).strip()
        if not out:
            # 机构档（46–51）：没有案例清单，卡片即 `### 3.N 标题`
            for mm in re.finditer(r"(?m)^###\s+3\.\d+\s+(.+?)\s*$", t):
                out.append({"brand": mm.group(1).strip(), "one": "", "what": "",
                            "result": "", "points": ""})
        else:
            # **2026-09-17 新增：清单 ∪ 深度卡**。
            #    实测 25 个文件里有 **48 张深卡不在自己的案例清单里** ——
            #    只读清单的 Agent 永远看不到它们，composer 也引用不到。
            #    这里把「只在深度拆解」的卡一并收进来（标 deep_only 供溯源）。
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
    """把 `**案例**` 行拆成 **[(文件名, 品牌关键词)]** —— 保留「品牌属哪一档」的对应。

    为什么一定要保留对应（2026-09-17）：第一版只抽出「品牌候选集」，
    再对**每一个被引用的档**都做一次子串匹配 → 同一个品牌会从多文件各中一次
    （实测：淄博烧烤、石头科技、瑞幸 各被抽出两份），引用行与实际取到的卡不一致。
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
    """从打法的 `**案例**` 行抽出**品牌前缀候选**（跨文件合集；仅用于粗筛，正取用 case_pairs）。"""
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
    """挑可抄案例 —— **两段式（2026-09-17 第二版）**，回 `[(file, card, 来源)]`。

    第一段（精准）：打法 `**案例**` 行**指名**的品牌。指不出来就空着，
    **绝不回落成「那个文件的第一张卡」**（旧逻辑实测踩过：§4.1「包裹卡引流」的案例行
    只写「食品品牌的包裹卡引流」，回落成 `cases/02` 第一张卡 = 王老吉，与包裹卡毫无关系）。

    第二段（**行业适配**，2026-09-17 新增）：若还不足 limit，就从**客户所在行业档**
    （`ind`）里挑一张与这条打法语义最接近的卡。为什么必须加这一段：
    没有它，一个银发养老的客户会被配上美妆／茶饮的例子 ——
    **「可抄案例」不可抄，等于没有案例。**
    """
    hint = play.get("cases_raw", "")
    pairs = case_pairs(hint)
    picks, seen = [], set()
    # **配额设计（2026-09-17）**：给了行业档时，答案要「1 张精准对标 ＋ 1 张本行业可抄」。
    #   全给指名卡 → 银发客户拿到美妆例子（不可抄）；全给行业卡 → 失去跨行业标杆。
    #   所以指名段最多占 limit-1，最后一格一定留给客户所在行业。
    named_quota = max(1, limit - 1) if ind else limit
    for cf, kw in pairs:
        for c in parse_cards(cf):
            base = re.split(r"[｜|（(]", c["brand"])[0].strip()
            if base and kw in c["brand"] and base not in seen:
                seen.add(base)                       # ← 以品牌去重，跨文件也不会重复
                picks.append((cf, c, "指名"))
                break                                # 每个（档, 品牌）只取首次出现那张
        if len(picks) >= named_quota:
            break
    if ind and len(picks) < limit:
        for cf, c in best_cards_for_play(ind, play, (limit - len(picks)) + 2):
            base = re.split(r"[｜|（(]", c["brand"])[0].strip()
            if base not in seen:
                seen.add(base)
                picks.append((cf, c, "行业适配"))
                if len(picks) >= limit:
                    break
    return picks[:limit]


def pick_cards(play, ind, limit=2):
    """兼容层：只回 (file, card) 两元组。"""
    return [(cf, c) for cf, c, _ in pick_cards_ex(play, ind, limit)]


def has_named_case(play):
    """这条打法的 `**案例**` 行**指名**了品牌吗（第一段能不能取到东西）。"""
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
    """回传「案例行指不出任何可引用卡片」的打法清单（给骨架列出待补项）。"""
    out = []
    for p in plays:
        if not has_named_case(p):
            why = ("案例行未指名品牌" if p.get("cases") else "无案例行")
            out.append((p, why))
    return out


def card_line(cf, c, maxlen=200):
    """一行卡片摘要（含出处文件名，方便回溯）。"""
    brand = re.split(r"\s*[·・]\s*", c["brand"])[0].strip()      # 去掉「· 谁做的：…」
    body = c.get("what") or c.get("one") or ""
    res = c.get("result") or ""
    txt = f"**{brand}**"
    if body:
        txt += f" —— {body}"
    if res:
        txt += f"　▶ 结果：{res}"
    if len(txt) > maxlen:
        txt = txt[:maxlen].rstrip() + "…"
    return f"{txt}（`{cf}`）"


def _book(b):
    """49 书籍字符串 → 引用格式。容忍没有「｜作者」的字符串，不崩。

    ⚠️ 2026-09-17：这是**内部版**（带 `49` 编号），只进 internal 文件。
       交付稿一律用 `book_explain()` —— 展开成白话，不带编号。
    """
    parts = [x.strip() for x in b.split("｜")]
    name = parts[0]
    author = parts[1] if len(parts) > 1 else ""
    return f"{name}（{author}49）" if author else f"{name}（49）"


# ─────────────────────────────────────────────────────────────
# 4b. 交付稿专用：把「理论／书籍／案例」展开成白话（2026-09-17 新增）
#
#   用户诉求（原话）：「不是只是引用了就行了，不是拿了案例就行了，
#   说有什么理论是没有任何意义也没有任何作用的 —— 而是要根据这些案例、
#   这些理论、这些观点写具体的操作、具体的做法。」
#   「交付出来的东西应该是可以直接看的，而不是有例如像（打法库 §4.1）
#    这样的引用。」
#
#   → 所以：**知识含量只增不减，座标全部剥掉**。
#     §X.X／03 §C1／（作者49）／`cases/xx.md` 这些内部座标对客户毫无意义
#     （他不知道去哪查，也不知道那是什么），全部改写成可读的内容。
# ─────────────────────────────────────────────────────────────
_B49 = {}          # 《书名》 → {"what": 核心主张, "effect": 效果}


def load_books(path):
    """读 49 书籍档，抽出每本书的「③ 做了什么（核心主张）」＋「⑤ 效果」。

    为什么要读内容而不只给书名（与 `load_model_names` 同一个教训）：
    只给一个书名＝「说有什么理论没有任何意义」，执行 AI 据此写不出具体做法。
    """
    if not os.path.exists(path):
        return
    t = read(path)
    for b in re.split(r"(?m)^###\s*", t)[1:]:
        m = re.match(r"[\d.]+\s*(《[^》]+》)", b)
        if not m:
            continue
        d = {"what": "", "effect": ""}
        mw = re.search(r"\*\*③\s*做了什么\*\*[：:]?\s*(.*?)(?=\n\s*[-*]\s*\*\*⑤|\Z)",
                       b, flags=re.S)
        if mw:
            d["what"] = re.sub(r"\s+", " ", mw.group(1).replace("**", "")).strip()
        me = re.search(r"\*\*⑤\s*效果\*\*[：:]?\s*(.*?)(?=\n\s*[-*]\s*\*\*[⑥⑦]|\Z)",
                       b, flags=re.S)
        if me:
            d["effect"] = re.sub(r"\s+", " ", me.group(1).replace("**", "")).strip()
        _B49[m.group(1)] = d


def _load_t2s():
    """加载内置繁→简单字表（`scripts/t2s_data.py`，机械生成）。

    为什么不用 opencc／zhconv：那要多一个依赖，跨平台（没网／没 pip 的环境）就挂。
    这张表覆盖本知识库实际用到的全部繁体字，零依赖、纯 dict 查表。
    加载失败（文件被删）→ 退回不转换，**不抛错** —— 繁体最终由 selfcheck 兜底。
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
    """繁→简（逐字查表）。知识库原文是繁体，交付稿必须简体 —— 在注入时就转掉，
    不要留给模型（模型会漏，selfcheck 就会卡在交付前）。"""
    if not s or not _T2S_MAP:
        return s
    return "".join(_T2S_MAP.get(ch, ch) for ch in s)


def book_explain(b, maxlen=150):
    """书籍 → 「《书名》（作者）：核心主张…」白话，**不带 `49` 编号**。"""
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
    """模型码 → 「模型名：解决什么问题。具体用法：第1步…；第2步…」

    与 `model_brief()` 的差别：**不带（03 §C1）座标**，且步骤给到 4 步（更详尽）。
    座标拿掉、内容加长 —— 对客户来说可读性与可操作性都更高。
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


# 「⚠️ 归因提醒」索引：清单行不带它（它在**深度卡**里），所以先建品牌→提醒的索引。
#  2026-09-17（教材一致性审计第 1 条）：深度卡写了 412 处归因护栏，
#  而 card_line_public 只注入「做法 ▶ 结果」—— 护栏被机械剥掉，下游必然把相关写成因果。
_CAVEAT_CACHE = {}


def _caveat_index():
    if _CAVEAT_CACHE:
        return _CAVEAT_CACHE
    import glob as _glob
    for _f in sorted(_glob.glob(os.path.join(REF, "cases", "*.md"))):
        try:
            _t = read(_f)
        except Exception as _e:
            # 不许静默：读不到就等于**这张卡的归因护栏取不到**，
            # 而调用方看到的是「这条案例没有护栏」—— 与事实不同。
            print(f"  ⚠️ 归因提醒索引跳过（读不了）：{os.path.basename(_f)}（{type(_e).__name__}）")
            continue
        for _blk in re.split(r"(?m)^###\s+", _t)[1:]:
            _head = _blk.split("\n", 1)[0]
            _m = (re.search(r"⚠️?\s*\*{0,2}归因提醒\*{0,2}\s*[：:]\s*(.+)", _blk)
                  or re.search(r"⚠️?\s*\*{0,2}归因提醒\*{0,2}\s*[：:]\s*(.+)", _blk))
            if not _m:
                continue
            # 深度卡标题形如 `### 3.1 珀莱雅｜「早 C 晚 A」大单品战略（2020 起）`
            #   —— 品牌在 `｜` 之前，**没有加粗**（第一版只找 `**品牌**`，索引因此全空）。
            _bm = re.search(r"\*\*([^*]{2,24})\*\*", _head)
            _name = _bm.group(1).strip() if _bm else ""
            if not _name:
                _h2 = re.sub(r"^[\d.\s]+", "", _head)          # 去掉 "3.1 "
                _name = re.split(r"[｜|·・（(]", _h2)[0].strip()
            if _name:
                _CAVEAT_CACHE.setdefault(_name, _m.group(1).strip())
    return _CAVEAT_CACHE


def _caveat_for(brand):
    """按品牌取归因提醒；精确命中优先，否则取「包含关系」最长的一个。"""
    if not brand:
        return ""
    idx = _caveat_index()
    if brand in idx:
        return idx[brand]
    cands = [(k, v) for k, v in idx.items() if k in brand or brand in k]
    if not cands:
        return ""
    cands.sort(key=lambda kv: -len(kv[0]))
    return cands[0][1]


def card_line_public(c, maxlen=260):
    """案例卡 → 交付稿用的一行（**不带 `cases/xx.md` 路径与卡号**）。

    形态（用户 2026-09-17 选定）：`**品牌** —— 他做了什么　▶ 结果：数字`
    保留品牌名作佐证（可信度），不暴露内部文件名。
    """
    brand = re.split(r"\s*[·・]\s*", c["brand"])[0].strip()
    body = c.get("what") or c.get("one") or ""
    res = c.get("result") or ""
    # ⚠️ 2026-09-17（教材一致性审计第 5 条）：README §六 与 01 §二.2 都写
    #   「【未核实】不得进对外交付物」，而装配器**照搬** —— 实测 615 条清单「结果」行里
    #   有 79 条（12.8%）带【未核实】。教材的硬规则在自家工具里失效。
    #   → 宁缺勿错：带标记的结果整句丢弃（保留做法，不保留未核实的数字）。
    if re.search(r"未核实|未核实|待核实|待核实", res):
        res = ""
    txt = f"**{brand}**" if brand else ""
    if body:
        txt += f" —— {body}"
    if res:
        txt += f"　▶ 结果：{res}"
    # ⚠️ 2026-09-17（教材一致性审计第 1 条）：深度卡里写了 412 处「⚠️归因提醒」，
    #   而 card_line_public 只注入「做法 ▶ 结果」—— 护栏被机械剥掉，
    #   下游必然把「相关」写成「因果」。这里把归因提醒一并带出去（截断到 60 字）。
    _caveat = c.get("caveat") or _caveat_for(brand)
    if _caveat:
        # ⚠️ 2026-09-17（投资人视角第 10 条）：原本截 60 字 —— 而卡内真实提醒很长，
        #   「**不要混用或相加**」这句最关键的往往在 60 字之外，**护栏恰好断在最要紧处**。
        #   改成 160 字，并优先保留含口径限定词的那一句。
        _sent = [x for x in re.split(r"[。；;]", _caveat) if x.strip()]
        _key = [x for x in _sent if re.search(r"口径|口径|同比|同店|全渠道|全渠道|不要混用|不能相加|慎引", x)]
        _keep = ("。".join(_key[:2]) if _key else _caveat)[:160]
        txt += f"　（归因提醒：{_keep}）"
    txt = _t2s_light(txt).strip()
    if len(txt) > maxlen:
        txt = txt[:maxlen].rstrip() + "…"
    return txt


# ─────────────────────────────────────────────────────────────
# 5. 产出骨架
# ─────────────────────────────────────────────────────────────
def parse_steps(howto):
    """把打法库的「怎么做」拆成结构化步骤：[(动作, 产出), ...]"""
    steps = []
    for ln in howto.splitlines():
        m = re.match(r"^\s*\d+[.、]\s*(.+)$", ln)
        if not m:
            continue
        body = m.group(1).strip()
        out = ""
        mo = re.search(r"产出[：:]\s*(.+)$", body)
        if mo:
            out = mo.group(1).strip().rstrip("。")
            body = body[:mo.start()].strip().rstrip("。")
        if body:
            steps.append((body, out))
    return steps


def infer_industry(gate, kmap):
    """从『卖什么／品类／卖给谁』推 cases 行业档（确定性关键词匹配）。"""
    txt = " ".join(str(gate.get(k, "")) for k in ("卖什么", "品类", "品类", "卖给谁", "行业", "行业"))
    # 取「最长命中关键词」（最长＝最具体），避免「城市」「区域」这类泛词误命中（2026-09-16）
    best, best_len = "", 0
    for kw, f in kmap.get("industry_to_cases", {}).items():
        if kw in txt and len(kw) > best_len:
            best, best_len = f, len(kw)
    return best


def play_block(i, p, kmap, ind=""):
    """交付稿用的打法段 —— **零内部座标**（2026-09-17 重写）。

    旧版长这样，客户全看不懂：
        **打法 1｜包裹卡引流**（打法库 §4.1）
        - 理论依据：AIDA（03 §C1）＋《影响力》（西奥迪尼49）＋（打法库 §4.1）
        - 可抄案例：xx —— …（`cases/12-xxx.md`）

    新版：座标全剥，知识展开成「别人怎么做的」＋「为什么这么做」。
    """
    models, books = theory_for(p, kmap)
    # 理论：**不带编号**，且比旧版更详尽（模型：解决什么问题 ＋ 前 4 步用法）
    mtxt = "　".join(x for x in (model_explain(c, 4) for c in models) if x)
    btxt = "　".join(book_explain(b) for b in books)
    picks = pick_cards_ex(p, ind)
    if picks:
        # 2026-09-17：这里原本把案例全文印一遍，而 2.0.1 又逐条印一遍 →
        # 同一段文字在交付稿里出现两次（实测 4 处），违反了 SKILL「全文不允许逐字
        # 重复的段落」，却没有任何关卡管。改为**只留一行索引**，正文只在 2.0.1 展开。
        # ⚠️ 索引行只放**品牌名**：归因提醒由 2.0.1 的展开行统一承载，
        #    否则同一条提醒会在两处出现（刚修完的「逐字重复」又回来了）。
        _brands = "、".join((c.get("brand", "").split("·")[0].strip() or "（案例）")
                            for cf, c, src in picks)
        cases = f"\n  - 可抄案例：{_brands}（展开与「我们怎么用」见 **2.0.1**）"
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
        f"{_t2s_light(p['budget']) or FILL}｜{_t2s_light(p['period']) or FILL}"
        # 2026-09-17：`difficulty` 早就从打法库解析进内存了（见 parse_playbook），
        # 却从来没被打印过 —— 方案只回答「花多少」，不回答「做不做得动」。
        f"｜制作难度：{_t2s_light(p.get('difficulty')) or FILL}\n"
        f"- **验收指标**：{_t2s_light(p['verify']) or FILL}\n"
        f"- **不适用情况**（什么时候**不要**用这条）：{_t2s_light(p.get('not_for')) or FILL}\n"
        f"- **可抄案例（别人怎么做的、结果如何）**：{cases}\n"
        f"- **为什么这么做（背后的道理，照这个改就不会跑偏）**：{why}\n"
    )


def build_lite(rules, plays, kmap, cardpoints, today):
    """速览档：给小微企业／个案「快速看懂打法」——1–2 页，只留决策要素。"""
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


def build_skeleton(rules, plays, kmap, tier, cardpoints, scene=""):
    client = rules.get("client", "客户")
    gate = rules.get("gate", {})
    today = datetime.date.today().isoformat()
    cp = "／".join(f"{c}（{CARDPOINT_NAME.get(c, c)}）" for c in cardpoints)
    ind = infer_industry(gate, kmap)      # 同一个行业档在「案例库提示」与「案例注入」共用

    if tier == "速览":
        return build_lite(rules, plays, kmap, cardpoints, today)

    # 2026-09-17：头部施工说明全部移除（「本骨架由 composer.py 机械组装」「打法匹配自
    #   `00-打法库 §0 总表`」「同类行业案例库：references/cases/xx.md」…）。
    #   这些是给执行 AI 的工单，客户看不懂也不需要看 —— 改写进 internal 文件。
    head = (
        f"# {client} · 营销方案\n\n"
        f"> 生成日期：{today}\n\n"
        # 2026-09-19（B 批 · 合规视角第 15 条）：基线第 10 条「交付治理」卡在 4.5/5，
        #   直接原因就是它自己写的判据「5＝机制之外**还有人**把最后一关」——
        #   而封面一直没有「人」这一层：谁编的、谁审的、谁签的、改了哪几版。
        f"> **版本**：v{FILL}　｜　**编制**：{FILL}　｜　**审核／签批**：{FILL}　"
        f"｜　**日期**：{today}\n\n"
        f"## 执行摘要\n- 目标：{FILL}\n- 主线一句话：{FILL}\n"
        f"- 核心打法：{'、'.join(_t2s_light(p['name']) for p in plays)}\n"
        f"- 预期 KPI：{FILL}\n- 盈亏线：{FILL}\n\n"
        # 2026-09-17（评审侧审计第 7 条）：SKILL 承诺「核心结论卡片 —— 一张表讲完关键数字」，
        #   范例稿里也有，而 composer 从不生成 → 决策者只能从数万字里扒重点。
        f"### 核心结论卡片（**决策者只看这一张就够**）\n"
        # 2026-09-17（投资人视角第 8／9 条）：
        #   ① 「预期回报」没口径 —— 同一格可以是营收/毛利/净利，差一个数量级；
        #   ② 只写「最大风险」的定性描述，答不出「输了亏多少」，投资人无法定仓位。
        f"| 目标 | 投入 | **基线（不做也会自然涨多少）** | **净增量（本方案带来；须标口径：营收/毛利/净利）** | 保本点 | "
        f"最大现金亏损（元） | 最大风险 | 谁执行 |\n|---|---|---|---|---|---|---|---|\n"
        f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        # 2026-09-19（B 批 · 战略咨询第 2 条／投资人第 7 条）：
        #   原先只有「预期回报」一个绝对值 → **不可证伪**：客户无法判断哪部分是方案挣的。
        #   把「基数」与「增量」拆开才有对照；配套在 7.2 写增量口径。
        f"> **预期回报必须拆成「基线 ＋ 净增量」两格** —— 不做也会自然涨的那部分不算方案的功劳。\n"
        f"> 净增量 ＝ 动作期总量 − 基线（对照组／去年同期／前后对比，口径写在 7.2）。\n\n"
        f"> 最大现金亏损 = 不可回收支出（物料 + 前置库存 + 最低承诺投放 + 沉没人力）− 残值。\n\n"
    )

    diagnosis = (
        f"## 一 · 现状分析\n> 本章回应：H【填】（证实／证伪）\n\n### 1.1 问题类型与目标\n"
        f"- 问题类型：**{cp}**（八类：认知／交易／渠道／信任／复购／定价／组织／合规）\n"
        f"- 生意目标：{FILL}\n\n### 1.2 真正的卡点\n"
        f"> {FILL}：不是 X —— 是 Y\n\n### 1.3 已排除的假设\n{FILL}\n\n"
        f"### 1.4 竞争与关联品牌扫描\n- 头号对手（按业务环节全链条拆：获客→信任→成交→履约→复购）：{FILL}\n"
        f"- 其他对手逐个：{FILL}\n- 核心差异点一句话：{FILL}\n\n"
        # 2026-09-17：80/20 的反面是「主动放弃」。原先 `paradigm_data` 的 must 里写了
        # 「每条＝约束 ＋ 由此主动放弃的动作」，但**没有任何脚本消费它**，骨架里也没有承载位。
        # 改成固定三行，逼出取舍。
        f"### 1.5 约束与风险底线（**含主动放弃**）\n"
        f"| 硬约束 | 因此主动放弃（动作名） | 若被迫加回则砍哪个 |\n|---|---|---|\n"
        f"| {FILL} | {FILL} | {FILL} |\n"
        f"> 至少要写 **2 条真实放弃** —— 只写约束不写放弃，等于没做取舍。\n\n"
        # 2026-09-19（B 批 · 战略咨询第 4 条／投资人第 3 条）：
        #   全仓没有「市场测算」这一节，两个不同视角独立撞到同一条 → 真缺口。
        #   判据是**双算互校**：只给一个数无法验证量级。
        f"### 1.6 市场盘子（**双算互校，只给一个数无法验证量级**）\n"
        f"| 口径 | 公式 | 数字 | 来源 |\n|---|---|---|---|\n"
        f"| 自上而下 | 品类规模 × 可及比例 | {FILL} | {FILL} |\n"
        f"| 自下而上 | 目标人群数 × 渗透率 × 年均支出 | {FILL} | {FILL} |\n"
        f"- **两数差异**：{FILL}%（**≤30% 或写明差异原因**）；**取哪个数、为什么**：{FILL}\n"
        f"- **渗透率来源**：{FILL}（估算也要写估算依据）\n\n"
        f"> 自上而下答「这个盘子多大」，自下而上答「你够得着多少」；两者差一个数量级，\n"
        f"> 说明其中一个的假设有问题。**只给一个数＝不可验证。**\n\n"
    )

    strategy = "## 二 · 策略\n> 本章回应：H【填】（证实／证伪）\n\n### 2.0 打法组合（核心）\n\n"
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

    # 2026-09-17：原「2.0.2 知识库缺口」整章移出交付稿 —— 那是**我们自己的维护待办**
    #   （哪条打法的案例行没指名品牌、要去补哪个文件），客户既看不懂也无义务替我们补库。
    #   改写进 internal 文件（`--internal`），执行 AI 与维护者看那份即可。
    strategy += (
        # 2026-09-19（B 批 · 战略咨询第 1 条）：全仓 grep「方案一｜选项对比｜取舍矩阵」0 命中
        #   —— 现在是「先收窄、再一条路走到底」，无法证明没选的那条为什么更差。
        f"\n### 2.0.5 战略选项对比（**≥3 条互斥路线，恰好 1 条采纳**）\n"
        f"| 选项 | 核心动作 | 成立前提 | 放弃的代价 | 什么信号出现就改选 | 采纳 |\n"
        f"|---|---|---|---|---|---|\n"
        + "".join(f"| 方案{'一二三'[i]} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
                  for i in range(3)) + "\n"
        f"> **三条路线必须互斥**（不能是「都做，只是顺序不同」）；**恰好一行标「采纳」**。\n"
        f"> 「成立前提」写不出＝这条路线没想清；「什么信号出现就改选」写不出＝没做预案。\n\n"
        f"\n### 2.0.7 概念测试（**问谁／问什么／什么算过**）\n"
        # 2026-09-19（B 批 · 4A 工序第 6 条）：原先只有「共鸣测试：把洞察念给 3 个人，
        #   几人说『啊，我也是』」——**只查字符串在不在**，不查样本量/问法/合格线，
        #   而且测的是**洞察**，不是 Big Idea 或创意概念。给一张真表。
        f"| 测什么 | 测试对象（是谁／多少人） | 展示什么 | 问什么 | **合格线**（含 %） | 实测结果 | 不达标则怎么改 |\n"
        f"|---|---|---|---|---|---|---|\n"
        f"| Big Idea | {FILL} | 一句话（不给背景） | 请原样复述一遍 | 复述正确 ≥60% | {FILL} | {FILL} |\n"
        f"| 概念 A | {FILL} | 样稿 | 二选一：更想买哪个／为什么 | 选 A ≥60% | {FILL} | {FILL} |\n"
        f"| 概念 B | {FILL} | 样稿 | 同上 | 选 B ≥60% | {FILL} | {FILL} |\n"
        f"> 三要素缺一不可：**对象**（是谁、多少人）、**问什么**（原样复述／二选一偏好）、"
        f"**合格线**（含百分比）。\n"
        f"> 无法实测时，写清替代判据（如成对替换词表全过）—— **不许留空**。\n\n"
        f"\n### 2.1 三次收窄（时间／人群／动作）\n{FILL}\n\n"
        f"### 2.2 货盘与机制\n{FILL}\n\n"
        # 2026-09-17（反向榨第 1 条，贝恩 R1 ＋ 运营 R3 **双重印证**）：
        #   SKILL 合约里承诺了「2.3 被低估的资产」「2.4 节奏排期」，composer 一个都不生成，
        #   而 selfcheck 的 SECTIONS 与 paradigm_data 零对账 —— 永远不会有人发现。
        "### 2.3 被低估的资产（**客户手里已经有的、没被用起来的东西**）\n"
        "> 最省钱的增长往往不是「再做一个活动」，而是把已有的资产摆到台前。\n\n"
        "| 资产 | 现在怎么用 | 可以怎么用（本方案怎么用它） | 用它省下什么 |\n|---|---|---|---|\n"
        f"| {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"| {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        "### 2.4 节奏排期（**第几天做什么，哪天是峰值**）\n"
        "| 阶段 | 日期 | 主推动作 | 渠道 | 负责人 | 当日复盘点 |\n|---|---|---|---|---|---|\n"
        f"| 预热 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"| 引爆 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"| 延续 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"| 收尾 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        "> 只写「做什么」不写「第几天做、哪天峰值」，客户上线后没有节奏可跟。\n\n"
        # 2026-09-19（C 批第五批 · 体系5 #12「反向激励检查」）：原来只有正向的
        #   「对执行人的好处」——**没有一个位置写「这个指标会把一线带歪成什么样」**。
        #   真实事故：考核「加微数」→ 一线去街上拦人扫码（全是死粉）；考核「核销单量」→
        #   店员自己下单刷量。**考核什么，就会得到什么的变体。**
        "### 2.5 反向激励检查（**考核什么，就会得到什么的变体**）\n"
        "> 只写正向激励＝只考虑了我们想要什么；这一节写**我们这个打法会被怎么钻空子**。\n\n"
        "| 最容易被做歪的动作 | 指标会诱导出什么错误行为 | 制衡手段（第二指标／抽查／惩罚） |\n"
        "|---|---|---|\n"
        f"| {FILL} | {FILL} | {FILL} |\n"
        f"| {FILL} | {FILL} | {FILL} |\n"
        f"| {FILL} | {FILL} | {FILL} |\n\n"
        "> 至少 3 行。**没有制衡手段的激励＝鼓励造假**：\n"
        "> 例：单看「加微数」→ 拦人扫码拿死粉 → 制衡＝「7 日内有对话的占比 ≥40%」。\n\n"
    )

    # 2026-09-17：学理依据原本硬编码 ['B5','C1'] ＋「major_theory['1'] 第一本书」，
    #   于是**每一个客户都拿到同一段「四种定位法＋超级符号＋《定位》」** ——
    #   正确，但对本客户零信息量（So-What 的教科书式失败）。
    #   改为按本次真正选中的打法反查理论，去重后取前几个。
    _pm, _pb = [], []
    for _p in plays:
        _m, _b = theory_for(_p, kmap)
        _pm += [x for x in _m if x not in _pm]
        _pb += [x for x in _b if x not in _pb]
    _ptxt = "；".join(x for x in (model_explain(c, 3) for c in _pm[:3]) if x)
    _btxt = "；".join(book_explain(b) for b in _pb[:2])
    _pos_theory = ("；".join(x for x in (_ptxt, _btxt) if x)
                   or "（本次打法未匹配到理论，按打法原理直接推导）")
    # 2026-09-17 新增（BCG 视角第 5 条，R1 第 16 条）：**先证明没漏掉一整块，再谈怎么打**。
    #   原骨架是「现状分析 → 策略 → 定位 → 触达 → 预算 → 执行」—— 这是**过程叙事**，
    #   不是 BCG 的「问题树 → 假设 → 只收集能证伪的信息」。不加这一章，无法证明方案没有
    #   漏掉一整块问题。
    zeroth = (
        "## 〇 · 议题树与假设台账（**先证明没漏掉一整块，再谈怎么打**）\n"
        "> 判据：**没有议题树就写正文＝不合格。**\n\n"
        # 2026-09-19（B 批 · 战略咨询第 3 条）：**这张表原先是「营收因子树」而不是问题树** ——
        #   固定四因子「流量／转化率／客单价／复购」**预设了「问题就是营收」**，
        #   于是**无法证明「没漏掉一整块」**（而这正是 BCG 那条判据针对的东西）。
        #   → 改成两层：先做**五分支问题树**（逐支标「是否排除及依据」），
        #     再把营收四因子降为「主攻分支的量化工具」。
        "### 0.1 MECE 分解（**先证明没漏掉一整块，再拆因子**）\n"
        "| 分支 | 该分支下的判断 | 支持证据 | **是否排除／依据** |\n|---|---|---|---|\n"
        f"| 需求端（没人要／要的人变了） | {FILL} | {FILL} | {FILL} |\n"
        f"| 竞争端（被谁抢走了） | {FILL} | {FILL} | {FILL} |\n"
        f"| 自身产品与价格（东西或价不对） | {FILL} | {FILL} | {FILL} |\n"
        f"| 渠道与触达（够不着人） | {FILL} | {FILL} | {FILL} |\n"
        f"| 组织与执行（做不出来／做不到位） | {FILL} | {FILL} | {FILL} |\n"
        f"- **主攻分支**（只剩一支）：{FILL}　｜　**其余四支靠什么排除**：{FILL}\n\n"
        f"> **五支都要填**，且**至少排除 3 支并写明依据** —— 不写排除依据＝这份诊断没做过穷尽。\n"
        f"> 只写「问题就是流量不够」而不排除其他四支，等于跳过了诊断。\n\n"
        f"**主攻分支的量化拆解**（把选定那一支拆到因子）\n"
        # 2026-09-17（R2 数据科学视角第 6 条）：加「数据来源」列 ——
        # 整张诊断表的输入数字原本全是无出处裸数，客户/评审无法追溯。
        "| 因子 | 当前值 | **数据来源（口径／时点）** | 目标值 | 差距 | 主因 |\n"
        "|---|---|---|---|---|---|\n"
        f"| 流量 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"| 转化率 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"| 客单价 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"| 复购次数 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"**最大缺口在【{FILL}】**（只选一层，选差距 × 可达性最高的那层）\n\n"
        "### 0.2 假设台账（每条都可证伪）\n"
        "| H# | 可证伪假设 | 所属分支 | 要什么数据 | 去哪拿 | 证伪则改做 |\n|---|---|---|---|---|---|\n"
        f"| H1 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"| H2 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"| H3 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        "> 假设必须**可证伪**（写得出来「若拿到什么，就说明我错了」）。\n\n"
    )

    # 2026-09-17 新增（4A 视角第 2 条）：交付稿原先从「调研发现」直接跳到「定位语」，
    # 中间「洞察」那一跳没人做 —— 而洞察恰恰是 4A 体系的核心动作。
    insight = (
        "## 二·九 · 洞察萃取（**从数据到定位之间那一跳**）\n"
        "> 洞察 ≠ 数据复述。判据：**用户自己没说出口、但一听就认**的那句话。\n\n"
        f"- **观察**（数据或原话，照抄）：{FILL}\n"
        f"- **【洞察】人心深处**（≤25 字，**主语必须是「人／用户」**）：{FILL}\n"
        # 2026-09-19（C 批 · 4A 工序第 7 条）：原先只有「观察→洞察→连接句」三格，
        #   而**「怎么萃出来的」没有位置** —— 结果就是洞察被写成「观察的形容词版」。
        #   4A 的判据是「必须能说出用了哪一招」，三招是可教、可复现、可反驳的。
        f"- **用的是哪一招**（找矛盾／文化张力／品类惯例反面，**三选一，并写清怎么套上来的**）：{FILL}\n"
        f"- **连接句**（这条洞察如何推出下面的定位语）：{FILL}\n"
        f"- **共鸣测试**：把洞察念给 3 个人，几人说「啊，我也是」：{FILL}\n"
        f"- **不合格版**（自检用，照抄一行反例再改写）：{FILL}\n\n"
    )

    # 2026-09-19（C 批 · 体系2 #3「一页 creative brief」）：骨架原先从「洞察」直接跳到「定位」——
    #   中间缺一张**一页的创作指令**。4A 的判据是六字段：SMP／target／barrier／RTB／mandatories／success，
    #   而 SMP **只能一条**（同时给两条＝没有主张）。
    brief = (
        # ⚠️ 2026-09-19 踩坑：标题原来写成 `二·十 · 创意简报（一页 · **写创意的人只准看这一页**）`
        #   —— 而 `selfcheck` 的骨架对账用的是**字面子串**比对（声明名去空白后必须在正文里出现），
        #   声明名是 `二·十 · 创意简报（一页）`：多了括号内文字 → **判成「缺这一节」的假报警**。
        #   → **规则：标题在第一个右括号之前必须与 paradigm_data 的声明名逐字一致**；
        #     要加强调，写在右括号之后（这里改放到下面的引用行里）。
        "## 二·十 · 创意简报（一页）\n"
        "> 六字段缺一不可，**写创意的人只准看这一页**（看多了会自己发挥）。\n"
        "> **SMP 只能写一条** —— 写两条等于没有主张。\n\n"
        f"- **SMP（单一营销命题，一句话，只能一条）**：{FILL}\n"
        f"- **target（对谁说：不是人群画像，是「此刻的他」）**：{FILL}\n"
        f"- **barrier（他不买的真实理由）**：{FILL}\n"
        f"- **RTB（凭什么信我们做得到）**：{FILL}\n"
        f"- **mandatories（必须遵守：口径／禁用词／必带元素／时长）**：{FILL}\n"
        f"- **success（成功长什么样，含数字）**：{FILL}\n\n"
    )

    positioning = (
        "## 三 · 定位与口径\n> 本章回应：H【填】（证实／证伪）\n\n### 3.1 定位与差异化支点\n"
        f"- 定位语（一句话）：{FILL}\n"
        f"- 学理依据（**按本次选中的打法反查**，不是通用套话）：{_pos_theory}\n"
        f"- 三个支点（各跟一个可查证事实）：{FILL}\n\n"
        # 2026-09-17（平台算法视角第 6 条）：GUIDE 要求本节是「5–12 行的表」，
        #   而 composer 给的是裸 `{FILL}` —— 骨架与指引漂移，检查必然落空。
        f"### 3.2 禁用词与红线（什么话绝不能说）\n"
        f"| 禁用词 | 替换说法 | 依据 | 适用平台 | 违规后果（限流／拒审／判罚） |\n"
        f"|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n" for _ in range(6))
        + f"\n> 平台侧雷区与广告法不同：小红书禁导流微信、抖音会拒审素材、微信禁诱导分享 —— "
          f"**分平台列，不要合成一句「注意合规」**。\n\n"
        f"### 3.3 对不同人说什么\n{FILL}\n\n"
        # 2026-09-19（C 批 · 4A 工序第 10 条）：3.2 只说「什么话不能说」，**没写「发布前谁审、提前几天送」**。
        #   物料是当天做当天发的，法务没时间看；平台侧（医疗／食品／金融／教育）还要资质备案。
        #   「谁审」写成「团队／大家一起」＝没有人负责，所以判据里明令写**岗位**。
        f"### 3.4 发布前合规送审（**物料是当天做当天发的 —— 所以送审要提前，不能当天**）\n"
        f"| 送审对象（哪类物料） | 审什么（广告法／平台规则／行业资质） | **谁审（写岗位，不写「团队」）** | "
        f"**提前几天送** | 送审要交什么材料 | 不过则怎么办（降级模板／延期／撤） |\n"
        f"|---|---|---|---|---|---|\n"
        f"| 全部对外文案 | 广告法绝对化用语、功效宣称 | {FILL} | {FILL} | 定稿文案＋依据出处 | {FILL} |\n"
        f"| {FILL} | 平台侧规则（行业资质／备案号） | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        f"> 「谁审」必须写**岗位**（法务岗／平台运营岗／外部律所）—— 写「团队」「大家一起」＝**没有人负责**。\n"
        f"> 「提前几天」必须写**数字**：法务要时间、平台审核要时间、资质备案更慢；\n"
        f"> 写「发布前送审」而不写天数，等于给自己的排期埋一颗雷。\n\n"
        # ── 2026-09-19（C 批第五批）：三条「一字都没落过」的合规边界（六体系核对 · 体系6 挖出）──
        #   3.5 是**按行业**动态注入的（受监管行业才有）；下面三条是**通用**的，所以编号 3.6–3.8
        #   （跳过 3.5 是刻意的：它只在受监管行业出现）。
        f"### 3.6 未成年人·母婴保护（**涉及校园／儿童／母婴，这一节不能空**）\n"
        f"> 触发条件：客群里含未成年人，或品类是母婴／儿童用品／儿童食品。\n\n"
        f"| 项 | 要求（**含禁语与替换说法**） |\n|---|---|\n"
        f"| **监护人书面同意**（采集未成年人信息／使用其形象时） | {FILL} |\n"
        f"| 未成年人形象使用边界（能否出镜、能否作证明） | {FILL} |\n"
        f"| **母婴食品禁语**（替代母乳／促进长高／变聪明／益智等，逐条替换说法） | {FILL} |\n"
        f"| 校园渠道的红线（不得进校／不得以校方名义／不得面向儿童直接促销） | {FILL} |\n\n"
        f"> **本表是禁语清单**（照原样列出，供一线对照）：母婴与儿童食品的「促进长高／变聪明」\n"
        f"> 属于**虚假宣传高发区**（罚款级）；\n"
        f"> 未成年人信息采集须**监护人单独同意**（《个人信息保护法》第 31 条），不是默认同意。\n\n"
        f"### 3.7 抽奖与导流合规（**规则要写死，导流要分平台**）\n"
        f"| 项 | 内容 |\n|---|---|\n"
        f"| 抽奖规则（参与条件／开奖时间／开奖方式／公示在哪） | {FILL} |\n"
        f"| **奖项设置与价值上限**（现金类不超过 5 万元需公证等） | {FILL} |\n"
        f"| 中奖名单与兑奖凭证的留存 | {FILL} |\n"
        f"| **导流是否可行 · 分平台写**（微信／小红书／抖音／线下各一行） | {FILL} |\n\n"
        f"> ⛔ **不要写一句「全平台同步导流」** —— 小红书禁站外导流、抖音对「引导私域」有明确处罚口径、\n"
        f"> 微信禁诱导分享。**导流方式必须按平台分别写可与不可**；抽奖不公示规则与开奖＝纠纷高发点。\n\n"
        f"### 3.8 竞品比较合规边界（**比较可以，贬低不行**）\n"
        f"| 项 | 内容 |\n|---|---|\n"
        f"| 可以比较什么（参数／价格／规格，且**须附可查来源**） | {FILL} |\n"
        f"| **禁用的贬低词**（碾压／吊打／秒杀／完爆等，逐条改中性表述） | {FILL} |\n"
        f"| 比不过的地方怎么处理（不写／改讲场景） | {FILL} |\n"
        f"| 由谁复核比较内容的依据 | {FILL} |\n\n"
        f"> 《广告法》第 13 条禁止贬低同行；比较广告**必须能出示依据** ——\n"
        f"> 拿不出数据来源的对比，投诉到市场监管就是「不正当竞争」。\n\n"
    )

    # 2026-09-17（私域视角第 4 条）：原先路径只有一句 `{FILL}` ——
    #   短视频/小红书引来的流量落到哪、谁接、漏在哪，全部无法验收。
    reach = (
        f"## 四 · 触达与渠道\n"
        f"- 渠道选择（为什么用/不用）：{FILL}\n"
        f"- 用户路径一句话：{FILL}\n"
        f"- 硬风险：{FILL}\n\n"
        f"| 渠道 | 钩子 | 落点（企微／群／小程序／门店） | 承接人 | 流失率预估 |\n"
        f"|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n" for _ in range(3)) + "\n"
        f"> **每一行都必须有非空的「落点」** —— 写「引流到私域」不算落点。\n\n"
        # 2026-09-19（B 批 · 4A 工序第 8 条）：渠道表原本**无预算、无触达、无频次**，
        #   而 `SKILL.md:339` 却承诺「触达 Agent：渠道 ≥4 各含 理由／预算／预期／执行人」
        #   —— **承诺与骨架不一致**。这里补一节真正的媒介计划。
        f"### 4.1 媒介组合与预算分配（**占比行加总须 = 100%**）\n"
        f"| 渠道 | 角色 | 预算占比 | 预期触达（人数） | 频次 | 去重口径 | 加投／维持／停 |\n"
        f"|---|---|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL}% | {FILL} | {FILL} | {FILL} | {FILL} |\n"
                  for _ in range(4)) + "\n"
        f"- **预算占比合计**：{FILL}%（**须 = 100%**）\n"
        f"- **跨渠道触达不能简单相加**（去重口径写上面那一列；重复人群比例：{FILL}%）\n\n"
        f"**三段排期**（预热／引爆／承接）：\n"
        f"| 阶段 | 起止 | 主推渠道 | 该段预算 | 该段唯一要拿到的结果 |\n|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n" for _ in range(3)) + "\n"
        f"> 分配依据是**影响力**而不是**曝光量** —— 同样 100 万次曝光，媒体通稿与社区口碑对"
        f"「下次还买不买」的作用差一个量级；**没有预算占比的渠道计划，等于没有媒介计划**。\n\n"
    )
    # 2026-09-17 新增（4A 视角第 8 条）：渠道原生。原先只有「渠道｜内容」两列，
    # 内容栏自由文本 → 结果就是「同一段内容换个渠道名」。这里强制每个渠道至少
    # 一个**不可移植元素**（放到别的渠道就失效的东西）。
    # ── 创意主张（Big Idea）：2026-09-19（根因 3 剩余 · agency-4a 第 1/4/5 条）──
    # ⚠️ 原先**创意链只挂大赛档** —— 最常交付的标准档（C 端品牌，68 节）里
    #    **没有任何 Big Idea／创意章**，从「三 · 定位」直接跳到「五 · 物料表」。
    #    而 4A 的判据是「**创意必须能做成样稿**；只有概念没有样稿＝没做完」。
    #    → 补成**所有非速览档都有**的创意决策层（五·〇 主张 → 5.2 样稿）。
    #    两个可判定测试是这条的关键：**复述测试**证明它记得住，
    #    **换名测试**证明它是这家的（换掉品牌名就失效）—— 否则只是一句行业通用口号。
    creative = (
        f"## 五·〇 · 创意主张（Big Idea）\n"
        f"- **Big Idea**（一句话，要能被别人复述）：{FILL}\n"
        f"- **它绑定了哪个定位支点**：{FILL}（回指「三 · 定位与口径」里的第几条）\n"
        f"- **复述测试**：念给 3 个没看过方案的人，**{FILL} 人能原样复述**（<2 人＝重写）\n"
        f"- **换名测试**：把品牌名换成「X」后，本句**{FILL}**（应写「不成立」）\n"
        f"- **它为什么不是品类通用口号**：{FILL}\n\n"
        f"> 三道测试缺一不可。**换名测试还成立＝这只是一句谁都能用的话**；\n"
        f"> **没有样稿＝这个概念没做完**（样稿见 5.2）。\n\n"
    )
    copy_ = (
        f"## 五 · 落地文案与物料\n"
        f"- 物料清单（放在哪／写什么／多少钱）：{FILL}\n"
        f"- 一线话术：{FILL}\n\n"
        f"### 5.1 同一母题 · 各渠道的**不同形态**（不是同一段内容换个渠道名）\n"
        f"| 母题 | 渠道 | 形态（长度／交互／载体） | **时长（秒）** | 开头 3 秒或首屏 | "
        f"**钩子类型（结果前置／冲突提问／反常识／利益直给／身份喊话，五选一）** | "
        f"**目标完播／互动值** | 结尾引导口令 | 用户可做的动作 | **不可移植元素** |\n"
        f"|---|---|---|---|---|---|---|---|---|---|\n"
        f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        # 2026-09-19（A 批 · 平台视角第 1 条）：五种钩子与禁区**知识库里有**
        #   （`00-打法库.md:547/553`），骨架却只有一个空格。
        f"> **前 3 秒禁止出现 logo 与「大家好，今天讲…」** —— 字幕前 6 个字就是第二钩子。\n"
        f"> 钩子必须从五类里选一类来写；写「突出产品卖点」这种＝没选。\n"
        f"> **必须覆盖抖音／小红书／视频号三行** —— 视频号走社交转发，结构不同于抖音的完播逻辑。\n"
        f"> **每个渠道至少 1 个「不可移植元素」** —— 把它放到别的渠道就失效的那种东西。"
        f"（例：抖音是评论区扣字、小红书是收藏清单体、详情页是第七屏风险逆转、"
        f"线下是「走 5 分钟到店」。）两个渠道的「形态＋开头」雷同＝没做渠道原生。\n\n"
        # ── 核心概念样稿：2026-09-19（agency-4a 第 5 条）──
        # ⚠️ 原先**样稿也只在 大赛档／提案档**要求。标准档的文案篇止于「物料清单：{填}」——
        #    于是交付物里只有概念描述，没有一句能通读的原文。
        #    判据：**真样稿＝能通读的文案全文**（≥30 实字），
        #    不以「视觉／风格／调性／氛围」开头 —— 那是描述，不是样稿。
        f"### 5.2 核心概念样稿（**每个概念 ≥1 张真样稿**）\n"
        f"> **真样稿 ＝ 能通读的文案全文**，不是「视觉风格：年轻有活力」这类描述。\n"
        f"> 下面四类**各挑最相关的一类**写成原文（每张 ≥30 实字）；写不出原文，\n"
        f"> 说明这个概念还没想清楚 —— 不要用「待定」「见图」占位。\n\n"
        f"- **海报**（主文案／副文案／落款）：{FILL}\n"
        f"- **短视频前 15 秒口播逐句**：{FILL}\n"
        f"- **详情页第七屏（风险逆转）原文**：{FILL}\n"
        f"- **私域首触话术**（加微后第一条）：{FILL}\n\n"
        # ── 2026-09-19（C 批第五批 · 体系4 #8／#11）：知识库对小红书有**全套**（四类笔记＋标题
        #   公式＋封面＋正文模板），对视频号只有两句；而骨架只给「小红书：收藏清单体」6 个字。
        #   5.1 已经强制覆盖抖音／小红书／视频号三行，但**「覆盖一行」≠「写出这家的原生形态」**。
        #   这两节把两家的原生差异落成字段（判据查「有没有写」，不查「写得好不好」）。
        f"### 5.3 小红书笔记形态（**四类笔记选一，标签 ≥5**）\n"
        f"| 项 | 内容 |\n|---|---|\n"
        f"| **正文结构（四选一）**：痛点型／攻略型／开箱型／对比型 | {FILL} |\n"
        f"| **封面主标**（大字，≤12 字，一眼看懂给谁看） | {FILL} |\n"
        f"| **标题公式**（数字＋人群＋结果／反差＋悬念，写出成品标题） | {FILL} |\n"
        f"| 正文首句（前两行决定点不点「展开」） | {FILL} |\n"
        f"| **标签 ≥5 个**（品类词＋场景词＋人群词各 1–2） | {FILL} |\n"
        f"| **三档配比**（干货 : 种草 : 转化 ＝ ？） | {FILL} |\n\n"
        f"> 小红书是**搜索型**社区（不是推荐流逻辑）：标题与标签要按「用户会搜什么词」写，\n"
        f"> 而不是按「我想说什么」写。⛔ 站外导流在站内是处罚项 —— 导流手法见 3.7。\n\n"
        f"### 5.4 视频号原生形态（**转发靠理由，不靠算法**）\n"
        f"| 项 | 内容 |\n|---|---|\n"
        f"| **一句话转发理由**（转发者凭什么转给自己的朋友看） | {FILL} |\n"
        f"| **公众号／企微承接**（看完往哪儿去，一步可达） | {FILL} |\n"
        f"| **朋友圈分发路径**（谁在什么时候转、配什么话术） | {FILL} |\n"
        f"| 与抖音的同一条内容**差在哪**（时长／字幕／结尾引导） | {FILL} |\n\n"
        f"> 视频号是**社交推荐**：完播率不是第一位，「值得被熟人看到」才是。\n"
        f"> ⛔ **直接把抖音那条搬过来＝没有视频号**：抖音结尾引导「点下方链接」，\n"
        f"> 视频号要引导的是「转给可能需要的朋友」。\n\n"
    )
    # ⚠️ 2026-09-19（A 批 · 执行视角第 1 条 ＋ 平台视角第 2 条）：
    #   原先这一节是**三条项目符号、根本没有表** —— 于是 selfcheck 的 16g
    #   （查 KPI 表头有没有「频率／责任人」两列）**永远找不到表头、静默失效**；
    #   知识库里的平台经验阈值（3 秒完播 >35%、团购核销率 5–20%）也没有落点。
    kpi = (
        f"## 六 · KPI 与追踪机制\n"
        f"- 追踪工具（土办法＋成本）：{FILL}\n\n"
        f"### 6.1 KPI 表（**没有频率与责任人的指标没人会去看**）\n"
        # 2026-09-19（C 批 · 4A 工序第 12 条）：原表有「观测频率／观测人」，那是**观测方式**；
        #   缺的是**归因方式** —— 「这个数涨了，凭什么说是这次投放带来的？」
        #   没有专属码／分渠道／对照组／前后对照，活动期自然增长会被算成方案的功劳。
        f"| KPI | 基准值 → 目标值 | 预警线 → 立刻做什么 | **归因方式（专属码·分渠道·对照组·前后对照，四选一）** | "
        f"观测频率 | 观测人（岗位） | 权重（合计 100%） | 达标奖／不达标罚 |\n"
        f"|---|---|---|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
                  for _ in range(3)) + "\n"
        f"> 「归因方式」**四选一**：专属码／专属链接（线上线下分流）、分渠道埋点、对照组（不投放区域或人群）、"
        f"前后对照＋基线扣除。\n"
        f"> ⚠️ 只写「观测方式」（看哪些数、多久看一次）**不等于归因** —— 没有归因列，"
        f"活动期自然增长会被算成这次投放的功劳。\n"
        f"> 「权重」合计须 = 100%；「达标奖／不达标罚」要**挂到钱上**（奖金系数或保证金），\n"
        f"> 只写「加强跟进」＝这个指标没人管。\n\n"
        f"### 6.2 平台健康阈值参考（**经验值，不是承诺**）\n"
        f"| 平台 | 看哪个指标 | 经验参考值 | 低于此线就停／改什么 |\n"
        f"|---|---|---|---|\n"
        f"| 抖音 | 3 秒完播率 | 经验值 >35% | {FILL} |\n"
        f"| 小红书 | 赞藏比／搜索排名 | {FILL} | {FILL} |\n"
        f"| 视频号 | 社交转发率 | {FILL} | {FILL} |\n"
        f"| 美团／点评 | 团购核销率 | 经验值 5–20% | {FILL} |\n\n"
        f"- 决策节奏：{FILL}\n\n"
    )
    # 2026-09-17（R2 数据科学视角第 3 条）：盈亏线原本只给单点 —— **单点=假精确**。
    # 标准档以前完全没有敏感性分析（只有 B 端有）。这里统一加三档，并把来源列补上。
    budget = (
        f"## 七 · 预算明细\n"
        # 2026-09-17（连锁加盟视角第 3 条）：要门店出钱出力却无分摊、核销与罚则 ——
        #   门店对掏钱的活动必然软抵抗。
        f"| # | 分项 | 金额（元） | 数量 | 单价 | 来源／口径 | **承担方（总部／门店／比例）** | 核销凭证与时限 | 不执行的处理 |\n"
        f"|---|---|---|---|---|---|---|---|---|\n"
        f"| 1 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"| — | **合计** | **{FILL}** | — | — | — | — | — | — |\n\n"
        # 2026-09-17（投资人视角第 6 条）：原为自由文本 `{FILL}`，**连公式都没有**；
        #   而 budget_check 那边的保本量公式分子只有固定成本 —— 漏了投放费与获客成本，
        #   保本量必然偏低，投资人重算一遍保本点就上移。
        f"### 7.2 盈亏线测算\n"
        f"保本量 =（固定成本 + 投放费 + 专项人力）÷（客单价 − 变动成本 − 单笔履约/佣金/退货损耗）\n"
        f"| 分子项 | 值 | 分母项 | 值 |\n|---|---|---|---|\n"
        f"| 固定成本 | {FILL} | 客单价 | {FILL} |\n"
        f"| 投放费 | {FILL} | 变动成本 | {FILL} |\n"
        f"| 专项人力 | {FILL} | 单笔履约/佣金/退货损耗 | {FILL} |\n"
        f"| **合计** | **{FILL}** | **单位毛利** | **{FILL}** |\n\n"
        f"**保本量 = {FILL} 单**\n\n"
        # 2026-09-19（B 批 · 增量归因）：券／补贴类动作最容易把「存量搬家」当成新增。
        f"**增量口径**（券／折扣／补贴类动作必填；其余填「不适用」）：\n"
        f"| 动作期总量 | 基线（对照组／去年同期／前后对比） | **净增量** | 基线怎么来的 |\n"
        f"|---|---|---|---|\n"
        f"| {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"> 不设基线的活动**无法判断增量** —— 把总销量当增量，是最常见的自欺。\n\n"
        f"### 7.3 敏感性分析（**关键结论不给区间＝假精确**）\n"
        # 2026-09-19（A 批 · 投资人视角第 11 条）：原先只动客单/转化/投放，
        #   而**留存与复购是最脆的** —— 悲观档不压它，等于没做压力测试。
        f"| 情景 | 关键假设（客单价／转化率／投放成本／**年复购次数或留存年限**） | 营收 | 成本 | 结论 |\n"
        f"|---|---|---|---|---|\n"
        f"| 乐观 | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"| 基准 | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"| 悲观 | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        # 2026-09-17（运营 R3 第 3 条）：SKILL 承诺「7.3 追投与止损规则」，但 7.3 被敏感性占用了，
        #   于是「第 3 天数据不达标时调什么、谁拍板」这条**根本没落地**。补成 7.4。
        # 2026-09-17（平台算法视角第 3 条）：投流在整条流水线里没有落点 ——
        #   路由表把「投流亏钱」导向诊断章，客户拿不到止损动作。
        f"### 7.4 投流计划（千川／聚光／京准通：**出价＋素材迭代＋止损**闭环）\n"
        # 2026-09-19（C 批第五批 · 体系4 #4「投放账户结构与冷启动判定」）：
        #   原七列**没有账户结构、没有冷启动判定** —— 而这两件事决定投手第一天怎么开局：
        #   几个账户、计划怎么命名分层、学习期几天不调价、花多少还没转化就必须关掉。
        #   投手的行话是「一计划一素材一落地页」，缺了这三列，方案交到手里没法执行。
        f"| 平台 | 账户结构（几个账户／计划怎么分层命名） | 目标 | 出价方式 | 日预算 | 素材迭代节奏 | "
        f"**学习期规则（前 N 次转化不调价）** | **冷启动关停线（花 X 元无转化即关）** | **CAC 上限** | **止损条件** |\n"
        f"|---|---|---|---|---|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL}（例：3 账户×「日期_素材类型_定向」） | {FILL} | {FILL} | {FILL} | "
                  f"{FILL} | {FILL}（例：前 20 次转化不调价） | {FILL}（例：单计划花 300 元无转化即关） | "
                  f"{FILL} | {FILL} |\n"
                  for _ in range(2)) + "\n"
        f"> 「学习期规则」与「冷启动关停线」**两列必须带数字** —— 它们是投手的开局纪律：\n"
        f"> 不写，投手就会在学习期里反复调价（越调越学不出来），或者让一个跑不动的计划白烧一天。\n\n"
        f"### 7.5 追投与止损规则（**第 3 天不达标，谁在第几天前决定什么**）\n"
        f"| 触发数字（什么情况下） | 第几天前决定 | 调什么 | 谁拍板 | 不达标则停哪个动作 |\n"
        f"|---|---|---|---|---|\n"
        f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        f"> 敏感性分析是**静态**三档；这一节是**动态**止损 —— 没有它，客户只能凭感觉加码或收手。\n\n"
        # 2026-09-19（B 批 · 投资人视角第 6 条）：原先只有「最大现金亏损」**总量、没有时序** ——
        #   而投资人看的第一问是「钱什么时候出去、什么时候回来、最深要垫多少、垫多久」。
        f"### 7.6 现金流与垫资（**总量之外，还要看时序**）\n"
        f"| 周／月 | 支出（出账） | 回款（进账） | **净流** | **累计净流** |\n|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n" for _ in range(4)) + "\n"
        f"- **最大资金缺口**＝min（累计净流）＝{FILL} 元　｜　**缺口持续**：{FILL} 周\n"
        f"- **客户可动用现金 / 账期天数**：{FILL}　→　**结论**：{FILL}（垫得起 / 需要分批 / 需要外部资金）\n\n"
        f"> 只写「最大现金亏损」不够：**同样亏 20 万，「前两周垫」与「第三个月才垫」是两门生意。**\n"
        f"> 回款账期要从客户实际结算口径来（平台账期／经销商账期／直客现结），不能拍一个数。\n\n"
    )
    exec_ = (
        # 2026-09-17（反向榨，HR R3 第 1／3／4／9 条 ＋ 供应链 R3 第 2 条，四方共识）：
        #   原骨架只给裸占位符 `{FILL}`，而 depth_check 却硬性要求「行动清单是表、每行有负责方＋时间」
        #   —— 骨架不给表，检查必然落空。而且原五要素**缺「决策权限／对执行人的好处／替补人」**。
        f"## 八 · 执行与风控\n"
        f"### 8.1 行动清单\n"
        f"| 行动 | **执行主体（总部／区域／门店／加盟商）** | 负责方（岗位到人） | 替补人 | 截止 | 预算 | 验收标准 | 验收人 | 决策权限（谁能批／超出找谁） | **依赖方＋接口人＋交期** | 对执行人的好处 |\n"
        f"|---|---|---|---|---|---|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
                  for _ in range(10)) + "\n"
        # 2026-09-19（A 批 · 执行视角第 7 条）：全仓「跨部门」只命中**生成流程**的内部分工，
        #   没有客户侧接口 —— 每个要别人配合的动作，都该写清「从谁那里拿什么、几号给我、
        #   他不给我找谁拍板」。
        f"- **跨部门冲突升级路径**（一线卡住了怎么办）：\n"
        f"| 情形 | 一线先找谁 | 几小时未决升级到谁 | 最终拍板人 |\n"
        f"|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} |\n" for _ in range(3)) + "\n"
        f"> **负责方必须是岗位名**（店长／导购／区域经理…），写「团队」「相关同事」不算 —— 没有人真的负责。\n"
        f"> **对执行人的好处**一栏不能空：没有激励的动作在门店端必然走样。\n\n"
        # ⚠️ 2026-09-19（A 批 · 执行视角第 6 条 ＋ 投资人视角第 12 条）：
        #   原先只有一行 {FILL} —— 只会「砍活」，不会「加人／外包／上工具」，
        #   也没有「预算砍半／加倍怎么办」。两件事都是决策者必问的。
        f"### 8.2 执行人力与资源伸缩\n"
        f"| 岗位 | 现有人数 | 现有负荷（天／月） | 本方案新增负荷 | 是否超载 | 补法（加人／外包／上工具） | 月成本 | 到位周期 |\n"
        f"|---|---|---|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
                  for _ in range(2)) + "\n"
        f"- **删减顺序**（真做不完时先砍哪个）：{FILL}\n"
        f"- **绝对不砍的三项**：{FILL}\n"
        f"- **预算 −50% 先砍哪条**：{FILL}\n"
        f"- **预算 +100% 先加哪条**：{FILL}\n\n"
        # 2026-09-17（客服舆情视角第 4 条）：四件套只回答「怎么写」，没回答
        #   「**谁在几小时内拍板**」—— 预警信号触发了，兜底预案会卡在等老板回复上。
        #   升级为六件套：+ 决策人＋决策时限、+ 对外口径。
        f"### 8.2.5 备货与库存（**卖得掉才算数**）\n"
        # 2026-09-19（B 批 · 执行视角第 5 条）：8.3.1 只有「超卖与履约兜底」＝**事后赔付**；
        #   没有「备货够不够、补货要几天、卖不掉／临期怎么处理」。
        f"| SKU | 活动承诺量 | 现有库存 | 生产或补货前置期 | **安全库存线** | 临期／尾货处理 |\n"
        f"|---|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n" for _ in range(2)) + "\n"
        f"> **先算能卖多少，再承诺卖多少。** 承诺量 > 现有库存 + 前置期内可补量 ＝ 注定超卖：\n"
        f"> 那时再写「补偿方案」是被动补救，客户已经失信一次。\n"
        f"> 临期／尾货必须在方案里给出路（搭赠／转私域／折价清仓），否则毛利会被尾货吃掉。\n\n"
        f"### 8.3 风险清单（每条写清**六件套**）\n"
        f"| 风险 | 为什么会发生 | 预警信号（具体数字＋检查时点） | 兜底预案 | "
        f"**决策人＋决策时限** | **对外口径** | 预防动作 |\n|---|---|---|---|---|---|---|\n"
        f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL}（例：区域经理，24 小时内） | {FILL} | {FILL} |\n"
        f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        f"### 8.3.1 超卖与履约兜底（**承诺了优惠却发不出货，是最典型的信任崩塌点**）\n"
        f"| 承诺量 | 实际库存 | 超卖触发线 | 补偿方案 | 谁批 |\n|---|---|---|---|---|\n"
        f"| {FILL} | {FILL} | {FILL} | 「已付款订单全部履约，超时补 20 元无门槛券，**不取消订单**」 | {FILL} |\n\n"
        f"### 8.3.2 退款与纠纷升级路径\n"
        f"| 级别 | 适用情形 | 谁处理 | 时限 | 谁有权免单 |\n|---|---|---|---|---|\n"
        f"| 一级 客服 | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"| 二级 店长／主管 | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"| 三级 平台介入 | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        f"### 8.3.3 差评与口碑预案（**投放必然带差评；没有规矩，一线会自己乱来**）\n"
        f"| 差评类型 | 首响时限 | 处理动作 | **禁用动作** |\n|---|---|---|---|\n"
        f"| 功效类 | 2 小时内私信 | 只讲退换、不讲原理 | 禁止承诺「删评返现」 |\n"
        f"| {FILL} | {FILL} | {FILL} | 禁止私了删评、禁止与用户争吵 |\n\n"
        f"### 8.3.4 资产与账号风险（私域案的头号事故）\n"
        f"- 名单归属条款＋员工签署：{FILL}\n"
        f"- 备用账号（主号被封后 24 小时导流路径）：{FILL}\n\n"
        # 2026-09-19（B 批 · 客服舆情第 9 条）：8.3.3 只管「差评来了怎么处理」，
        #   而**评论区是第二个客服台** —— 谁值守、多久内回、什么必须回、什么必须删，
        #   全库一个字段都没有。没有值守规则，结果就是「投放把评论冲上来、没人接」。
        f"### 8.3.5 评论区与私信值守（**评论区是第二个客服台，不是第二个广告位**）\n"
        f"| 平台 | 值守人（几班／几点到几点） | 首响时限 | 必须回的内容 | "
        f"**必须删或举报的** | 置顶内容 | 负面聚集时做什么 |\n"
        f"|---|---|---|---|---|---|---|\n"
        f"| {FILL} | {FILL}（例：2 班，10:00–22:00） | {FILL} | 提问／比价／参数疑问 | "
        f"人身攻击、竞品刷屏、涉政涉黄涉赌 | {FILL} | {FILL} |\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
                  for _ in range(2)) + "\n"
        f"- **同类问题 ≥3 条** → 触发 8.6.1「同一问题 ≥3 条」那一行（按舆情升级，不按客服处理）\n"
        f"- 私信与评论**分开值守**：私信里有成交机会，评论里有口碑风险，混在一起两件都做不好\n"
        f"- 一线**不得自行解释功效**（口径见 3.2），**不得与用户争论、不得私了删评**\n"
        f"- 未回复的差评如何被看见（谁每天收口一次）：{FILL}\n\n"
        f"### 8.4 关键假设与验证\n{FILL}\n\n"
        f"### 8.5 待解决问题清单\n{FILL}\n\n"
        f"### 8.6 不承诺的事\n{FILL}\n\n"
        # 2026-09-17（客服舆情视角第 2 条）：原本只有 G 端一行「舆情风险清单与应对」，
        #   标准/B端/投标三档完全没有 —— 什么情况升级、谁能对外发声、几小时内回应，全是空白。
        f"### 8.6.1 舆情升级与对外发声（**出事了谁说话、多久内说**）\n"
        f"| 触发线 | 升级给谁 | 对外口径 | 承诺回应时限 | 发声人 |\n|---|---|---|---|---|\n"
        f"| 单条差评 | {FILL} | {FILL} | 2 小时 | {FILL} |\n"
        f"| 同一问题 ≥3 条 | {FILL} | {FILL} | 6 小时 | {FILL} |\n"
        f"| 上热搜／被媒体报道 | {FILL} | 「物料已第一时间下架，我们主动配合核查，不对外解释处罚细节」 | 2 小时 | {FILL} |\n"
        # 2026-09-19（B 批 · 危机三件之「口径审批人」）：上表有「发声人」一列，
        #   但**没有「只有一个」这件事** —— 舆情事故里最常见的二次伤害，是
        #   一线／加盟商／外包客服／合作达人的**个人号抢先代表品牌说话**，
        #   以及回复出去了才发现口径没人审。这里把「唯一性」写成字段。
        f"\n**唯一发声人 ＋ 口径审批（危机里最先坏掉的不是内容，是**谁在说话**）**\n"
        f"| 项 | 内容 |\n|---|---|\n"
        f"| **唯一对外发声口**（品牌名下只有这 1 个署名，写清是谁／职务） | {FILL} |\n"
        f"| **口径审批人**（对外每一句发出前由谁签字；未经审批不得回复） | {FILL} |\n"
        f"| **全员静默范围**（一线／加盟商／外包客服／合作达人的个人号**不得代表品牌发声**，也不得在评论区争论） | {FILL} |\n"
        f"| 违反静默的处置 | {FILL} |\n"
        f"| 沉默模板（**不是所有事都要说**：不表态也是一种口径，写清什么情况用它） | {FILL} |\n\n"
        f"### 8.6.2 被举报与判罚的应对（3.2 只写了「预防」，这里写「被举报后」）\n"
        f"- 谁对接监管／平台：{FILL}\n- 几小时内完成下架：{FILL}\n"
        f"- 整改留痕（留存什么证据）：{FILL}\n- 统一口径（谁能对外说）：{FILL}\n\n"
        # 2026-09-17 新增（贝恩视角第 2 条）：Red Team。原先只要求「必须有一条反对意见」，
        # 且 selfcheck 无此关 —— 等于「提过一句反对」就算做过压力测试。
        f"### 8.7 这个方案最可能怎么死（**Red Team，定长三条**）\n"
        f"> 只提一句反对不算压力测试。三条必须**互不相同**（两两相似会被判复读）。\n\n"
        f"**死法 1**\n"
        f"- 最强反方论点：{FILL}（≥15 实字）\n"
        f"- 它成立的条件（**必须含数字或日期**）：{FILL}\n"
        f"- 我们的应对，或主动接受的代价：{FILL}\n\n"
        f"**死法 2**\n"
        f"- 最强反方论点：{FILL}\n- 它成立的条件：{FILL}\n- 我们的应对：{FILL}\n\n"
        f"**死法 3**\n"
        f"- 最强反方论点：{FILL}\n- 它成立的条件：{FILL}\n- 我们的应对：{FILL}\n\n"
        f"**我们认为本方案最脆弱的一条假设是**：{FILL}"
        f"（若…则不成立／若…就放弃）\n\n"
        f"### 8.8 制作可行性与档期（**做得出来才算方案**）\n"
        f"| 物料 | 形态 | 制作方 | 前置期 | 硬条件（场地/模特/资质/审批） | 最晚定稿日 | 难度 |\n"
        f"|---|---|---|---|---|---|---|\n| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        # 2026-09-17（运营 R3 第 5 条）：没有分阶段复盘节点，异常往往拖到结案才发现。
        # 2026-09-17（法务版权视角第 3／4／5／6／8 条）：全库「授权／版权」命中约 30 处，
        #   而**没有一处落在生成稿的必需字段里** —— 达人塌房、素材侵权、肖像权、UGC 超范围使用
        #   全都无从自证。这一节是「出事了拿得出东西」的那一节。
        f"### 8.9 外部合作合同要点（**达人／拍摄／场地／物料**）\n"
        # 2026-09-19 补三列（平台视角第 5 条 ＋ 合规视角第 11 条）：
        #   原表没有**结算方式**（纯佣／坑位费／保量）→ 报价与效果不绑，付了钱没交付说不清；
        #   也没有**不可抗力与责任上限** → 出事了谁赔、赔到哪，没有成文约定。
        f"| 对象 | 排他期 | 内容归属与二次分发权 | 发布后不得删稿期限 | "
        f"**结算方式与效果绑定（纯佣／坑位费／保量＋未达标扣减）** | 数据造假与违约金 | "
        f"**不可抗力（范围／通知／免责）** | **责任上限（以合同额为限／排除间接损失）** |\n"
        f"|---|---|---|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
                  for _ in range(3)) + "\n"
        # 2026-09-19（B 批 · 危机三件之「达人塌房切割与追偿」）：上表有「数据造假与违约金」
        #   一列，但那管的是**数据**；达人**塌房**（违法／失德／被处罚）是另一条链 ——
        #   它要的是「几小时内切、切哪些位、切了之后素材从哪来、钱怎么追回来」。
        #   不切割 ＝ 品牌连坐；切得快但留不下证 ＝ 追偿无依据。
        f"### 8.9.1 达人塌房：切割与追偿（**切得快靠预案，追得回靠留证**）\n"
        f"| 阶段 | 时限 | 谁做 | 做什么 | **留什么证** |\n|---|---|---|---|---|\n"
        f"| 发现 | {FILL}（谁监测：平台处罚公示／舆情工具／粉丝提醒） | {FILL} | 记录首发链接与时间 | 截图＋链接（**带时间戳**） |\n"
        f"| 定性 | 24 小时内 | {FILL} | **只认官方通报／平台处罚／本人承认** —— 未定性不切割、也不背书 | 通报原文 |\n"
        f"| 内容处置 | 定性后 2 小时内 | {FILL} | 全部位下架或隐藏（列出受影响位置清单） | 下架前后截图 |\n"
        f"| 是否发声 | 定性后 6 小时内 | {FILL} | 说与不说的分界：{FILL} | 口径审批记录 |\n"
        f"| 追偿 | {FILL} | {FILL} | 依合同哪一条｜已付费用／违约金／未消耗排期怎么算 | 合同条款＋付款凭证 |\n"
        f"| 复盘 | 结案后 3 天 | {FILL} | 选人标准加哪一条（例：近 12 个月无行政处罚） | 更新后的选人清单 |\n\n"
        f"- **连坐面控制**：单一达人素材占本次总素材量 ≤ {FILL}%（塌房时被牵连的位越少，切割越便宜）\n"
        f"- **备用素材**：塌房后 2 小时内可替换的储备从哪来：{FILL}\n\n"
        # 2026-09-19（C 批第五批 · 体系6 #13「责任与保险」）：全仓 grep「保险／责任险／赔偿上限」
        #   **零命中** —— 出了事谁赔、赔到哪、投保没有，一个字都没有。
        #   而现场活动（搭台／试吃／亲子／户外）恰恰是人身意外高发场景。
        f"### 8.9.2 责任与保险（**出了事谁赔、赔到哪、投保没有**）\n"
        f"| 风险场景 | 谁赔（我方／客户／第三方／连带） | **赔偿上限（以合同额为限／单项封顶）** | "
        f"**是否投保·险种与保额** | 凭证留哪 |\n"
        f"|---|---|---|---|---|\n"
        f"| 现场活动人身意外（搭台／试吃／亲子／户外） | {FILL} | {FILL} | {FILL}（例：公众责任险，单次事故 100 万） | {FILL} |\n"
        f"| 素材侵权／肖像权投诉 | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"| 达人／KOL 违约或塌房 | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        f"> **「谁赔」要写到主体**（我方／客户／第三方），「赔到哪」要写**上限**（以合同额为限／单项封顶）——\n"
        f"> 只写「按合同约定」等于没写。**没有保险的现场活动，一次意外就能把整年的毛利吃掉。**\n\n"
        f"### 8.10 授权与素材来源（**出事时拿得出东西**）\n"
        f"| 项 | 内容 |\n|---|---|\n"
        f"| 肖像／声音授权书（谁签、范围、期限） | {FILL} |\n"
        f"| 素材来源（自拍／客户提供／付费图库编号，**逐项列**） | {FILL} |\n"
        f"| 字体授权（所用字体｜授权类型：系统自带／已购／免费商用｜凭据） | {FILL} |\n"
        f"| 音乐／音效（平台免费商用曲库／自行录制，**不得用热门歌**） | {FILL} |\n"
        f"| UGC 授权口径（参与即同意品牌在＿＿范围内商用／署名方式） | {FILL} |\n"
        f"| 非遗／专利／认证：证明文件编号＋有效期＋权利人授权书 | {FILL} |\n\n"
        # 2026-09-19（B 批 · 合规视角第 4 条）：全仓「隐私政策／告知同意／最小必要／留存期限／
        #   第三方共享」**一个交付字段都没有** —— 而 selfcheck 的 16a 只扫手机号字面。
        #   加微／建群／人脸／定位这些动作在方案里天天出现，个人信息合规是刚性要求。
        f"### 8.10.1 个人信息与隐私合规台账（**收集了谁的什么，凭什么、留多久**）\n"
        f"| 收集字段 | 用途 | **合法性基础**（同意／履行合同／法定义务） | 告知方式 | "
        f"**最小必要核验** | **留存期限** | 共享接收方 | 删除／撤回路径 |\n|---|---|---|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
                  for _ in range(3)) + "\n"
        f"> 涉及**敏感个人信息**（人脸／生物识别／医疗健康／金融账户／行踪轨迹）须**单独同意**，\n"
        f"> 未成年人须**监护人同意**。**不写留存期限＝默认永久保存**，这是最常被查的一条。\n\n"
        # 2026-09-19（B 批 · 4A 工序第 11 条）：8.10 只对肖像与非遗判了「期限」，
        #   而**版权／字体授权是有期限的** —— 到期还在用就是侵权。要一张台账。
        f"### 8.10.2 素材资产台账（**授权到期还在用＝侵权**）\n"
        f"| 素材名（品牌_渠道_主题_版本_日期） | 版本 | **授权起止** | 二次分发权 | **到期替换动作** | 提醒节点 |\n"
        f"|---|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n" for _ in range(3)) + "\n"
        f"> 命名要带**版本与日期**（同一张主视觉改过三版，靠文件名就能分清）；"
        f"**授权起止与到期替换动作两列必须填** —— 字体／音乐／肖像／付费图库都有期限，"
        f"到期不换就是持续侵权，而且通常是客户被投诉了才知道。\n\n"
        f"### 8.11 复盘节点（**看哪三个数、谁主持、不达标触发哪条兜底**）\n"
        f"| 节点 | 看哪 3 个数 | 谁主持 | 不达标触发 |\n|---|---|---|---|\n"
        f"| T+3 天 | {FILL} | {FILL} | {FILL} |\n"
        f"| 第 1 周末 | {FILL} | {FILL} | {FILL} |\n"
        f"| 结案 | {FILL} | {FILL} | {FILL} |\n\n"
        # 2026-09-19（B 批 · 执行视角第 4 条）：8.11 只有「T+3／首周末／结案」——
        #   那是活动内节点，不是**跨月推进节奏**。而知识库里已有现成模板
        #   （`references/05:1166`「新品牌上市 90 天作战计划」13 周表）没被接进骨架。
        f"### 8.12 推进里程碑（30／60／90 天，**跨月客户必挂**）\n"
        f"| 阶段 | 起止 | 交付物 | 负责人 | 这一段看哪个数 | 不达标则停／改什么 |\n|---|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
                  for _ in range(3)) + "\n"
        f"> 三段分别是 30／60／90 天。**每段都要绑一个交付物和一个量化信号** ——\n"
        f"> 「持续推进」不是里程碑；「第 30 天单店动销达 X 件，未达则换选品」才是。\n\n"
        # 2026-09-19（B 批 · 合规视角第 15 条）：文档治理的「人」这一层 —— 改了哪几版、
        #   为什么改、谁批的。缺它，第 10 条交付治理就上不去。
        f"### 8.13 变更记录（**版版可追，谁批的写清楚**）\n"
        f"| 日期 | 改了什么 | 为什么改 | 谁批的 |\n|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} |\n" for _ in range(2)) + "\n"
        # 2026-09-19（B 批 · 治理节奏与变更控制）：8.13 是**日志**（改了什么），
        #   缺的是**规则** —— 变更怎么提、谁批、几天内答复、什么算「范围外」，
        #   以及方案交付之后**谁在什么时候复核**。没有这层，方案签完就开始失控：
        #   客户随口加一个渠道，交付方默默做三个月，双方都没有「这算新增」的依据。
        f"### 8.14 变更控制与范围边界（**方案签完不是结束，是变更开始**）\n"
        f"**① 变更流程**（什么变更走什么口，以及**什么算范围外**）\n"
        f"| 变更类型 | 谁提 | **谁批** | **答复时限** | 影响面（要改哪几节） | **工作量归属**（范围内／新增计费） |\n"
        f"|---|---|---|---|---|---|\n"
        f"| 文案微调 | 客户对接人 | 项目经理 | 1 个工作日 | 仅 5.x | 范围内 |\n"
        f"| 新增渠道／平台 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        f"| 改目标人群／定位 | 客户决策人 | 双方负责人 | 3 个工作日 | 一·／二·／三· 全章 | 新增工作量 |\n\n"
        f"**② 评审节奏**（谁在什么时候复核，不通过则怎么办）\n"
        f"| 节点 | 时间 | 谁参加 | 这次只裁决什么 | 不通过则 |\n|---|---|---|---|---|\n"
        f"| 初稿评审 | {FILL} | {FILL} | 核心判断与打法是否成立 | 改后 2 天内复审 |\n"
        f"| 定稿评审 | {FILL} | {FILL} | 数据与口径是否一致 | {FILL} |\n\n"
        f"- **范围边界**（本方案**不做什么** —— 写清才挡得住范围蔓延）：{FILL}\n"
        f"- **争议升级**（双方意见不一致时谁裁、几个工作日内给出结论）：{FILL}\n"
        f"- 每次变更**都要回到 8.13 变更记录留一行**（日期／改了什么／为什么／谁批的）\n\n"
        # 2026-09-19（C 批 · 体系1 #8「结案移交与后续 90 天」）：全仓**零「移交／交接」**字段 ——
        #   方案结案后谁接手、文件在哪、账号权限怎么转、90 天看什么，一条都没有。
        #   结果就是「方案交付即失联」，客户内部也接不住。
        f"### 8.16 结案移交与后续 90 天（**交付不是终点，交接完才算**）\n"
        f"| 移交项 | 内容 | 交给谁（岗位） | 什么时候交 |\n|---|---|---|---|\n"
        f"| 交付文件（含源文件在哪、版本怎么认） | {FILL} | {FILL} | {FILL} |\n"
        f"| **账号与权限**（平台后台／投放账户／私域工具／素材库） | {FILL} | {FILL} | {FILL} |\n"
        f"| 未结事项（还在跑的活动、未付的款、未签的合同） | {FILL} | {FILL} | {FILL} |\n\n"
        f"**后续 90 天观察**（谁在看、看哪几个数、什么信号触发回流）：\n"
        f"| 观察期 | 看哪 3 个数 | 观测人（岗位） | 什么信号算「要改」 |\n|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} |\n" for _ in range(3))
        + f"\n- **复盘回流**（哪些结论要写回知识库／下一版方案）：{FILL}\n\n"
    )

    # 2026-09-17：原「附件 · 交付自检单」整章移出交付稿 —— 自检单是**内部质检记录**，
    #   按协定它就该原样输出在 AI 的**回复中**给用户看，而不是印在客户方案的最后一页。
    #   → 改写进 internal 文件（见 `build_internal`），交付稿只留客户要看的内容。
    # 场景章节：大赛／B端／G端／投标 各自有必须有的章节（缺一块＝不完整）
    # 不同档位给不同骨架：--tier 直接等于场景名时，自动注入该场景专属章节。
    _TIER_SCENE = {"标准": "标准", "大赛": "大赛", "B端": "B端", "G端": "G端", "投标": "投标"}
    if not scene:
        scene = _TIER_SCENE.get(tier, "标准")
    # ⚠️ 2026-09-17（评审侧审计第 5 条）：议题树（两张大空表）原本压在「现状分析」之前，
    #   实测「### 1.2 真正的卡点」之前有 42 个【填】、841 字 —— 决策者只看前两页，
    #   看到的是两张空表，看不到「方案的核心判断」，容易被判「没有结论」。
    #   → 把 〇 章移到现状分析之后：先给判断，再给推导。
    body = (head + diagnosis + zeroth + strategy + insight + brief + positioning + reach + creative + copy_
            + kpi + budget + exec_ + scene_body(scene, client, probe_traits(rules),
                                                detect_industry(rules)))
    return body


# ─────────────────────────────────────────────────────────────
# 5a. 场景章节（2026-09-17 新增）
#     用户：「这个框架的内容种类都太少了，根本就不是一个完整的策划」。
#     → 四类交付场景各自有**必须有的章节**，缺一块就是不完整。
#       章节清单与评分标准见 `references/09-完整策划标准与评分表.md`。
# ─────────────────────────────────────────────────────────────
SCENE_SECTIONS = {
    # 2026-09-17 新增：C 端品牌（＝「标准」档）。用户原话：「例如B端的、C端的、小客户的，
    #   都需要有他们各自的一个范式」—— 原本「标准」档无场景，会 fallback 到 B 端场景章
    #   （生意拆解／单位经济／商务条款），对消费品牌是错配。这里补上 C 端专属四章。
    "标准": (
        "## 九 · 产品与货盘结构（卖什么组合，比怎么推广更先决定成败）\n"
        "| 产品／SKU | 在货盘里的角色 | 价格带 | 毛利 | 承担什么任务 |\n|---|---|---|---|---|\n"
        "| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        "- **价格带阶梯**：{FILL} 元 → {FILL} 元 → {FILL} 元（对应三种决策路径：试试看／认真买／囤货）\n"
        "- **组货逻辑一句话**：{FILL}\n\n"
        "## 十 · 内容与种草矩阵（谁来说／在哪说／说什么）\n"
        "- **核心母题**（只留一个，其余全部让位）：{FILL}\n"
        "| 内容类型 | 说什么 | 谁来说 | 发在哪 | 频次 |\n|---|---|---|---|---|\n"
        "| 科普 | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        "| 体验 | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        "| 趣味 | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        # 2026-09-17（平台算法视角第 1／4／7 条）：
        #   ① 算法靠前 5–10 条内容给账号打人群标签，而方案只排「发什么」，不排「怎么喂标签」；
        #   ② 达人投放只剩「谁来说」一格，缺分层／占比／防刷；
        #   ③ 内容产能与素材复用无字段 —— 算法要持续更新，断更掉权重。
        "## 十·二 · 账号冷启动（**第 1–30 条内容怎么喂标签**）\n"
        "| 账号 | 身份一句话 | 内容支柱（3 个） | 前 5 条选题 | 发布节奏 | 每 10 条复盘哪 3 个数 | 爆款复制规则 |\n"
        "|---|---|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
                  for _ in range(2)) + "\n"
        "> **前 5 条必须同一人群、同一话题** —— 算法就是靠这 5 条给你打标签。\n\n"
        "### 10.1 达人投放分层（**占比与防刷必须同时写**）\n"
        "| 层级 | 人数 | 单价 | 预算占比 | 互动率下限 | 归因口径 | 防刷动作 | 复投规则 |\n"
        "|---|---|---|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
                  for _ in range(3)) + "\n"
        "> 预算占比合计须 ≈100%；「互动率下限」用来卡掉有水分的达人。\n\n"
        "### 10.2 内容产能与复用（**断更掉权重，周条数要落到人**）\n"
        # 2026-09-19（A 批 · 平台视角第 12 条）：原表有「复用去向≥3」但**没有切点定义**
        #   —— 只说「切 3 条」不说「从哪切」，执行的人只能从头到尾硬切。
        "| 每周条数 | 主产人（岗位） | 拍摄日 | 单条工时 | 母素材复用去向（≥3） | "
        "**切片切点（≥3 个具体内容点，如「00:12 翻车瞬间」）** | 备用库存 |\n"
        "|---|---|---|---|---|---|---|\n"
        + f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        "## 十一 · 会员与复购机制（拉新之后怎么留下）\n"
        # 2026-09-17（私域视角第 1／2／6 条）：
        #   ① 全案没回答「用户凭什么扫这个码」；② 起点原写「购买后第 N 天」，
        #   而打法库要求「**加好友后** 24 小时内发放承诺权益」；③ 唤醒只有一个空位。
        f"- **加微钩子**（用户凭什么扫这个码，**必须是一个即时可用的东西，不是券**）：{FILL}\n"
        f"- **承接载体**（企微／个人号／群，选一并说明理由）：{FILL}\n"
        # 2026-09-19（A 批 · 平台视角第 6 条）：原句是「选一并说明理由」——
        #   没有判据，等于让人自己拍脑袋。给一张四条判据的对比表。
        f"- **载体怎么选**（四条判据，逐条填）：\n"
        f"| 判据 | 企微 | 个人号 | 群 | 本案选哪个 |\n"
        f"|---|---|---|---|---|\n"
        f"| 客户资产归属（离职带走？） | 归属公司 | 归属个人 | 归属群主 | {FILL} |\n"
        f"| 群发与自动化能力 | 强 | 弱 | 中 | {FILL} |\n"
        f"| 封号风险 | 低 | 高 | 中 | {FILL} |\n"
        f"| 员工离职时的迁移成本 | 低 | 高 | 高 | {FILL} |\n\n"
        f"> **有员工流失风险的连锁一律选企微** —— 客户资产不能挂在个人号上。\n\n"
        f"### 11.1 加微后 0–24 小时（**起点是「加好友后」，不是「购买后」**）\n"
        f"| 时点 | 动作 | 话术（示例） | 责任人 |\n|---|---|---|---|\n"
        f"| 0–2 小时 | 发放承诺的权益 | 「你领的表在第 2 页；顺便说：本周首单减 15，只到周五」 | {FILL} |\n"
        f"| 24–48 小时 | 首单推动 | {FILL} | {FILL} |\n"
        f"| 7 天未购 | 再推一次（**换理由，不重复原话**） | {FILL} | {FILL} |\n\n"
        f"### 11.2 沉睡唤醒（**分三段，每段配不同理由**）\n"
        f"| 沉睡段 | 唤醒理由 | 渠道 | 话术 |\n|---|---|---|---|\n"
        f"| 30–60 天 | {FILL} | {FILL} | 「张姐，你上次买的是去渍款，新到的同款加了便携装，老客价 39，只留到周日」 |\n"
        f"| 60–90 天 | {FILL} | {FILL} | {FILL} |\n"
        f"| 90 天以上 | {FILL} | {FILL} | {FILL} |\n\n"
        f"### 11.3 老带新（**分利与防刷必须同时写**）\n"
        f"- 分利：「你介绍的人首单成，你俩各得 20 元券，24 小时到账」：{FILL}\n"
        f"- 防刷：「同手机号／同地址只算一次」，另加 2 条：{FILL}\n"
        f"- **私域合规红线**：不诱导分享／不助力集赞／不砍价免费拿／不向个人号收款／"
        f"不用个人号存客户资产：{FILL}\n\n"
        # 2026-09-17（连锁加盟视角第 1／4 条）：标准档（最常服务连锁品牌）原本只锁价格，
        #   物料／VI／话术零字 —— 门店不知哪些不能改，只能自行发挥；
        #   而且**没人查门店做没做**。
        "## 十一·四 · 总部与门店的权责（**哪些必须统一、哪些可本地调**）\n"
        "| 必须统一（越界后果） | 门店可本地调的范围 |\n|---|---|\n"
        f"| {FILL}：VI／主视觉／价格／活动名／核心话术 —— 越界＝整改并停供物料 | {FILL}：赠品／地推形式／社群节奏 |\n"
        # ⚠️ 2026-09-19：GUIDE 要求「必须统一／可本地调」两栏**各 ≥8 条**，
        #   而骨架原先只预填 1 行 ＋ 3 行空行（共 4 行）→ 要求与给位不符。补到 8 行。
        + "".join(f"| {FILL} | {FILL} |\n" for _ in range(7)) + "\n"
        "### 11.4.1 稽核表（**没人查＝没人做**）\n"
        # ⚠️ 2026-09-19 补两列：上一轮加的 selfcheck【19a】要求「谁查／查完报给谁」，
        #   但**骨架这张表当时只有 5 列、根本没有这两列** —— 真出稿必然空转
        #   （「骨架不给位、检查查不到」，本仓库的坑 5，这次是我自己踩的）。
        "| 检查项 | 频率 | 抽查比例 | 合格线 | **谁查（岗位）** | **查完报给谁** | 不合格处置（整改／扣保证金／停供物料） |\n"
        "|---|---|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n" for _ in range(3)) + "\n"
        "### 11.4.2 培训与物料下发\n"
        # ⚠️ 2026-09-19 补两列（A 批 · 执行视角第 9 条）：
        #   原表有「考核合格线」却没有「谁培训」与「不合格怎么办」——
        #   「培训过了」这句话没人能验证。
        "| 对象 | 课时 | 形式 | **谁培训** | 考核合格线 | **不合格处置** | 物料下发方式 | 安装责任（谁装／几号前） | 损耗与补货 | 到店截止日 | 签收人 |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|\n"
        + f"| 店长／店员 | {FILL} | {FILL} | {FILL} | {FILL} | 当日补考／跟班／不上活动 | {FILL} | {FILL} | 损坏谁赔／补货周期 | {FILL} | {FILL} |\n\n"
        "## 十一·五 · 社群运营（**私域的主要容器，没人管三天就变广告群**）\n"
        "| 项 | 内容 |\n|---|---|\n"
        f"| 群定位 | {FILL} |\n| 入群门槛 | {FILL} |\n"
        f"| 群规（3 条，含一条「什么会被移出」） | {FILL} |\n"
        f"| 固定栏目（周一上新／周三问答／周五福利…） | {FILL} |\n"
        f"| 群主与轮值 | {FILL} |\n"
        f"| 退群预警线（周退群 > X% 就要查） | {FILL} |\n\n"
        "- **留存节奏**：购买后第 {FILL} 天／第 {FILL} 天／第 {FILL} 天各触达一次，内容分别是 {FILL}\n"
        "- **复购触发条件**：{FILL}（用完／某时点／某行为）\n"
        "- **会员权益**（写清给什么、成本多少）：{FILL}\n"
        "- **沉默唤醒**：超过 {FILL} 天未复购的动作：{FILL}\n\n"
        "## 十二 · 渠道价格与控价（不写这节，活动一开就乱价）\n"
        "- **各渠道价格带**：线上 {FILL}／线下 {FILL}／私域 {FILL}；差异来自 {FILL}（赠品／服务／规格），不是直接降价\n"
        "- **控价规则**：低于 {FILL} 元销售的处理流程：{FILL}\n"
        "- **促销机制边界**（什么折扣不能给）：{FILL}\n\n"
        "## 十三 · 利益相关者与阻力处理（**方案能不能落地，一半看这里**）\n"
        "> 门禁就问过「对接人与决策人」—— 这一章就是回答「谁会支持、谁会拦、拦的理由是什么」。\n\n"
        # ⚠️ 2026-09-19 补两列（A 批 · 执行视角第 10 条）：
        #   原表只到「我们的处理动作」—— 没有**让步边界**就不知道谈到哪算到底，
        #   没有**转向条件**就只是「去谈」。基线把这条打 1.0 分，正因如此。
        "| 角色 | 立场（支持／中立／反对） | 反对的**真实理由** | 我们的处理动作 | **可让步（≤X）／不可让步底线** | **他转向支持的条件** | 谁去谈·何时 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        "- **至少 3 个角色**，其中**至少 1 个是反对者**（全是「支持」＝这份方案没做过推演）。\n"
        "- 「反对的真实理由」要写他的**利益或担忧**，不是「观念落后」。\n"
        f"- 数据来源清单（来源／口径／时点）：{FILL}\n\n"
        # 2026-09-17（R2 数据科学视角第 2 条）：C 端最常缺的一节 —— 单位经济模型。
        # 原本只有 B 端有，于是 C 端美妆案不回答「花多少钱换一个客、这个客值多少钱」，
        # 财务上完全不可证伪。
        "## 十四 · 单位经济与回本（**花多少钱换一个客，这个客值多少钱**）\n"
        # 2026-09-17（投资人视角第 2／3／6 条）：三处量纲与口径修正 ——
        #   ① LTV 原写「客单价×毛利率×**年**复购次数」＝**年**毛利，却拿去和 CAC 比判据 ≥3
        #      （那是生命周期口径）→ 量纲混用，投资人一代入就发现算不平。
        #   ② CAC 原写「总投放 ÷ 新客数」，未含内容制作／达人佣金／工具／人力折算 →
        #      最容易把「重度人力」算成划算。改成明细加总。
        #   ③ 回本周期原用「单客月均毛利」，该项**不在五项里也没有定义** → 补进公式。
        "| 指标 | 公式（**口径写清才可被复算**） | 本案数值 | 口径／来源 |\n|---|---|---|---|\n"
        f"| 单客获取成本 CAC | （媒介投放 + 内容制作 + 合作佣金 + 工具/SCRM + **人力折算**）"
        f"÷ 新增首购客户数（归因窗口 30 天） | {FILL} | {FILL} |\n"
        f"| 客单价 | 销售额 ÷ 订单数 | {FILL} | {FILL} |\n"
        f"| 毛利率 | （客单价 − 变动成本）÷ 客单价 | {FILL} | {FILL} |\n"
        f"| 年复购次数 | 年度订单数 ÷ 年度客户数 | {FILL} | {FILL} |\n"
        f"| 留存年限 | 首购后仍能产生复购的年数 | {FILL} | {FILL} |\n"
        f"| 单客生命周期价值 LTV | 客单价 × 毛利率 × **年复购次数 × 留存年限** | {FILL} | {FILL} |\n"
        # 2026-09-19（A 批 · 投资人视角第 14 条）：只有生命周期口径不够 ——
        #   **首单亏是常态**，但要写明亏多少、以及最长的容忍回本月数。
        f"| 回本周期（月） | CAC ÷ （客单价 × 毛利率 × 月均复购次数） | {FILL} | {FILL} |\n"
        f"| **首单 ROI** | 首单毛利 ÷ CAC（**允许 <1，但要写明最长容忍回本月数**） | {FILL} | {FILL} |\n\n"
        # 2026-09-17（R6 连锁加盟第 5 条）：只写「对执行人的好处」不够 ——
        #   加盟商是**独立法人**，要算他自己的账，否则他没理由配合。
        f"### 14.1 对门店／加盟商的账（**他不配合是因为你没算给他看**）\n"
        f"| 单店投入（元） | 月均增量毛利（元） | 回本月数 | LTV/CAC | "
        f"**试点选择标准** | **首批家数** | **首批额外激励** | **试点期** | **成功判据** |\n"
        f"|---|---|---|---|---|---|---|---|---|\n"
        + f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        # 2026-09-19（A 批 · 执行视角第 3 条）：只算账不够 —— 要回答
        #   「先让哪 10 家动、给它们什么额外好处、用它们的数据说服剩下的人」。
        f"> **单店投入**回本月数 > {_C.PAYBACK_WARN_STORE} 个月 → 加盟商大概率软抵抗，需要总部补贴或分批投入。\n"
        # ⚠️ 2026-09-19：这里和「CAC 回本周期 ≤12 个月」是**两个不同的口径**，
        #   别把它们当成同一个数（原先两处都写「回本」，读的人会以为差一倍）。
        #   单店投入回收（加盟商视角）≤6 个月；CAC 回收（投放视角）≤12 个月。
        f"> 与之区分：**CAC 回本周期**（收回获客成本）的警戒线是 ≤12 个月 —— 两个口径不同。\n"
        # 2026-09-19（A 批 · 投资人视角第 9 条）：知识库明说「一定要分渠道算 LTV，
        #   不同渠道用户质量差异巨大」，而骨架只有一张合计表 → 混着算会把
        #   高质渠道的钱补贴到低质渠道上。
        f"### 14.2 分渠道单位经济（**混着算会把高质渠道补贴给低质渠道**）\n"
        f"| 渠道 | CAC | LTV | LTV÷CAC | 首单 ROI | 回本周期（月） | 结论（加投／维持／停） |\n"
        f"|---|---|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
                  for _ in range(2)) + "\n"
        # 2026-09-17（R5 私域第 7 条）：没有交易载体与标签口径，复购券发不对人，方案停在动作层。
        f"## 十五 · 工具与数据底座\n"
        f"| 用途 | 工具 | 谁建 | 上线时间 | 月成本 | 谁维护 |\n|---|---|---|---|---|---|\n"
        + "".join(f"| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
                  for _ in range(3))
        + f"\n**标签口径**（复购券要发对人，靠的就是这套）：价值（高/中/低）｜偏好（品类/价格带）｜"
          f"状态（新客/复购/沉睡）：{FILL}\n\n"
        "> **三项必须能互推**（容差 5%）：LTV÷CAC ≥ 3 才算这笔投放站得住；< 1 就是卖一单亏一单。\n\n"
        "> 判据：**LTV / CAC ≥ 3** 才算这笔投放站得住；< 1 就是卖一单亏一单。\n\n"
    ),
    "大赛": (
        "## 九 · 创意设计执行（大赛必写，只有概念没有样稿＝失分）\n"
        "- **Big Idea（一句话，能被别人复述）**：{FILL}\n"
        "- **主视觉与文案样稿**：{FILL}（把文案写出来，不是描述长什么样）\n"
        "- **物料清单与样稿**（海报／短视频／H5／线下）：\n"
        "  - 海报主文案：{FILL}\n"
        "  - 短视频脚本（15 秒，分镜）：{FILL}\n"
        "  - 线下物料：{FILL}\n"
        "- **回指**（强制格式，不是自述）：本条创意解决【打法 {FILL}】的第【{FILL}】步"
        "（原问题：{FILL}）\n\n"
        "## 十 · 媒介排期表（哪天发什么，不是只写渠道名）\n"
        "| 阶段 | 日期 | 渠道 | 内容 | 频次 | 负责人 |\n|---|---|---|---|---|---|\n"
        "| 预热 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        "| 引爆 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        "| 承接 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        "## 十一 · 提案脚本（现场提案 8 分钟）\n"
        "| 时间 | 讲什么 | 对应页 |\n|---|---|---|\n"
        "| 0:00–0:40 | 一句话结论（我们建议做什么、预期得到什么） | {FILL} |\n"
        "| 0:40–2:30 | 为什么是这个卡点（数据＋排除其他解释） | {FILL} |\n"
        "| 2:30–5:00 | 核心策略与打法（挑最强的 2–3 条深讲） | {FILL} |\n"
        "| 5:00–7:00 | 创意与执行（亮样稿） | {FILL} |\n"
        "| 7:00–8:00 | 预算与预期效果（收尾回到结论） | {FILL} |\n\n"
        # 2026-09-17（评审侧审计第 3 条）：标题写「10 个最可能被问的」，实际只有 4 条实问
        #   ＋1 条空的（且官方要求就是 10 个）。现场问答占 30–50 分，答到第 5 问就哑。
        #   → 补足 10 条，并强制「证据在第几页」——评委最烦「答了但拿不出东西」。
        "## 十二 · 评委问答预判（10 个最可能被问的）\n"
        "| # | 预判问题 | 标准答法 | 证据在第几页 |\n|---|---|---|---|\n"
        "| 1 | 为什么选这个人群／这个方向？ | {FILL} | {FILL} |\n"
        "| 2 | 预算为什么这么分？ | {FILL} | {FILL} |\n"
        "| 3 | 效果怎么衡量？数据从哪来？ | {FILL} | {FILL} |\n"
        "| 4 | 竞品已经在做了，你们有什么不同？ | {FILL} | {FILL} |\n"
        "| 5 | 这套方案的洞察是怎么得出来的？（**评委最爱的追问**） | {FILL} | {FILL} |\n"
        "| 6 | 如果预算砍一半，你砍哪一部分？ | {FILL} | {FILL} |\n"
        "| 7 | 你调研的样本代表谁？偏差在哪？ | {FILL} | {FILL} |\n"
        "| 8 | 执行风险最大的是哪一环？兜底是什么？ | {FILL} | {FILL} |\n"
        "| 9 | 创意里哪个元素是「换任何品牌也成立」的？你们怎么避开的？ | {FILL} | {FILL} |\n"
        "| 10 | 这套方案最可能怎么死？ | {FILL} | {FILL} |\n\n"
        "## 附件 · 一手调研材料（官方要求「调查表附后」）\n"
        "- 调查问卷原件：{FILL}\n- 访谈／走访记录：{FILL}\n"
        "- 数据来源清单（来源／口径／时点）：{FILL}\n- 物料完稿：{FILL}\n\n"
    ),
    "B端": (
        "## 九 · 生意拆解与机会量化\n"
        "> 营收 ＝ 流量 × 转化率 × 客单价 × 复购次数 —— 先拆开，才知道钱漏在哪一层。\n\n"
        "| 因子 | 当前值 | 目标值 | 差距 | 造成差距的主因 | 主要动作 |\n|---|---|---|---|---|---|\n"
        "| 流量 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        "| 转化率 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        "| 客单价 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        "| 复购次数 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        "**最大缺口在哪一层**：{FILL}（一层只选一个，选差距 × 可达性最高的那层）\n\n"
        "## 十 · 财务测算与盈亏平衡（B 端必答，答不上＝拿不到预算）\n"
        "- **投入明细**（一次性／周期性分开列）：\n"
        "  - 一次性：{FILL}\n  - 周期性（月）：{FILL}\n"
        "- **单位经济模型**：单客获取成本 {FILL} 元；单客生命周期价值 {FILL} 元；"
        "回本周期 {FILL}\n"
        "- **盈亏平衡**：需要做到 {FILL} 单／{FILL} 客流才能打平；按当前节奏需要 {FILL} 个月\n"
        "- **敏感性分析**（三档）：\n"
        "| 情景 | 关键假设 | 营收 | 成本 | 结论 |\n|---|---|---|---|---|\n"
        "| 乐观 | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        "| 基准 | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        "| 悲观 | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        "## 十一 · 组织与人力可行性（做不完的方案＝没有方案）\n"
        "| 动作 | 需要谁 | 每周投入 | 现有资源够吗 | 缺口怎么补 |\n|---|---|---|---|---|\n"
        "| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        "## 十二 · 商务条款\n"
        "- 报价与付款节奏：{FILL}\n- 交付物清单与验收标准：{FILL}\n"
        "- 知识产权归属：{FILL}\n- 违约责任与退出机制：{FILL}\n\n"
        "## 十三 · 利益相关者与阻力处理（**方案能不能落地，一半看这里**）\n"
        "> 门禁就问过「对接人与决策人」—— 这一章就是回答「谁会支持、谁会拦、拦的理由是什么」。\n\n"
        # ⚠️ 2026-09-19 补两列（A 批 · 执行视角第 10 条）：
        #   原表只到「我们的处理动作」—— 没有**让步边界**就不知道谈到哪算到底，
        #   没有**转向条件**就只是「去谈」。基线把这条打 1.0 分，正因如此。
        "| 角色 | 立场（支持／中立／反对） | 反对的**真实理由** | 我们的处理动作 | **可让步（≤X）／不可让步底线** | **他转向支持的条件** | 谁去谈·何时 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        "- **至少 3 个角色**，其中**至少 1 个是反对者**（全是「支持」＝这份方案没做过推演）。\n"
        "- 「反对的真实理由」要写他的**利益或担忧**，不是「观念落后」。\n"
        f"- 数据来源清单（来源／口径／时点）：{FILL}\n\n"
    ),
    "G端": (
        "## 九 · 政策依据与上位规划（G 端第一关，没有依据＝直接出局）\n"
        "- **国家层面**：{FILL}（文件名称＋文号＋具体条款）\n"
        "- **省级层面**：{FILL}（文件名称＋文号＋具体条款）\n"
        "- **市级／县级层面**：{FILL}（文件名称＋文号＋具体条款）\n"
        "- **本项目与上位规划的对应关系**：{FILL}\n"
        "- **必要性**：不做会怎样（用数据说明）：{FILL}\n\n"
        "## 十 · 绩效目标与考核（G 端核心，不可考核＝立不了项）\n"
        "| 一级指标 | 二级指标 | 三级指标 | 目标值 | 考核方式 | 责任单位 |\n|---|---|---|---|---|---|\n"
        "| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        "## 十一 · 资金与保障\n"
        "- **总投资**：{FILL} 万元；**资金来源**：财政 {FILL}／专项债 {FILL}／社会资本 {FILL}\n"
        "- **分年度用款计划**：第一年 {FILL}；第二年 {FILL}；第三年 {FILL}\n"
        "- **资金管理办法**：{FILL}\n"
        "- **组织保障**：领导小组 {FILL}；牵头单位 {FILL}；配合单位 {FILL}\n"
        "- **督导与考核机制**：{FILL}\n\n"
        "## 十二 · 汇报与评审\n"
        # 2026-09-17（评审侧审计第 3 条）：原为一行占位反复列出九个词，
        #   等于把 9 页活推给模型。改成 9 行表，每页一句结论 + 数据出处。
        "### 12.1 汇报稿／PPT 骨架\n"
        "| 页 | 标题 | 一句话结论 | 数据／出处 |\n|---|---|---|---|\n"
        + "".join(f"| {_p} | {FILL} | {FILL} | {FILL} |\n"
                  for _p in ["封面", "背景", "依据", "目标", "任务",
                             "实施", "预算", "绩效", "保障"]) + "\n"
        "### 12.2 评审答疑口径\n"
        "| # | 预判问题 | 标准答法 |\n|---|---|---|\n"
        "| 1 | 政策依据充分吗？ | {FILL} |\n"
        "| 2 | 资金从哪来、合规吗？ | {FILL} |\n"
        "| 3 | 绩效目标怎么考核？ | {FILL} |\n\n"
        "## 十三 · 合规与舆情红线\n"
        "- 公文格式与字数页数：{FILL}\n- 禁用词与红线：{FILL}\n"
        "- 舆情风险清单与应对：{FILL}\n\n"
        "## 十四 · 利益相关者与阻力处理（**方案能不能落地，一半看这里**）\n"
        "> 门禁就问过「对接人与决策人」—— 这一章就是回答「谁会支持、谁会拦、拦的理由是什么」。\n\n"
        # ⚠️ 2026-09-19 补两列（A 批 · 执行视角第 10 条）：
        #   原表只到「我们的处理动作」—— 没有**让步边界**就不知道谈到哪算到底，
        #   没有**转向条件**就只是「去谈」。基线把这条打 1.0 分，正因如此。
        "| 角色 | 立场（支持／中立／反对） | 反对的**真实理由** | 我们的处理动作 | **可让步（≤X）／不可让步底线** | **他转向支持的条件** | 谁去谈·何时 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        "- **至少 3 个角色**，其中**至少 1 个是反对者**（全是「支持」＝这份方案没做过推演）。\n"
        "- 「反对的真实理由」要写他的**利益或担忧**，不是「观念落后」。\n\n"
    ),
    "投标": (
        "## 九 · 商务响应偏离表（投标第一优先，格式不符＝废标）\n"
        "> 逐条对照招标要求写「完全响应／正偏离／负偏离」。**先把符合性审查表过一遍再谈创意。**\n\n"
        "| 序号 | 招标要求 | 我方响应 | 偏离说明 |\n|---|---|---|---|\n"
        "| 1 | {FILL} | 完全响应 | {FILL} |\n"
        "| 2 | {FILL} | 正偏离 | {FILL} |\n\n"
        "## 十 · 需求理解（很多标输在这一步 —— 证明你听懂了）\n"
        "- **招标方要解决的核心问题**：{FILL}\n"
        "- **我方理解**（用自己的话复述需求，不照抄）：{FILL}\n"
        "- **关键约束**（预算／周期／合规／既有系统）：{FILL}\n"
        "- **我方的差异化理解**（别人可能忽略的点）：{FILL}\n\n"
        "## 十一 · 实施与保障\n"
        "- **项目组配置**（角色／资历／投入比例）：{FILL}\n"
        "- **进度计划**（里程碑＋交付物）：{FILL}\n"
        "- **质量保障机制**：{FILL}\n- **交付物清单**：{FILL}\n\n"
        "## 十二 · 业绩与售后\n"
        "| 项目名 | 业主 | 金额 | 时间 | 验收情况 |\n|---|---|---|---|---|\n"
        "| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        "- **售后承诺**（响应时效／服务内容）：{FILL}\n- **培训计划**：{FILL}\n\n"
        "## 十三 · 报价与资质\n"
        "| 分项 | 数量 | 单价 | 小计 |\n|---|---|---|---|\n"
        "| {FILL} | {FILL} | {FILL} | {FILL} |\n| — | **合计** | — | **{FILL}** |\n\n"
        "- **资质文件清单**（营业执照／资质证书／财务报表／无重大违法声明）：{FILL}\n\n"
    ),
}

# ─── 附 A · 决策人问答预判（2026-09-19 · C 批「体系1 #6」）────────────────────
# 原先只有**大赛档有「评委问答预判」、G 端有「评审答疑口径」** —— 而**标准／B端／投标**
# 同样要过会、同样会被追问，却一条预判都没有。
# ⚠️ 命名用「附 A」而不是「8.15」：它排在场景章（九～十五）之后，用 8.x 的编号会与章序冲突
#   （而且 `build_paradigm` 的骨架一致性校验会按顺序比对，编号错位会直接判漂移）。
# ⚠️ 只接**这三个档位**：大赛／G端 已有各自的问答章，再接上去就是同一件事印两遍。
_QA_BRIEF = (
    "## 附 A · 决策人问答预判（**拿到会上会被问到的 5 个问题**）\n"
    "> 会上没人问「能不能成」，只会问下面四类。**答不上来的问题，就是方案最薄的地方。**\n\n"
    "| # | 决策人最可能问的问题 | 标准答法（≤3 句，**含数字**） | 证据在第几节 | 属于哪一类 |\n"
    "|---|---|---|---|---|\n"
    "| 1 | 这笔钱能带回多少？ | {FILL} | {FILL} | 效果 |\n"
    "| 2 | 万一第一周就不动销，怎么办？ | {FILL} | {FILL} | 风险 |\n"
    "| 3 | 要我出多少人、多少预算排期？ | {FILL} | {FILL} | 资源 |\n"
    "| 4 | 为什么不直接把钱全砸在别处？ | {FILL} | {FILL} | 取舍 |\n"
    "| 5 | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
    "- **谁去答**（岗位）：{FILL}\n"
    "- **当场答不上来怎么办**（不硬编，要留活口）：{FILL}\n\n"
)
for _s in ("标准", "B端", "投标"):
    SCENE_SECTIONS[_s] = SCENE_SECTIONS[_s] + _QA_BRIEF


# ─── 条件章节：把「能力」从「档位」解耦，改由「客户特征」触发（2026-09-19）────────
#
# ⚠️ 为什么要有这个机制（本轮最重要的一处**结构改动**）：
#   原来「能力」是**挂死在档位**上的 —— 创意链只挂大赛档、连锁那三张表只挂「标准」档。
#   后果不是「少写一节」，而是**整类客户缺章**：
#     · 做连锁的客户若被判进 B 端档 → 拿不到稽核表、培训表、对门店的账
#     · 需要直播的客户 → 全套骨架 `grep「直播|排品|憋单」` **零命中**
#     · 有线下门店的客户 → `grep「美团|点评」` **零命中**
#   → 解法不是「再加几个检查项」，而是**改触发方式**：从档位改成客户特征，命中即注入。
#
# ⚠️ 与门禁 13 项的关系：**不动门禁**（那是不变式 —— SKILL／README／流程状态行都写 13）。
#   特征从《任务规则表》**全文**抽，与 `gate_check.GATE_ITEMS` 的别名匹配同一套思路。
#
# ⚠️ 与 `build_paradigm` 校验的关系：它比对活骨架时用的是 `DUMMY_RULES`（中性文本，
#   不含任何特征词）→ 条件章节**不会**进它比对的清单 → **无需改 SKELETON_HEADS，校验照旧绿**。
#   但**填写指引仍要写进 `paradigm_data.GUIDE`**，否则模型不知道怎么填。
TRAIT_PATTERNS = [
    ("多门店",   ["门店", "连锁", "分店", "加盟", "经销", "代理", "铺货", "终端", "督导"]),
    ("直播",     ["直播", "自播", "达播", "主播", "直播间", "排品", "憋单"]),
    ("本地生活", ["美团", "点评", "团购", "到店", "核销", "本地生活", "门店地址"]),
]


def probe_traits(rules):
    """从《任务规则表》**全文**抽客户特征。只读文本，不改门禁、不改档位。

    ⚠️ 2026-09-19 起多一个**动态特征**：`受监管行业` —— 它的关键词表在
    `industry_rules.INDUSTRIES`（12 类），命中即置位；它注入的章节**内容随行业不同**，
    所以不放进 `TRAIT_SECTIONS`（那是静态串），改由 `scene_body` 动态渲染。
    """
    if not isinstance(rules, dict):
        return []
    blob = json.dumps(rules, ensure_ascii=False)
    out = [name for name, kws in TRAIT_PATTERNS if any(k in blob for k in kws)]
    if _IND and detect_industry(rules):
        out.append("受监管行业")
    return out


def _industry_blob(rules):
    """行业判定只看**决定性字段**，不看整份 JSON。

    ⚠️ 2026-09-19 实测教训：一开始拿整份规则表做关键词计数 ——
    把一份 **SaaS** 客户的表（其余字段留着示例模板里的「茶饮」字样）喂进来，
    照样判成「餐饮食品」并注入一节**错的**行业规定。
    比「漏判」更坏的是「错判」：错的那一节会让填稿的人去核不相关的资质。
    → 只取「客户名 ＋ 卖什么 ＋ 卖给谁 ＋ 卡在哪 ＋ 显式行业」——
      这五项在任何一份表里都是**本案专属**的，模板残留影响不到。
    """
    if not isinstance(rules, dict):
        return ""
    parts = [str(rules.get("client") or rules.get("客户") or "")]
    g = rules.get("gate") or rules.get("门禁") or {}
    if isinstance(g, dict):
        for k, v in g.items():
            if any(t in str(k) for t in ("卖什么", "卖给谁", "行业", "品类", "主营",
                                         "卡在哪", "卡点", "卖给谁")):
                parts.append(str(v))
    for k in ("governance", "治理", "治理块"):
        v = rules.get(k)
        if isinstance(v, dict):
            parts.append(str(v.get("客户行业") or ""))
    return " ".join(parts)


def detect_industry(rules):
    """回 `industry_rules` 的行业 key（无命中或模块缺失则 None）。

    ⚠️ **门禁里的「客户行业」优先**（`explicit_from`），关键词计数只是回退 ——
    理由见 `industry_rules.detect` 与 `_industry_blob` 的说明（实测医美客户会被模板里
    残留的「茶饮」带走、SaaS 客户被判成餐饮）。
    所以 `gate_check.py` 把「客户行业」「已持资质」列成**补充项**：
    门禁 13 项是不变式，但这两项填了，行业判定就从「猜」变成「读」。
    """
    if not _IND or not isinstance(rules, dict):
        return None
    try:
        return _IND.detect(_industry_blob(rules), explicit=_IND.explicit_from(rules))
    except Exception:
        return None


# 每个特征对应的**必挂章节**。`{FILL}` 与 SCENE_SECTIONS 同一约定（由 scene_body 替换）。
TRAIT_SECTIONS = {
    # ── 多门店／连锁：总部—区域—门店的权责、稽核、培训、对加盟商的账 ──
    #    ⚠️ 标题**故意与 `SKELETON_HEADS["标准"]` 里那四个完全一致**（「十一·四 · 总部与门店的权责」
    #       「11.4.1 稽核表」「11.4.2 培训与物料下发」「14.1 对门店／加盟商的账」）——
    #       这样标准档已经有的会被 `_drop_existing()` 跳过（不重复、不动标准档骨架），
    #       B端／G端／投标 缺的才会被注入。**一套名字，一个真相。**
    "多门店": (
        "## 十一·四 · 总部与门店的权责\n"
        "| 事项 | 总部定 | 区域定 | 门店定 | 必须统一 | 可本地调 |\n|---|---|---|---|---|---|\n"
        "| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        "> 「必须统一」「可本地调」**各 ≥8 条**，每条写检查方式与越界后果 ——\n"
        "> 抽一家店能逐条打勾，才算可复制到 300 家店不走样。\n\n"
        "## 11.4.1 稽核表\n"
        "| 检查项 | 频率 | 抽查比例 | 合格线 | **谁查（岗位）** | **查完报给谁** | 不合格处置 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | 限期整改／扣保证金／停供物料 |\n\n"
        "> **没有「谁查」＝没有守门人** —— 处置必须分级写全：**罚**（扣保证金）／\n"
        "> **改**（限期整改）／**换**（换店长、停合作）。只写「加强检查」等于没写。\n\n"
        "## 11.4.2 培训与物料下发\n"
        "| 对象 | 课时 | 形式 | **谁培训** | 考核合格线 | **不合格处置** | 物料 | 安装责任（谁装／几号前） | 损耗与补货 | 到店截止日 | 签收人 |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|\n"
        "| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | 当日补考／跟班／不上活动 | {FILL} | {FILL} | 损坏谁赔／补货周期 | {FILL} | {FILL} |\n\n"
        "> 培训讲师要写到“谁”（内部讲师／供应商／外部机构），**不合格的人当天怎么补、二次不过怎么处理**\n"
        "> 必须成文 —— 否则「培训过了」这句话没人能验证。\n\n"
        "## 14.1 对门店／加盟商的账\n"
        "| 单店投入 | 月均增量毛利 | 回本月数 | LTV/CAC | **试点选择标准** | **首批家数** | **首批额外激励** | **试点期** | **成功判据** | **复制节奏** |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
        "| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | 第 {FILL} 周铺开 |\n\n"
        "> **他不配合，是因为你没算给他看。** 账要算到「他多做什么 → 多拿多少」。\n"
        "> 并且必须回答：**先让哪 10 家动、给它们什么额外好处、用它们的数据说服剩下的人。**\n"
        f"> 回本警戒线（**全仓只许有一个数**，来自 `_common.py` 的常量）："
        f"**单店投入**回本 ≤{_C.PAYBACK_WARN_STORE} 个月；**品牌投放**（收回 CAC）≤{_C.PAYBACK_WARN_AD} 个月。\n"
        f"> 两者**不是一个口径**，不要合成一个数（一个是「开店多少钱多久回」，一个是「获客多少钱多久回」）。\n\n"
    ),
    # ── 直播：排品与话术循环（**全仓原先零命中**）──
    "直播": (
        "## 十·三 · 直播排品与话术循环（**有直播间必挂**）\n"
        "| SKU | 角色（引流／利润／福利） | 价格带 | 上架时段 | 憋单-放价时点 | 每 30 秒留人动作 | 逼单合规禁用动作 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| {FILL} | 引流款 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        "| {FILL} | 利润款 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n"
        "| {FILL} | 福利款 | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        "> **三种角色各 ≥1 行，缺一即不完整**（只有引流款＝不赚钱；只有利润款＝不进人）。\n"
        "> 「逼单合规禁用动作」必须写具体行为（如「不承诺全网最低」「不诱导未成年人下单」），\n"
        "> 不要写「注意合规」。\n\n"
        "- **循环脚本一句话**（把直播从「随机聊」变成有节奏的循环）：{FILL}\n"
        "- **场控时间表**：{FILL}\n"
        "- **主播口播示范**（写**真实口播原文**，不是「生动有感染力」这类描述）：{FILL}\n"
        "- **直播间搭建要点**：{FILL}\n\n"
    ),
    # ── 本地生活：到店链路 ──
    "本地生活": (
        "## 十·四 · 本地生活到店链路（**有线下门店必挂**）\n"
        "| 团购 SKU | 门店页卖点 | 定价 | 让利 | 平台佣金 | 履约成本 | **核销成本合计** | 上架时间 |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} | {FILL} |\n\n"
        "> **核销成本合计 ＝ 套餐让利 ＋ 平台佣金 ＋ 履约成本** —— 不把这笔算出来，\n"
        "> 团购就是「卖得越多亏得越多」。\n\n"
        "- **评分与评价运营**：当前评分 {FILL} ／ 目标 {FILL}（维持 ≥4.6 为宜）／\n"
        "  差评首响时限 {FILL} 小时内 ／ 谁盯：{FILL}\n"
        "- **POI 与地图**：门店地址与坐标已校验 {FILL} ／ 营业时间 {FILL} ／ 电话 {FILL}\n"
        "- **探店视频**：拍几条 {FILL} ／ 挂什么转化组件 {FILL}\n"
        "- **核销承接（到店后怎么进私域）**：{FILL}\n\n"
    ),
}


def _norm_head(s):
    """标题归一化：去掉加粗、括注、空白 —— 只留下「说的是哪一节」。

    ⚠️ 必须有它：标准档的实际标题是「11.4.1 稽核表（**没人查＝没人做**）」，
    而 `SKELETON_HEADS` 声明的是「11.4.1 稽核表」。**精确比对只能中 1/4**
    （实测：4 个标题里 3 个带括注）→ 去重会失效、标准档凭空多出 3 节。
    """
    s = re.sub(r"\*\*", "", s)
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    return re.sub(r"\s+", "", s)


def _drop_existing(block, base):
    """把 `block` 里**归一化标题已在 base 出现**的节整节丢掉 —— 避免条件章节与场景章节重复。

    为什么需要它：多门店那一组**故意复用了标准档已有的 4 个标题**（一套名字，一个真相）。
    标准档本来就带这 4 节 → 全部丢掉、标准档骨架零变化（`build_paradigm` 的校验不受影响）；
    B端／G端／投标 本来没有 → 全部留下、补上缺的章。
    """
    if not base.strip():
        return block
    base_heads = {_norm_head(h) for h in re.findall(r"(?m)^#{2,3}\s+(.*\S)\s*$", base)}
    out, keep = [], True
    for line in block.split("\n"):
        m = re.match(r"^(#{2,3})\s+(.*\S)\s*$", line)
        if m:
            keep = _norm_head(m.group(2)) not in base_heads
        if keep:
            out.append(line)
    return "\n".join(out)


def scene_body(scene, client="", traits=(), industry=None):
    """按交付场景返回「这一类方案必须有的章节」。

    没有这些章节，方案就是**不完整**的 —— 跟打法写得好不好无关。

    ⚠️ 2026-09-19 起多一个 `traits` 维度：**能力按客户特征触发，不再按档位分配**。
    理由见 `TRAIT_SECTIONS` 上方的注释（连锁客户被判进 B 端档会拿不到稽核表）。
    `industry`（受监管行业 key）用于动态渲染 `3.5 行业资质与宣称边界`。
    """
    # ⚠️ SCENE_SECTIONS 是普通字符串（不是 f-string），`{FILL}` 是**字面占位符**，
    #    必须在这里换成真的 `【填】` —— 否则交付稿里会出现 `{FILL}` 这种鬼东西。
    base = SCENE_SECTIONS.get(scene, SCENE_SECTIONS["B端"]).replace("{FILL}", FILL)
    extra = "".join(_drop_existing(TRAIT_SECTIONS[t].replace("{FILL}", FILL), base)
                    for t, _kws in TRAIT_PATTERNS if t in traits)
    # 受监管行业：内容随行业变化，所以走动态渲染（不放进 TRAIT_SECTIONS 的静态串）。
    # ⚠️ 只判「有没有命中受监管行业」，**不判是哪个行业** —— 长尾行业也注入 GENERIC 版
    #    （「先去核资质」这件事对所有客户都成立，只是受监管行业更需要）。
    if "受监管行业" in traits and _IND:
        try:
            extra += _drop_existing(_IND.section(industry).replace("{FILL}", FILL), base)
        except Exception as e:
            # ⛔ **不静默**（optimize_scan 会抓 `except: pass`）：行业章节渲染失败必须说出来，
            #    否则调用方看到的是「这一档没有 3.5」＝「这是普通行业」，而事实是**渲染炸了**。
            print(f"{WARN} 行业资质章节渲染失败（{type(e).__name__}: {e}）—— "
                  f"本档缺 3.5 行业资质与宣称边界，selfcheck【30】会报；"
                  f"检查 scripts/industry_rules.py 的 section()")
    return base + extra


# ─────────────────────────────────────────────────────────────
# 5b. 内部文件（2026-09-17 新增）
#     交付稿要「干净可直接提交」，但施工说明／知识库缺口／自检单**不能丢** ——
#     那就另开一份文件：只有执行 AI 与维护者看，永远不进 .docx。
# ─────────────────────────────────────────────────────────────
FAILURE_LIB = os.path.join(REF, "04-失败归因总库.md")


def parse_premortem(path=FAILURE_LIB):
    """解析 `04-失败归因总库.md` 第三部分「接案时的失败预演清单（34 条）」。
    回传 [(num:int, text:str, is_star:bool)]。"""
    if not os.path.exists(path):
        return []
    t = read(path)
    m = re.search(r"# 第三部分：接案时的「失败预演」清单.*?(?=\n# 第四部分)", t, re.S)
    if not m:
        return []
    out, cur = [], ""
    for ln in m.group(0).split("\n"):
        mm = re.match(r"^(\d+)\.\s*(\*\s*)?(.*)$", ln.strip())
        if mm:
            if cur:
                out.append(cur)
            cur = [int(mm.group(1)), mm.group(3), bool(mm.group(2))]
        elif cur and ln.strip() and not ln.strip().startswith("##"):
            cur[1] += " " + ln.strip()
    if cur:
        out.append(cur)
    return out


def premortem_for(client, n=8):
    """从 34 条里选 n 条最相关的：★ 优先，其次按 bigram 与客户状况的重叠度。"""
    items = parse_premortem()
    if not items:
        return []
    cb = bigrams(client)
    starred = [it for it in items if it[2]]
    rest = [it for it in items if not it[2]]
    rest.sort(key=lambda it: -len(bigrams(it[1]) & cb))
    return starred + rest[: max(0, n - len(starred))]


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
    """施工说明 ＋ 知识库缺口 ＋ 自检单 —— **不进交付稿**。`--internal` 输出。"""
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
        f"3. 知识库已全仓统一简体（2026-09-18），注入内容正常不会有繁体；",
        f"若出现，多半是外部粘贴 —— selfcheck 会按繁体字数卡（>15 种＝硬错误）。\n",
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
        lines.append(f"> ① 去 `references/cases/{ind or '（本行业档）'}` 的「案例清单」"
                     f"挑 1–2 张，把「品牌＋做了什么＋结果」抄进骨架；\n")
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

    # 2026-09-17：**失败预演**（`04-失败归因总库.md` 第三部分 34 条）。本仓库曾
    #   「46,010 字的库零消费」（promise_check 实测）—— 因为没有任何脚本真的读它。
    #   贝恩 agent 指出后接入：按客户状况选出最相关的若干条，供执行 AI 填 8.7 Red Team 用。
    _pm_items = premortem_for(" ".join(str(v) for v in rules.get("gate", {}).values()), n=8)
    if _pm_items:
        lines.append("\n## 五之二 · 接案前失败预演（来自 04 的 34 条，已按本案筛选）\n")
        lines.append("> 用来填交付稿的「8.7 这个方案最可能怎么死」。**只进内部文件**，\n"
                     "> 交付稿里写根因白话，**不写「模式 NN」**（selfcheck 第【10】关会拦）。\n")
        for num, txt, star in _pm_items:
            mark = "（★重点）" if star else ""
            lines.append(f"- **预演 {num}{mark}**：{_t2s_light(txt)}\n")

    # 2026-09-17：范式库（六档骨架＋逐节指引）。用户原话「每一个都需要有一个范式…
    #   不仅只有大纲，也需要有里面的内容可以参考」。
    #   ⚠️ 指引只出现在这份**内部文件**里 —— 交付稿必须保持干净（selfcheck 第【10】关）。
    lines.append("\n## 六、本档填写指引（范式库 · 逐节）\n")
    lines.append(f"> 档位 `{tier}` 的骨架共 {len(_PD.SKELETON_HEADS.get(tier, []))} 节，"
                 f"逐节指引如下。完整版（含全部六档）见 `references/12-范式库.md`。\n")
    lines.append(f"> ⛔ 这些是**给你看的**：照它填 `【填】`，但**一个字都不要抄进交付稿**。\n\n")
    _miss = 0
    for _h, _g in _PD.guides_for_tier(tier):
        lines.append(f"**{_h}**\n")
        if not _g:
            _miss += 1
            lines.append("- ⚠️ 本节暂无指引（范式库缺口）\n")
            continue
        lines.append(f"- 该写什么：{_g['what']}\n")
        lines.append(f"- 写几句：{_g['size']}\n")
        lines.append(f"- 必须含：{_g['must']}\n")
        for _x in (_g.get("lines") or []):
            lines.append(f"  - 句片段：{_x}\n")
        lines.append("\n")
    if _miss:
        lines.append(f"\n> ⚠️ 本档有 {_miss} 节缺指引，请补 `scripts/paradigm_data.py`。\n")
    return "\n".join(lines)


def _dump(path, text):
    """写档（自动建父目录）—— 免去「目录不存在」这类低级失败。"""
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
    ap.add_argument("--tier", default="标准",
                    choices=["速览", "标准", "大赛", "B端", "G端", "投标"],
                    help="交付档位＝骨架形态：速览=轻量快览（1–2 页，只留决策要素，可快速阅览）＝小客户／快速预览标准；"
                         "标准=完整八章＋B端场景章；大赛／B端／G端／投标=完整八章＋该场景专属章节。"
                         "即「不同档位给不同骨架」，现有骨架本身即各类型客户（含小企业／大客户）的标准。")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--scene", default="", choices=["标准", "大赛", "B端", "G端", "投标"],
                    help="交付场景章（标准=C端品牌／大赛／B端商业／G端政府／投标）。"
                         "一般随 --tier 自动推断；仅在 --tier 为 速览 时用来手动覆盖场景章。")
    ap.add_argument("--internal", default="",
                    help="额外输出「内部施工说明」到这个路径（施工要求／知识库缺口／"
                         "打法溯源／自检单）。**这份不进交付稿**，只给执行 AI 与维护者看。")
    a = ap.parse_args()
    a.top = max(3, min(7, a.top))   # 打法数锁在 3–7（与 SKILL「3–7 条为宜」一致）

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
        print(f"{WARN} 规则表缺少 gate（门禁内容）—— 打法匹配将退化成盲选；建议先跑 gate_check.py")
    elif sum(len(str(v)) for v in gate.values()) < 40:
        print(f"{WARN} gate 内容过短（<40 字）—— 匹配会不准，建议把门禁 13 项的客户状况补足")

    cardpoints = infer_cardpoints(gate)
    picked = select_plays(plays, rules.get("gate", {}), kmap, a.top, cardpoints)
    md = build_skeleton(rules, picked, kmap, a.tier, cardpoints, a.scene)
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

    _sc = a.scene or {"标准": "标准", "大赛": "大赛", "B端": "B端", "G端": "G端", "投标": "投标"}.get(a.tier, "标准")
    print(f"   档位：{a.tier} ｜ 场景：{_sc} ｜ 识别卡点：{'／'.join(cardpoints)} ｜ 注入打法 {len(picked)} 条")
    for i, p in enumerate(picked):
        print(f"   {i+1}. {_t2s_light(p['name'])}")
    print("   → 下一步：模型只填【填】处；再跑 run_pipeline 出稿。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ composer 执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
