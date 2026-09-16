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
    ov = None
    for key in kmap["play_overrides"]:
        if key in play["name"]:
            ov = kmap["play_overrides"][key]
            break
    major = kmap["major_theory"].get(str(play["major"]), {})
    models = list(ov["models"]) if ov else list(major.get("models", []))[:3]
    books = list(ov["books"]) if ov else list(major.get("books", []))[:2]
    return models, books


def model_label(code):
    """用模型碼在 03 手冊裡找中文名（如 C1 → 超級符號）。找不到就只給碼。"""
    m = _M03_RE.get(code)
    return f"{m}（03 §{code}）" if m else f"（03 §{code}）"


_M03_RE = {}


def load_model_names(path):
    if not os.path.exists(path):
        return
    for mm in re.finditer(r"^###\s*([A-Ma-m]\d{1,2})[｜|·\s]+([^\n（(]+)", read(path), flags=re.M):
        _M03_RE[mm.group(1).upper()] = mm.group(2).strip()


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


def _book(b):
    """49 書籍字串 → 引用格式。容忍沒有「｜作者」的字串，不崩。"""
    parts = [x.strip() for x in b.split("｜")]
    name = parts[0]
    author = parts[1] if len(parts) > 1 else ""
    return f"{name}（{author}49）" if author else f"{name}（49）"


def infer_industry(gate, kmap):
    """從『賣什麼／品類／賣給誰』推 cases 行業檔（確定性關鍵詞匹配）。"""
    txt = " ".join(str(gate.get(k, "")) for k in ("賣什麼", "品类", "品類", "賣給誰", "行业", "行業"))
    for kw, f in kmap.get("industry_to_cases", {}).items():
        if kw in txt:
            return f
    return ""


def play_block(i, p, kmap):
    models, books = theory_for(p, kmap)
    mtxt = "、".join(model_label(c) for c in models)
    btxt = "、".join(_book(b) for b in books)
    cases = "、".join(f"`{c}`" for c in p["cases"]) or "—"
    # 逐步骤实操：每步都写清「动作 / 谁做 / 时间 / 物料·话术 / 产出」
    steps = parse_steps(p["howto"])
    if steps:
        s_lines = [
            f"  {k}. {act} ｜ 时间：{FILL} ｜ 谁做：{FILL} ｜ 物料·话术：{FILL} ｜ 产出：{out or FILL}"
            for k, (act, out) in enumerate(steps, 1)
        ]
        howto = "\n".join(s_lines)
    else:
        howto = "  1. " + FILL
    return (
        f"**打法 {i}｜{p['name']}**（打法库 §{p['id']}）\n"
        f"- **为什么用它**：{p['situation'] or FILL}\n"
        f"- **具体动作（精准到每一步）**：\n{howto}\n"
        f"- **谁做｜花多少｜多久见效**：{p['who'] or FILL}｜{p['budget'] or FILL}｜{p['period'] or FILL}\n"
        f"- **验收指标**：{p['verify'] or FILL}\n"
        f"- **可抄案例**：{cases}（展开见 2.0.1）\n"
        f"- **理论依据**：{mtxt} ＋ {btxt} ＋（打法库 §{p['id']}）\n"
    )


def build_lite(rules, plays, kmap, cardpoints, today):
    """速覽檔：給小微企業／個案「快速看懂打法」——1–2 頁，只留決策要素。"""
    client = rules.get("client", "客户")
    gate = rules.get("gate", {})
    cp = "／".join(f"{c}（{CARDPOINT_NAME.get(c, c)}）" for c in cardpoints)
    ind = infer_industry(gate, kmap)
    lines = [
        f"# {client} · 打法速覽（速覽档 · composer 组装）\n",
        f"> 給小微企業／個案：一頁看懂「該打哪幾條、怎麼打、花多少」。完整交付請改用 `--tier 标准`／`G端`。\n",
        f"> 生成 {today} ｜ 打法匹配自 `00-打法库 §0 总表`\n\n",
        f"## 一、卡点一句话\n- 问题类型：**{cp}**\n- 真正的卡点：{FILL}（不是 X —— 是 Y）\n\n",
        f"## 二、建议打法（{len(plays)} 条）\n",
    ]
    for i, p in enumerate(plays, 1):
        models, books = theory_for(p, kmap)
        steps = parse_steps(p["howto"])[:3]
        s = "；".join(f"{k}) {a}" for k, (a, _) in enumerate(steps, 1))
        lines.append(
            f"**{i}. {p['name']}**（打法库 §{p['id']}）—— {p['situation']}\n"
            f"- 怎么打：{s or FILL}\n"
            f"- 谁做｜花多少｜多久见效：{p['who'] or FILL}｜{p['budget'] or FILL}｜{p['period'] or FILL}\n"
            f"- 理论依据：{'、'.join(model_label(c) for c in models)} ＋ "
            f"{'、'.join(_book(b) for b in books)} ＋（打法库 §{p['id']}）\n"
        )
    lines += [
        f"\n## 三、预算量级\n{FILL}（各条打法预算相加；含盈虧線）\n\n",
        f"## 四、下一步（只写一件）\n{FILL}\n",
    ]
    if ind:
        lines.insert(3, f"> 同类行业案例库：`references/cases/{ind}.md`（先读第一节清单）\n")
    return "\n".join(lines)


def build_skeleton(rules, plays, kmap, tier, cardpoints):
    client = rules.get("client", "客户")
    gate = rules.get("gate", {})
    today = datetime.date.today().isoformat()
    cp = "／".join(f"{c}（{CARDPOINT_NAME.get(c, c)}）" for c in cardpoints)

    if tier == "速览":
        return build_lite(rules, plays, kmap, cardpoints, today)

    head = (
        f"# {client} · 营销方案（composer 骨架 · {tier}档）\n\n"
        f"> 本骨架由 `composer.py` 机械组装：**打法／理论依据／可抄案例均来自知识库，请勿删改**；"
        f"你只需补 `{FILL}` 处数字与本地化描述。\n"
        f"> ⚠️ 注入的 00/03/49 原文为繁体，且可能含个别广告法禁用词；交付前请**本地化为简体**并逐字对照禁用词表。\n"
        f"> 生成 {today} ｜ 档位 {tier} ｜ 打法匹配自 `00-打法库 §0 总表`（SKILL.md §二 路由表驱动）\n"
        + (f"> 同类行业案例库：`references/cases/{infer_industry(gate, kmap)}.md`（先读第一节清单）\n"
           if infer_industry(gate, kmap) else "")
        + "\n"
        f"## 执行摘要（TL;DR）\n- 目标：{FILL}\n- 主线一句话：{FILL}\n"
        f"- 核心打法：{'、'.join(p['name'] for p in plays)}\n"
        f"- 预期 KPI：{FILL}\n- 盈亏线：{FILL}\n\n"
    )

    diagnosis = (
        f"## 一 · 现状分析\n### 1.1 问题类型与目标\n"
        f"- 问题类型：**{cp}**（A–H 分类见 SKILL.md 第 2 步）\n"
        f"- 生意目标：{FILL}\n\n### 1.2 真正的卡点\n"
        f"> {FILL}：不是 X —— 是 Y\n\n### 1.3 已排除的假设\n{FILL}\n\n"
        f"### 1.4 竞争与关联品牌扫描\n- 头号对手（按业务环节全链条拆：获客→信任→成交→履约→复购）：{FILL}\n"
        f"- 其他对手逐个：{FILL}\n- 核心差异点一句话：{FILL}\n\n"
        f"### 1.5 约束与风险底线\n{FILL}\n\n"
    )

    strategy = "## 二 · 策略\n### 2.0 打法组合（核心）\n\n"
    strategy += "".join(play_block(i + 1, p, kmap) + "\n" for i, p in enumerate(plays))
    strategy += "### 2.0.1 可抄案例（别人是怎么做的）\n"
    for i, p in enumerate(plays):
        strategy += f"- **打法 {i+1}（{p['name']}）**：来源 {('、'.join('`'+c+'`' for c in p['cases']) or FILL)}，请展开「他面对什么问题／具体做了什么／结果／我们怎么用」\n"
    strategy += (
        f"\n### 2.1 三次收窄（时间／人群／动作）\n{FILL}\n\n"
        f"### 2.2 货盘与机制\n{FILL}\n\n"
    )

    positioning = (
        "## 三 · 定位与口径\n### 3.1 定位与差异化支点\n"
        f"- 定位语（一句话）：{FILL}\n"
        f"- 学理依据：{'、'.join(model_label(c) for c in ['B5', 'C1'])}、{kmap['major_theory']['1']['books'][0].split('｜')[0]}（{kmap['major_theory']['1']['books'][0].split('｜')[1] if '｜' in kmap['major_theory']['1']['books'][0] else ''}49）—— 说明用在定位的哪一步\n"
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
        f"### 8.3 风险清单（每条挂「模式 NN」＋四件套：排序理由/预警信号/兜底预案/预防动作）\n{FILL}\n\n"
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

    appendix = (
        "## 附件 · 交付自检单（12 项，逐项 ✅/❌）\n"
        "| # | 自检项 | 结果 |\n|---|---|---|\n"
        "| 1 | 门禁 13 项已问全（含目标字数）并写入《任务规则表》 | 【填】 |\n"
        "| 2 | 未经验证的假设已在文首单独标注 | 【填】 |\n"
        "| 3 | 文档结构完整（八篇＋附件） | 【填】 |\n"
        "| 4 | 字数达标（任务规则表确认） | 【填】 |\n"
        "| 5 | 每条打法五要素（做什么/谁/何时/花多少/怎么验收） | ✅（composer 注入） |\n"
        "| 6 | 禁用词与口径章节存在，物料文案已逐字对照 | 【填】 |\n"
        "| 7 | 预算分项加总＝合计；引用数字全部有来源 | 【填】 |\n"
        "| 8 | KPI 可测（基准值＋观测方式）＋决策节奏已写 | 【填】 |\n"
        "| 9 | 执行人力检查＋删减顺序已写 | 【填】 |\n"
        "| 10 | 关键假设＋验证＋Plan B 已写 | 【填】 |\n"
        "| 11 | 无内部过程文档泄漏 | 【填】 |\n"
        "| 12 | 交付回复中已附本自检单 | 【填】 |\n"
    )

    body = head + diagnosis + strategy + positioning + reach + copy_ + kpi + budget + exec_ + g_extra + appendix
    return body


# ─────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tier", default="标准", choices=["速览", "标准", "G端"])
    ap.add_argument("--top", type=int, default=5)
    a = ap.parse_args()

    if not os.path.exists(a.rules):
        print(f"❌ 找不到规则表：{a.rules}")
        sys.exit(1)
    rules = json.loads(read(a.rules))
    kmap = json.loads(read(KMAP))
    load_model_names(os.path.join(REF, "03-方法论操作手册.md"))
    plays = parse_playbook(read(PLAYBOOK))
    if not plays:
        print("❌ 解析 00-打法库 失败（0 条打法）")
        sys.exit(2)

    cardpoints = infer_cardpoints(rules.get("gate", {}))
    picked = select_plays(plays, rules.get("gate", {}), kmap, a.top, cardpoints)
    md = build_skeleton(rules, picked, kmap, a.tier, cardpoints)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"✅ 已生成骨架：{a.out}")
    print(f"   档位：{a.tier} ｜ 识别卡点：{'／'.join(cardpoints)} ｜ 注入打法 {len(picked)} 条")
    for i, p in enumerate(picked):
        print(f"   {i+1}. {p['name']}（§{p['id']}·{p['major']}类）")
    print("   → 下一步：模型只填【填】处；再跑 run_pipeline 出稿。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ composer 执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
