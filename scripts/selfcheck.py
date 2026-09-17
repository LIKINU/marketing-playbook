#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交付前自檢 · selfcheck.py  （marketing-playbook 協議 3）

用途：宣告交付前跑一次。機械校驗「方案是否具備硬要素」。
      有 ❌ → 不准交付，修正後重跑。

用法：
    python selfcheck.py plan.md
    python selfcheck.py plan.md --banned banned.json      # 自訂禁用詞表
    python selfcheck.py plan.md --quiet                   # 只輸出結論

退出碼：0 = 全部通過；1 = 有硬錯誤（必須修）
判斷分三級：
    ❌ 硬錯誤 → 退出碼 1，必須修
    ⚠️ 警告   → 需人工確認（不影響退出碼）
    ✅ 通過
"""

import json
import os
import re
import sys

from _common import (OK, NG, WARN, HINT, INFO, VAGUE_WORDS, AI_SMELL_WORDS,
                     CAUSAL_WORDS, GENERIC_CATEGORY_WORDS,
                     CONCRETE_ACTION_WORDS, CONCRETE_OBJECT_WORDS)   # noqa: E402

# 繁→简单字表（与 composer 共用 `scripts/t2s_data.py`，机械生成、零依赖）
def _load_t2s():
    try:
        _here = os.path.dirname(os.path.abspath(__file__))
        if _here not in sys.path:
            sys.path.insert(0, _here)
        from t2s_data import T2S_PAIRS as _P
        return {_P[i]: _P[i + 1] for i in range(0, len(_P) - 1, 2)}
    except Exception:
        return {}


_T2S_MAP = _load_t2s()

# 結構清單（關鍵詞寬鬆匹配，命中任一即可）
# 三元組 = (名稱, 關鍵詞, 是否僅「完整版」需要)
#   —— 用戶定調（2026-09-14）：交付結構由用戶選（**精煉版**／**完整版**）
#      精煉版 = 終稿只放能執行的，**分析類內容（現狀／競品）留支撐稿** → 故標 True（可省）
SECTIONS = [
    ("執行摘要", ["執行摘要", "执行摘要", "TL;DR", "核心結論", "核心结论"], False),
    ("一 · 現狀分析", ["現狀分析", "现状分析", "生意現狀", "生意现状", "問題診斷", "问题诊断"], True),
    ("二 · 策略", ["策略", "方案成立的前提", "節奏排期", "节奏排期", "貨盤", "货盘"], False),
    ("三 · 定位與口徑", ["定位", "禁用詞", "禁用词", "口徑", "口径", "差異化支點", "差异化支点"], False),
    ("四 · 觸達與渠道", ["觸達", "触达", "渠道", "投放", "傳播路徑", "传播路径"], False),
    ("五 · 落地文案與物料", ["落地文案", "文案", "物料", "話術", "话术"], False),
    ("六 · KPI 與追蹤", ["KPI", "追蹤", "追踪", "指標", "指标", "監測", "监测"], False),
    ("七 · 預算明細", ["預算明細", "预算明细", "預算表", "预算表", "盈虧線", "盈亏线"], False),
    ("八 · 執行與風控", ["執行與風控", "执行与风控", "行動清單", "行动清单", "風險", "风险", "關鍵假設", "关键假设"], False),
]

# 內部過程文檔關鍵詞 —— 硬錯誤（真正「怎麼幹活」的內部術語，不該出現在給客戶的稿裡）
INTERNAL_LEAK_HARD = [
    "多 Agent", "多Agent", "Agent 分工", "Agent分工", "內部備註", "内部备注",
]
# 軟警告 —— 這些詞在合規稿件裡會**合法**出現，只提示人工確認：
#  ·「門禁／流程狀態」→ 交付自檢單裡會寫（如「門禁 13 項已問全」）
#  ·「裁決記錄／主理人裁決」→ 12 項自檢單第 12 條明文要求「裁決記錄與產出索引」，
#     且**保留反對意見的裁決痕跡是質量特徵**（羅森案原版就有「主理人對 5 處衝突的裁決」）
#  ·「事實底稿」→ 精煉版的「支撐稿索引」裡會提到它（分析類內容在那裡）
INTERNAL_LEAK_SOFT = [
    "門禁", "门禁", "流程狀態", "流程状态",
    "裁決記錄", "裁决记录", "主理人裁決", "主理人裁决",
    "事實底稿", "事实底稿",
]

# 預設禁用詞（行銷常見違規／高風險）
BANNED_DEFAULT = [
    # 絕對化用語
    "最好", "最佳", "最便宜", "最低價", "最強", "第一品牌", "國家級", "国家级",
    "唯一", "獨一無二", "独一无二", "極致", "极致", "頂級", "顶级", "最優", "最优",
    "100%有效", "100%見效", "百分百有效",
    # 功效／醫療
    "治療", "治疗", "治癒", "治愈", "根治", "痊癒", "痊愈", "包治", "無副作用", "无副作用",
    "藥到病除", "药到病除", "特效",
    # 金融 —— 注意：單獨的「保本」不算（「保本單量／保本點／保本線」是財務術語），
    #        只有「保本理財／保本收益」這種組合才是違規表述
    "保本收益", "保本理財", "保本理财", "保收益", "穩賺", "稳赚",
    "零風險", "零风险", "穩賺不賠", "稳赚不赔",
]
# ⛔ 硬錯誤級違規詞（2026-09-17 新增，R2 合規視角第 1 條）：
#    「疑似違規用語」原本**全部只判警告** —— 而廣告法第九條絕對化用語、化妝品醫療功效宣稱
#    是**罰款級紅線**，跟「建議補案例」同級是不對的。這裡把它們升為硬錯誤。
#    另外原表缺了美妝高頻違規詞（祛痘／美白／藥妝／醫美級… ）—— 一併補上。
BANNED_HARD = [
    # 廣告法第九條：絕對化用語
    "最好", "最佳", "最便宜", "最低價", "最低价", "最強", "最强", "第一品牌", "銷量第一",
    "销量第一", "國家級", "国家级", "國家級產品", "唯一", "獨一無二", "独一无二", "極致",
    "极致", "頂級", "顶级", "最優", "最优", "史上最", "絕無僅有", "绝无仅有", "首選",
    "首选", "領導品牌", "领导品牌", "馳名商標", "驰名商标", "100%有效", "100%見效",
    "百分百有效", "百分百見效", "全網最低", "全网最低",
    # 化妝品醫療功效宣稱（普通化妝品不得宣稱醫療功效）
    "治療", "治疗", "治癒", "治愈", "根治", "痊癒", "痊愈", "包治", "藥到病除", "药到病除",
    "特效", "療效", "疗效", "消炎", "殺菌", "杀菌", "抗菌", "除菌", "抗敏", "祛疤", "生髮",
    "生发", "豐胸", "丰胸", "減肥", "减肥", "溶脂", "藥妝", "药妆", "醫美級", "医美级",
    "醫學護膚品", "医学护肤品", "速效", "一洗白", "永久", "無副作用", "无副作用",
    # 美妝常見違規宣稱（R2 補）
    "祛痘", "祛斑", "美白", "去黑眼圈", "祛眼袋", "抗皺", "抗皱", "除蟎", "除螨", "脫敏",
    "脱敏", "激素", "排毒",
]

# 允許出現在「禁用詞表」章節內（那是在說「不能說」）
#    ⚠️ 2026-09-17 收窄（R2 合規視角第 3 條）：原表含「不得／禁止」——
#       那是正常公文高頻詞（「價格不得低於」），命中就挖掉**前後各 2 行**，
#       會讓附近真正的違規詞合法逃逸（系統性盲區）。改為只認「明確在講禁用詞表」的標記，
#       且豁免範圍從 ±2 行收到 ±1 行。
BANNED_CONTEXT_SAFE = ["禁用詞", "禁用词", "不能說", "不能说", "紅線詞", "红线词"]

# 財務／統計語境白名單：命中則從掃描文本挖掉
# （例：「保本單量」是財務術語，不是金融產品的「保本」承諾 —— 不豁免會一直誤報）
BANNED_WHITELIST_PATTERNS = [
    r"保本(單量|销量|銷量|點|点|線|线|值|門檻|门槛|测算|測算|單數|单数|分析)",
    r"回本(週期|周期|單量|销量|銷量|點|点|時間|时间|線|线)",
]


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def emit_json(hard, warns, code):
    """--json：給 CI／自動化消費的結構化輸出（優化項 2026-09-16）。"""
    if "--json" in sys.argv:
        print(json.dumps({"exit": code, "hard_errors": hard, "warnings": warns}, ensure_ascii=False))


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("用法: python selfcheck.py <plan.md> [--banned banned.json] [--quiet] [--json]")
        print("  退出碼 0=全過（可交付）｜1=有硬錯誤（不得交付）｜2=腳本出錯")
        sys.exit(0)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    quiet = "--quiet" in sys.argv
    if not args:
        print("用法: python selfcheck.py <plan.md> [--banned banned.json] [--quiet]")
        sys.exit(1)
    path = args[0]

    banned = list(BANNED_DEFAULT)
    if "--banned" in sys.argv:
        i = sys.argv.index("--banned")
        try:
            with open(sys.argv[i + 1], "r", encoding="utf-8") as f:
                extra = json.load(f)
            banned += list(extra.get("banned", extra)) if isinstance(extra, (dict, list)) else []
        except Exception as e:
            print(f"{WARN} 讀取自訂禁用詞表失敗（用預設表繼續）：{e}")

    try:
        text = read(path)
    except Exception as e:
        print(f"{NG} 無法讀取方案檔：{e}")
        sys.exit(1)

    hard_errors, warnings = [], []

    if not quiet:
        print("=" * 64)
        print(f"交付前自檢 · {path}")
        print("=" * 64)

    # 1) 結構（支援兩種交付結構：完整版／精煉版）
    if not quiet:
        print("\n【1】文檔結構（完整版九部分；**精煉版可省「現狀分析」**）")
    body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)  # 去掉 front matter
    optional_missing = []
    for name, keys, optional_only in SECTIONS:
        hit = any(k in body for k in keys)
        if not quiet:
            mark = OK if hit else (WARN if optional_only else NG)
            extra = "（精煉版可省 —— 分析留支撐稿）" if (optional_only and not hit) else ""
            print(f"  {mark} {name}{extra}")
        if not hit:
            if optional_only:
                optional_missing.append(name)
            else:
                hard_errors.append(f"缺少「{name}」章節")
    if optional_missing:
        warnings.append(
            f"未含 {'、'.join(optional_missing)} —— 若為**精煉版**屬正常（分析放在支撐稿）；"
            f"若為完整版則需補上"
        )

    # 1a) 篇幅形狀（優化項）：太短基本是空殼（除非明確是「速覽版」）
    _chars = len(re.sub(r"\s", "", body))
    if not quiet:
        print(f"  {'✅' if _chars >= 1500 else WARN} 正文非空白字數：{_chars:,}")
    if _chars < 1500 and "速覽" not in text and "速览" not in text:
        warnings.append(f"全文僅 {_chars} 字 —— 交付稿通常遠不止此，請確認不是空殼稿")

    # 1b) composer 骨架占位符殘留 —— 硬錯誤（未填完的骨架不得交付）
    # ⚠️ 2026-09-17 改 0 容忍（R2 合規視角第 9 條）：原閾值「<3 視為已填完」——
    #    但官方「不得留空」是 **0 容忍**，且 delivery_check 的 PLACEHOLDER_HARD 早已 0 容忍，
    #    兩處口徑不一致。留 1–2 處也能過 selfcheck ＝ 把漏洞開在自檢最該嚴的地方。
    fill_cnt = len(re.findall(r"【填】", text))
    if not quiet:
        print(f"  {'✅' if fill_cnt == 0 else NG} composer 占位符【填】殘留：{fill_cnt} 處（0 容忍）")
    if fill_cnt >= 1:
        hard_errors.append(f"方案殘留 {fill_cnt} 處 composer 占位符【填】 —— 骨架未填完，不得交付"
                           f"（占位符為 0 容忍：官方「不得留空」不給額度）")

    # 2) 交付自檢單（協議 3：可寫進文檔附件，也可只在聊天回覆輸出 → 缺失僅警告，不攔）
    has_checklist = ("自檢單" in text or "自检单" in text)
    box_count = len(re.findall(r"[✅❌]", text))
    if not quiet:
        print("\n【2】交付自檢單")
        print(f"  {'✅' if has_checklist else WARN} 出現「自檢單」字樣：{has_checklist}")
        print(f"  {'✅' if box_count >= 12 else WARN} ✅/❌ 標記數量：{box_count}（建議 ≥12）")
    if not has_checklist:
        warnings.append("文檔內未含《交付自檢單》—— 協議 3 允許只在聊天回覆輸出，請確認回覆中已附")
    elif box_count < 12:
        warnings.append(f"✅/❌ 標記只有 {box_count} 個，自檢單可能沒逐項標")

    # 3) 內部過程文檔洩漏
    #    ⚠️ 注意（死結修正）：交付稿的「附件 C」按 SKILL.md §三 明文就叫「事實底稿」，
    #    所以檢查必須跳過「附件／附錄」之後的區域 —— 否則一份完全合規的稿必然被判違規，
    #    build_docx 永久拒絕出稿（強制層反而變成阻塞層）。
    if not quiet:
        print("\n【3】內部過程文檔檢查（不得出現在正文；附件區除外）")
    # 附件／附錄標題（允許行末無內容、允許「## 附件」這種寫法）
    m_appendix = re.search(r"(?m)^#{1,4}\s*(附件|附錄|附录)\s*[A-D]?\s*[:：·]?", text)
    body_scope = text[:m_appendix.start()] if m_appendix else text
    leaks = sorted({k for k in INTERNAL_LEAK_HARD if k in body_scope})
    soft_leaks = sorted({k for k in INTERNAL_LEAK_SOFT if k in body_scope})
    if leaks:
        for k in leaks:
            if not quiet:
                print(f"  {NG} 發現內部字樣：「{k}」")
        hard_errors.append(f"交付稿混入內部過程字樣：{'、'.join(leaks)}")
    if soft_leaks:
        if not quiet:
            print(f"  {WARN} 出現流程用語：{'、'.join(soft_leaks)}（自檢單裡合法；若混進正文請刪）")
        warnings.append(f"正文可能混入流程用語：{'、'.join(soft_leaks)}")
    if not leaks and not soft_leaks and not quiet:
        print(f"  {OK} 未發現內部過程字樣")

    # 4) 未核實數據
    if not quiet:
        print("\n【4】可信度標註")
    unverified = len(re.findall(r"【未核實】|【未核实】", text))
    verified = len(re.findall(r"【已核實】|【已核实】", text))
    if not quiet:
        print(f"  {'⚠️' if unverified else '✅'} 【未核實】出現 {unverified} 處（>0 需從交付物剔除）")
        print(f"  ℹ️  【已核實】出現 {verified} 處")
    if unverified:
        warnings.append(f"交付稿含 {unverified} 處【未核實】數據，對外交付前應剔除或降級表述")

    # 5) 五要素（啟發式）
    if not quiet:
        print("\n【5】動作五要素（啟發式檢查）")
    four = {
        "誰做": ["誰做", "谁做", "負責", "负责", "責任人", "责任人", "執行人", "执行人"],
        "時間": ["什麼時候", "什么时候", "排期", "第 X 週", "第 X 周", "deadline", "截止", "日起", "月前"],
        "花多少": ["花多少", "預算", "预算", "費用", "费用", "元", "¥"],
        "怎麼驗收": ["驗收", "验收", "指標", "指标", "達成", "达成", "目標值", "目标值"],
    }
    for k, keys in four.items():
        hit = any(x in text for x in keys)
        if not quiet:
            print(f"  {OK if hit else WARN} {k}")
        if not hit:
            warnings.append(f"可能缺「{k}」的描述")

    # 6) 禁用詞
    if not quiet:
        print("\n【6】禁用詞掃描（只掃描非「禁用詞說明」段落）")
    # 粗略：把含「禁用詞/不能說/紅線」的段落挖掉再掃
    lines = text.splitlines()
    safe_idx = set()
    in_code = False
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("```"):     # 圍欄程式碼塊整段排除（範例／原文不該被當違規用語）
            in_code = not in_code
            safe_idx.add(i)
            continue
        if in_code:
            safe_idx.add(i)
            continue
        if any(c in ln for c in BANNED_CONTEXT_SAFE) or ln.strip().startswith(("- 禁用", "| 禁用", "- 不能")):
            for j in range(max(0, i - 1), min(len(lines), i + 2)):   # ±1 行（原 ±2）
                safe_idx.add(j)
    scan_text = "\n".join(ln for i, ln in enumerate(lines) if i not in safe_idx)
    # 套用財務／統計語境白名單（避免「保本單量」這類術語誤報）
    for pat in BANNED_WHITELIST_PATTERNS:
        scan_text = re.sub(pat, "", scan_text)
    found = sorted({b for b in banned if b and b in scan_text})
    hard_found = sorted({b for b in BANNED_HARD if b and b in scan_text})
    if hard_found and not quiet:
        print(f"  {NG} ⛔ 硬紅線違規詞 {len(hard_found)} 個：{'、'.join(hard_found[:12])}")
    if hard_found:
        hard_errors.append(
            f"廣告法／化妝品宣稱硬紅線：{'、'.join(hard_found[:12])}"
            + ("…" if len(hard_found) > 12 else "")
            + "　→ 絕對化用語與醫療功效宣稱是罰款級紅線，改成可核查的功能性表述。")
    soft = [b for b in found if b not in hard_found]
    if soft:
        for b in soft:
            if not quiet:
                print(f"  {WARN} 疑似違規用語：「{b}」")
        warnings.append(f"疑似違規用語 {len(soft)} 個：{'、'.join(soft[:12])}"
                        + ("…" if len(soft) > 12 else ""))
    if not found and not quiet:
        print(f"  {OK} 未發現預設禁用詞")

    # 7) 核心方法論要素（2026-09-16 新增：把「好方案的三個特徵」變成機械校驗）
    #    來源：用戶以《中百羅森新生開學引流方案》為基準的糾偏——該稿的診斷／打法組合／
    #    風險自檢三章明顯優於同期產出，遂固化为硬門檻。
    if not quiet:
        print("\n【7】核心方法論要素（打法組合表／問題類型／失敗歸因編號／可抄案例）")

    # 7a 打法組合 —— 硬錯誤（形式不限：多段文字 或 表格）
    #    2026-09-16 修正：8 列寬表在 Word 裡會擠成一條豎線（用戶實測反饋），
    #    推薦「多段文字」形式 → 校驗改為看「要素標籤」而非表頭。
    combo_marks = re.findall(r"(?m)^\*\*打法\s*\d+", text)
    table_head = re.search(r"(?m)^\|[^\n]*(為什麼用它|为什么用它)[^\n]*\|", text)
    labels = {
        "为什么用它": ["為什麼用它", "为什么用它"],
        "具体动作": ["具體動作", "具体动作"],
        "谁做": ["誰做", "谁做"],
        "花多少": ["花多少"],
        "多久见效": ["多久見效", "多久见效"],
        "验收指标": ["驗收指標", "验收指标"],
        "可抄案例": ["可抄案例"],
    }
    hit = sum(1 for alts in labels.values() if any(a in text for a in alts))
    if combo_marks or table_head:
        form = "多段文字" if len(combo_marks) >= 3 else "表格"
        if not quiet:
            print(f"  {OK} 打法組合存在（{form}形式，{len(combo_marks)} 條，要素標籤 {hit}/7）")
        if hit < 6:
            if not quiet:
                print(f"  {NG} 打法要素標籤只命中 {hit}/7")
            hard_errors.append(
                f"打法組合要素不全（{hit}/7）——每條須含：為什麼用它／具體動作／誰做＋花多少＋多久見效／驗收指標／可抄案例"
            )
    else:
        if not quiet:
            print(f"  {NG} 未找到打法組合（需「**打法 N｜名稱」分段，或含「為什麼用它」的表頭）")
        hard_errors.append(
            "缺少《打法組合》——推薦多段文字：每條「**打法 N｜名稱**」下寫"
            "為什麼用它／具體動作／誰做｜花多少｜多久見效／驗收指標／可抄案例"
        )

    # 7b 問題類型 A–H 歸類 —— 警告
    mt = re.search(r"問題類型|问题类型", text)
    _type_names = ["认知", "認知", "交易", "渠道", "信任", "复购", "復購", "私域",
                   "定价", "定價", "组织", "組織", "合规", "合規"]
    # 收緊：除了「問題類型」附近有 A–H 字母，還必須真的提到某一類名（否則模型碼里的字母會誤命中）
    if mt and re.search(r"[A-H]", text[mt.start():mt.start() + 120]) and any(n in text for n in _type_names):
        if not quiet:
            print(f"  {OK} 問題類型已歸類（A–H）")
    else:
        if not quiet:
            print(f"  {WARN} 診斷未見「問題類型（A–H）」歸類")
        warnings.append("診斷缺「問題類型（A–H）」——見 SKILL.md 第 2 步分類表（認知/交易/渠道/信任/復購/定價/組織/合規）")

    # 7c 風險四件套 —— 警告
    #    2026-09-17：不再要求掛「模式 NN」編號（那是內部座標，客戶看不懂，第【10】關會攔）。
    #    改為檢查風險本身寫全了沒：為什麼會發生／預警信號／兜底預案／預防動作。
    _rk = re.search(r"^#{1,4}\s*[^\n]*[风風][险險](.*?)(?=^#{1,2}\s|\Z)", text, flags=re.S | re.M)
    _rt = _rk.group(1) if _rk else ""
    _r4 = [k for k in ("预警信号", "預警信號", "兜底预案", "兜底預案",
                       "预防动作", "預防動作", "为什么会发生", "為什麼會發生") if k in _rt]
    if _rt and len(_r4) >= 3:
        if not quiet:
            print(f"  {OK} 風險四件套已寫（{'／'.join(_r4[:4])}）")
    elif _rt:
        if not quiet:
            print(f"  {WARN} 風險只寫了 {len(_r4)}/4 件套")
        warnings.append("風險清單每條要寫全四件套：為什麼會發生／預警信號／兜底預案／預防動作"
                        "（內部可對照失敗歸因總庫，但交付稿裡**不要**寫「模式 NN」編號）")
    else:
        if not quiet:
            print(f"  {WARN} 未找到風險章節，跳過")
        warnings.append("未找到風險章節，無法校驗風險四件套")

    # 7d 可抄案例 —— **必須有品牌＋有做法＋有結果**（2026-09-17 改）
    #    舊版看的是「有沒有寫 `cases/xx.md` 路徑」，那等於鼓勵把內部路徑寫進交付稿。
    #    新版看的是**內容**：拿得出品牌名嗎？說得出結果數字嗎？
    _cms = list(re.finditer(r"可抄案例", text))
    _weak = []
    for _n, _m in enumerate(_cms, 1):
        seg = text[_m.start():_m.start() + 400]
        has_brand = bool(re.search(r"\*\*[^*]{2,24}\*\*", seg))
        has_result = bool(re.search(r"结果|結果|率|增长|增長|提升|万|萬|%|倍", seg))
        if not (has_brand and has_result):
            _weak.append(_n)
    if _cms and not _weak:
        if not quiet:
            print(f"  {OK} 可抄案例均含「品牌＋做法＋結果」（{len(_cms)} 處）")
    elif _cms:
        if not quiet:
            print(f"  {WARN} 第 {_weak} 處可抄案例缺品牌或缺結果")
        warnings.append("可抄案例要寫「**品牌** —— 他做了什麼 ▶ 結果：數字」，"
                        "只有品牌沒結果（或只有做法沒品牌）都不算可抄")
    else:
        if not quiet:
            print(f"  {WARN} 未見可抄案例段落")
        warnings.append("打法組合建議加「可抄案例」（寫清別人怎麼做的、結果如何、我們怎麼用）")

    # 7e 每條打法的「具體動作」須精準到每一步（≥3 個編號步驟）—— 硬錯誤
    #    用戶 2026-09-16：「策劃具體操作流程還是沒寫好，要詳細精準到每一步 —— 指策劃案的打法和實操」
    p_blocks = re.split(r"(?m)^\*\*打法\s*\d+", text)[1:]
    thin = [i + 1 for i, b in enumerate(p_blocks)
            if len(re.findall(r"(?m)^\s*\d+[.、]", b)) < 3]
    if p_blocks:
        if not thin:
            if not quiet:
                print(f"  {OK} 每條打法都有 ≥3 步的逐步驟實操（{len(p_blocks)} 條）")
        else:
            if not quiet:
                print(f"  {NG} 有 {len(thin)} 條打法的實操不足 3 步")
            hard_errors.append(
                f"打法 {thin} 的「具體動作」不足 3 個編號步驟 —— 每條打法須寫到「精準到每一步」"
                "（動作／誰做／時間／物料·話術／產出），不能只寫一句話"
            )

    # 8) 知識展開度（2026-09-17 **反轉**）
    #
    #    舊版**強制**交付稿掛「打法库 §X.X」「03 模型碼」「（作者49）」——結果就是客戶
    #    拿到一份滿是內部座標的稿：看不懂、也查不到。用戶原話：
    #      「不是只是引用了就行了，說有什麼理論是沒有任何意義的 —— 要寫具體的操作」
    #      「交付出來的東西應該是可以直接看的，而不是有例如像（打法库 §4.1）這樣的引用」
    #
    #    新規則：**知識必須寫成內容，座標一律不得出現**。
    #      · 8a 每條打法的「為什麼這麼做」必須是**寫開的內容**（不是編號、不是【填】）
    #      · 8b 策略篇必須真的用到 ≥3 個理論（用 03 手冊的**模型中文名**驗，不看編號）
    #      · 8c 全文 ≥1 處書籍觀點（《書名》＋主張）
    #      · 座標本身的攔截 → 第【10】關
    if not quiet:
        print("\n【8】知識展開度（理論／案例須寫成可執行內容，不得只留編號）")

    _ref_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "references")
    _m03 = os.path.join(_ref_dir, "03-方法论操作手册.md")

    # 8a 每條打法的「為什麼這麼做」必須展開成實質內容（≥25 個實字）
    _pb = re.split(r"(?m)^\*\*打法\s*\d+", text)
    if len(_pb) > 1:
        _thin = []
        for i, blk in enumerate(_pb[1:], 1):
            m = re.search(r"(?:为什么这么做|为什么這麼做|理论依据|理論依據)[^\n]*?[：:]\s*(.+)", blk)
            # ⚠️ 2026-09-17 修：這裡原本寫 `body = ...`，**覆蓋掉上面第 147 行定義的全文變數 `body`**。
            #    後果：【11】場景完整性與【13】交叉引用都變成在對「某條打法的『為什麼』那半行」
            #    做檢查 → 永遠 0 命中 → 看起來全綠，其實整關從未生效。
            #    這是典型的「校驗器自己壞掉、卻回報通過」，比沒有校驗更危險。
            _why_txt = (m.group(1) if m else "").strip()
            solid = len(re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", _why_txt))
            # ⚠️ 2026-09-17 升级：原先只看「≥25 实字」，25 字空话稳过
            #    （「因为环境不好所以要稳健推进避免风险」21 字，加几个字就满分）。
            #    So-What 测的是「答不答得出**所以呢**」，不是长度 → 改为「长度 + 至少一条实质」：
            #      ① 含数字＋单位（可核验的量化）  ② 引了品牌或《书名》（有外部依据）
            #      ③ 含因果词（讲清了机制）
            #    并且不得通篇是模糊词。
            _has_num = bool(re.search(r"\d+\s*(?:元|%|％|万|萬|天|周|週|个月|個月|次|单|單|人|店|条|條|倍|小时|小時)", _why_txt))
            _has_ref = bool(re.search(r"\*\*[^*]+\*\*|《[^》]+》", _why_txt))
            _has_cause = any(w in _why_txt for w in CAUSAL_WORDS)
            # ⚠️ 2026-09-17 调参（拿真稿验出来的）：只认「数字／引用／因果词」会**误伤**
            #    机制句 —— 实测「瞳话如果不在黄金层、没有插卡和堆头，就只是在给陈列做得
            #    更好的对手做背景」这句明明是机制说明，却因为没有「因为/所以」被误判。
            #    → 补三类同样算「讲清了机制」的句式：条件推演／对照取舍／推理链。
            _MECH = [
                r"如果[^，。]{2,20}[，,][^。]{2,}", r"若[^，。]{2,20}[，,][^。]{2,}",
                r"一旦[^，。]{2,20}[，,]", r"只要[^，。]{2,20}[，,]",
                r"越[^，。]{1,12}[，,]越", r"不是[^，。]{1,20}[，,]?而是",
                r"只有[^，。]{2,20}[，,]?才", r"与其[^，。]{2,20}[，,]?不如",
                r"而不是", r"而非", r"相比", r"→",
            ]
            _has_mech = any(re.search(p, _why_txt) for p in _MECH)
            _vague = sum(1 for w in VAGUE_WORDS if w in _why_txt)
            _solid_ok = (solid >= 25
                         and (_has_num or _has_ref or _has_cause or _has_mech)
                         and _vague <= 2)
            if not _solid_ok:
                _thin.append(i)
        if _thin:
            if not quiet:
                print(f"  {NG} 打法 {_thin} 的「為什麼這麼做」沒寫開（<25 實字）")
            hard_errors.append(
                f"打法 {_thin} 的「為什麼這麼做」不達標 —— 需同時滿足："
                "①≥25 實字 ②至少含一條實質（數字＋單位／引品牌或《書名》／因果詞／機制句「如果…就」「不是…而是」等／推理箭頭）"
                "③模糊詞（加強/提升/優化/賦能…）≤2 個。"
                "**寫得長不等於寫得清**：要答得出「所以呢」。"
            )
        else:
            if not quiet:
                print(f"  {OK} 每條打法的「為什麼這麼做」都已展開（{len(_pb)-1} 條）")
    else:
        if not quiet:
            print(f"  {WARN} 未找到「**打法 N」分段，跳過")
        warnings.append("未找到打法組合分段，無法校驗「為什麼這麼做」是否展開")

    # 8b 策略篇須真的用到 ≥3 個理論 —— 用 03 手冊的**模型中文名**比對（不認編號）
    # 03 手冊是**繁體**，交付稿已轉簡體 —— 不轉換就一個都匹配不上（实测只识别到 2 个）
    def _s2cn(x):
        return "".join(_T2S_MAP.get(c, c) for c in x)

    _names = {}
    if os.path.exists(_m03):
        try:
            for m in re.finditer(r"^###\s*([A-Ma-m]\d{1,2})[｜|·\s]+([^\n（(]+)",
                                 read(_m03), flags=re.M):
                nm = _s2cn(m.group(2).strip())
                if len(nm) >= 2:
                    _names[m.group(1).upper()] = nm
        except Exception as _e:
            # ⛔ 不能吞：这张表是 8b「策略篇须用 ≥3 个理论」的唯一依据。
            #    载入失败＝后面那条校验会拿空表去比，必然判「没用到理论」或直接跳过。
            warnings.append(f"模型名表载入失败（{type(_e).__name__}）—— 【8】的 8b 校验不可信，请检查 03 手册")
            print(f"  {WARN} 模型名表载入失败（{type(_e).__name__}）—— 8b 校验不可信")
    _ms = re.search(r"^#{1,4}\s*[^\n]*策略(.*?)(?=^#{1,2}\s*[^\n]*定位|\Z)", text, flags=re.S | re.M)
    _strat = _ms.group(1) if _ms else text
    _hit_names = sorted({nm for nm in _names.values() if nm in _strat})
    if len(_hit_names) >= 3:
        if not quiet:
            print(f"  {OK} 策略篇用到 {len(_hit_names)} 個理論（{'、'.join(_hit_names[:6])}…）")
    else:
        if not quiet:
            print(f"  {NG} 策略篇只用到 {len(_hit_names)} 個理論（需 ≥3）")
        hard_errors.append(
            f"策略篇只識別出 {len(_hit_names)} 個理論（需 ≥3）——理論要**寫進做法裡**"
            "（說清楚這套動作背後用的是什麼道理），不是列一串理論名稱"
        )

    # 8c 全文 ≥1 處書籍觀點（《書名》＋主張）；排除內部文檔名
    _block_book = ("規則表", "规则表", "自檢單", "自检单", "規則", "规则")
    _books = [b for b in re.findall(r"《[^》]{1,40}》", text) if not any(x in b for x in _block_book)]
    if _books:
        if not quiet:
            print(f"  {OK} 引用書籍觀點 {len(_books)} 處（如 {_books[0]}）")
    else:
        if not quiet:
            print(f"  {NG} 全文未見任何書籍觀點")
        hard_errors.append("未引用任何書籍觀點（需 ≥1 處：《書名》＋它的核心主張，寫進做法依據裡）")

    # 8d 定位篇：≥1 個定位理論關鍵詞（警告 —— 不掛編號後不再強制模型碼）
    _mp = re.search(r"^#{1,4}\s*[^\n]*定位[與与]口[徑径](.*?)(?=^#{1,2}\s|\Z)", text, flags=re.S | re.M)
    _pos = _mp.group(1) if _mp else ""
    _pos_kw = ["定位", "品牌資產", "品牌资产", "視覺錘", "视觉锤", "超級符號", "超级符号",
               "USP", "獨特賣點", "独特卖点", "品類", "心智", "里斯", "特勞特", "凱勒",
               "華與華", "馮衛東", "江南春", "CBBE", "對立定位", "場景"]
    _kw_signals = {k for k in _pos_kw if k in _pos}
    if _pos and _kw_signals:
        if not quiet:
            print(f"  {OK} 定位篇理論關鍵詞 {len(_kw_signals)} 個")
    elif _pos:
        if not quiet:
            print(f"  {WARN} 定位篇未見定位理論關鍵詞")
        warnings.append("定位篇建議點明用的是哪一套定位理論（並說清楚怎麼用在這一步）")
    else:
        if not quiet:
            print(f"  {WARN} 未找到第三篇定位章節，跳過")
        warnings.append("未找到第三篇 定位與口徑，無法校驗定位理論")

    # 9) 交付稿須簡體（SKILL.md 硬要求）—— 偵測繁體字
    #    只做警告：專業名詞可能含繁體，且 composer 骨架本就注入繁體（交付前需本地化）
    _trad_hint = set("們個這說對產麼無為與於還進來過學經銷廣價範實樣觀點圍優質讓覺聲話術確認據應該務專態勢將團隊費責機構營運畫計劃達標類數據網絡歷總轉發構則議權價錢廠號樓區塊")
    hit_trad = sorted({ch for ch in text if ch in _trad_hint})
    if not quiet:
        print(f"\n【9】交付稿簡體檢查（SKILL 要求交付稿簡體）")
        print(f"  {'✅' if len(hit_trad) < 15 else WARN} 偵測到繁體字 {len(hit_trad)} 種"
              + (f"（{'、'.join(hit_trad[:15])}…）" if hit_trad else ""))
    if len(hit_trad) >= 15:
        # 改為硬錯誤（2026-09-16）：SKILL 明定交付稿必須簡體，只警告＝繁體稿照樣能出 → 規則形同虛設
        hard_errors.append(f"交付稿疑似繁體（{len(hit_trad)} 種繁體字：{'、'.join(hit_trad[:10])}…）"
                           f"—— SKILL 要求對外交付稿用**簡體**，請本地化後重跑")

    # 10) 交付稿潔淨度 —— 硬錯誤（2026-09-17 新增）
    #
    #    這關是整套改造的**收口**：前面把座標從骨架裡拿掉了，這裡確保模型補寫時
    #    也不會把座標加回來。出現任何一條 → 不准出稿。
    #    客戶不需要知道我們內部怎麼編號、檔案放在哪、用了哪個腳本。
    if not quiet:
        print("\n【10】交付稿潔淨度（不得出現任何內部座標）")
    _coord_pats = [
        (r"§\s*\d", "章節編號（§X.X）"),
        (r"cases/\d{2}-", "案例庫檔案路徑"),
        (r"references/", "references 目錄路徑"),
        (r"打法[庫库]", "「打法库」內部檔名"),
        (r"03\s*[·§]?\s*[A-Ma-m]\d", "03 模型碼"),
        (r"模型\s*[A-Ma-m]\d{1,2}", "模型碼"),
        (r"49\s*[）)]", "49 書籍編號"),
        (r"模式\s*\d{1,2}", "失敗歸因「模式 NN」編號"),
        (r"(?:composer|selfcheck|build_docx|run_pipeline|gate_check|kb_audit)\.py", "腳本檔名"),
        (r"(?:SKILL|AGENTS)\.md", "內部文檔檔名"),
        (r"knowledge_map", "內部映射表檔名"),
        (r"方法论操作手册|方法論操作手冊", "內部手冊檔名"),
        # 2026-09-17 新增：**施工語氣**。這些不是「座標」，但同樣是給執行 AI 的指令，
        # 印進客戶文檔裡一樣穿幫（實測 composer 曾在交付稿留下
        # 「—— 说明用在定位的哪一步」）。【10】關原本 12 條正則一條都蓋不到。
        (r"——\s*说明|——\s*說明", "給 AI 的施工說明"),
        (r"（自行填寫|（自行填写|自行填寫", "施工指引語氣"),
        (r"按指引|依指引|照骨架|見骨架", "施工指引語氣"),
        (r"\{FILL\}|【待填】|【待补】", "未替換的佔位符"),
    ]
    _coord_hits = []
    for _pat, _label in _coord_pats:
        for _m in re.finditer(_pat, text):
            _coord_hits.append((text[:_m.start()].count("\n") + 1, _label, _m.group(0).strip()[:24]))
    if _coord_hits:
        if not quiet:
            print(f"  {NG} 發現 {len(_coord_hits)} 處內部座標：")
            for _ln, _label, _raw in _coord_hits[:10]:
                print(f"     · 第 {_ln} 行【{_label}】{_raw}")
        hard_errors.append(
            f"交付稿出現 {len(_coord_hits)} 處內部座標（"
            + "、".join(sorted({x[1] for x in _coord_hits}))
            + f"）——客戶看不懂也不需要看。改成可讀的內容；"
            f"溯源訊息請寫進 `composer.py --internal` 那份文件裡"
        )
    else:
        if not quiet:
            print(f"  {OK} 無內部座標（客戶可直接閱讀／提交）")

    # 11) 場景完整性（2026-09-17 新增）
    #     大賽／B端／G端／投標 各自有「必須有的章節」（見 references/09 + composer SCENE_SECTIONS）。
    #     缺一塊＝不完整（「寫得再好，缺一塊就是不完整的」）。
    #     觸發條件：正文出現「## 九 ·」場景章節標題 → 判定用了場景結構 → 必須補齊該場景後續章節。
    #     判定：場景可識別且核心章節缺失 → 硬錯誤（退出碼 1，不得交付）；
    #           未用場景結構（無「九」章節）或「九」標題無法識別場景 → 只警告，不攔。
    #     ⚠️ 比對字串用**簡體**（交付稿依【9】必須是簡體）；註解用繁體與本檔一致。
    if not quiet:
        print("\n【11】場景完整性（大賽／B端／G端／投標 各自必須有的章節）")
    _scene_detect = [
        ("大賽", "创意设计执行"),
        ("B端", "生意拆解与机会量化"),
        ("G端", "政策依据与上位规划"),
        ("投標", "商务响应偏离表"),
    ]
    _scene_req = {
        "大賽": ["创意设计执行", "媒介排期表", "提案脚本", "评委问答预判"],
        "B端": ["生意拆解与机会量化", "财务测算与盈亏平衡", "组织与人力可行性", "商务条款"],
        "G端": ["政策依据与上位规划", "绩效目标与考核", "资金与保障", "汇报与评审", "合规与舆情红线"],
        "投標": ["商务响应偏离表", "需求理解", "实施与保障", "业绩与售后", "报价与资质"],
    }
    m9 = re.search(r"(?m)^##\s*九\s*[·・.\s]*(.+?)(?=^##\s|\Z)", body, flags=re.S)
    _detected = None
    if m9:
        head9 = m9.group(1)
        for sc, kw in _scene_detect:
            if kw in head9:
                _detected = sc
                break
    if _detected:
        req = _scene_req[_detected]
        missing = [c for c in req if c not in body]
        if not quiet:
            print(f"  {OK if not missing else NG} 識別為「{_detected}」場景；"
                  f"應有 {len(req)} 個場景章節，缺失 {len(missing)} 個"
                  + (f"：{'、'.join(missing)}" if missing else "（齊全）"))
        if missing:
            hard_errors.append(
                f"「{_detected}」場景缺失核心章節：{'、'.join(missing)}"
                f"—— 見 references/09-完整策劃標準與評分表.md 該場景的必寫章節清單"
                f"（composer --scene {_detected} 會自動注入）"
            )
    elif m9:
        if not quiet:
            print(f"  {WARN} 出現「九 ·」章節但無法識別場景（標題：{m9.group(1)[:28]}…），跳過場景校驗")
        warnings.append("「九 ·」章節標題無法識別場景類型（應為 创意设计执行／生意拆解／政策依据／商务响应偏离表 之一），未做場景完整性校驗")
    else:
        if not quiet:
            print(f"  {WARN} 未使用場景結構（無「九 ·」章節）—— 若為大賽／B端／G端／投標 交付，須補場景章節")
        warnings.append("未檢測到場景章節（## 九 ·）。若本案為大賽／B端／G端／投標 交付，需補該場景必有的章節（見 references/09-完整策劃標準與評分表.md）")

    # ── 【12】交付自檢單防偽（2026-09-17 補：原本號段缺【12】，且自檢單是**模型自填**）
    #    問題：協議 3 要求輸出 12 項自檢單，但「結果」那一欄由模型自己填 ——
    #    填 12 個 ✅ 就過關。這讓全表打分最高的「交付治理」變成自我聲明（假綠）。
    #    做法：① 抽出文檔裡自檢單的每一行判斷；② 與腳本本輪的真實判定比對；
    #          **自評高於腳本判定 → 硬錯誤**。這正是「假綠」的可操作定義。
    if not quiet:
        print("\n【12】交付自檢單防偽（自評不得高於腳本判定）")
    _rows = re.findall(r"(?m)^\s*\|[^|\n]*自檢|^\s*[-*]\s*\[[ xX]\]", text)
    _claimed_ok = len(re.findall(r"✅", text))
    _claimed_bad = len(re.findall(r"❌", text))
    # 腳本判定的「還能有幾項通過」：本輪 hard_errors / warnings 越多，可用額度越低
    _quota = max(0, 12 - len(hard_errors) * 2 - len(warnings))
    if not quiet:
        print(f"  文檔自評：✅ {_claimed_ok} 個 ／ ❌ {_claimed_bad} 個"
              f"（表格行 {len(_rows)} 條）")
        print(f"  腳本判定上限：✅ 至多 {_quota} 個（依本輪 {len(hard_errors)} 項硬錯誤、"
              f"{len(warnings)} 項警告推算）")
    if _claimed_ok > 0 and _claimed_ok > _quota and hard_errors:
        hard_errors.append(
            f"自檢單**自評高於腳本判定**：文檔裡標了 {_claimed_ok} 個 ✅，"
            f"但本輪有 {len(hard_errors)} 項硬錯誤、{len(warnings)} 項警告 —— "
            f"按腳本判定最多只允許 {_quota} 個 ✅。**自檢單不是自我聲明。**")
    elif not hard_errors and _claimed_ok == 0 and _claimed_bad == 0:
        warnings.append("未見任何 ✅/❌ 標記 —— 協議 3 要求把 12 項自檢單原樣輸出在回覆中")

    # ── 【13】交叉引用與編號連續性（2026-09-17 新增）
    #    為什麼要這一關：瞳話案前 12 關全綠，卻有 **4 處**「詳見第三部分 1.1 的反对意见」
    #    指向**根本不存在的章節**，而且團隊十章編號重複（「三」出現兩次）／倒序
    #    （一→三→二）／斷號（十章裡的「十」消失）。
    #    → 前 12 關查的都是「這份檔案自己的性質」；「指到別處的引用是否真的指得到」
    #      是**跨章節**的性質，沒有一關在查 —— 同一類「零件全合格、傳動軸是斷的」漏檢。
    #    判定：引用指向不存在的章節／章號重複／子編號重複 → 硬錯誤；
    #          章號非遞增、章內子編號非遞增 → 警告（不攔，但交付前要人工確認）。
    if not quiet:
        print("\n【13】交叉引用與編號連續性（指向不存在的章節＝硬錯誤）")
    _cn = {c: i for i, c in enumerate("一二三四五六七八九十", 1)}
    _part = None
    _idx = set()                 # (部分, A.B) —— 真實存在的子章節
    _chaps = []                  # (部分, 中文章號, 章名)
    _subs = {}                   # (部分, 桶) -> [A.B ...] 按出現順序
    _cur = None                  # 當前「### 中文數字、」章號
    _sec = ""                    # 當前「##」節標題（給沒章號的子節歸桶，避免誤判非遞增）
    for _l in body.split("\n"):
        _m = re.match(r"^#\s*第([一二三四五六七八九十]+)部分", _l)
        if _m:
            _part, _cur, _sec = _m.group(1), None, ""
            continue
        _m = re.match(r"^##\s+(.+?)\s*$", _l)
        if _m:                    # 進入新的 ## 節 → 上一個「### 章」的作用域結束
            _cur, _sec = None, _m.group(1)
            continue
        _m = re.match(r"^###\s*([一二三四五六七八九十]+)、(.+?)\s*$", _l)
        if _m:
            _cur = _m.group(1)
            _chaps.append((_part, _cur, _m.group(2)))
            continue
        _m = re.match(r"^#{3,4}\s*([0-9]+\.[0-9]+)\s", _l)
        if _m:
            _idx.add((_part, _m.group(1)))
            _bucket = _cur if _cur else f"§{_sec}"
            _subs.setdefault((_part, _bucket), []).append(_m.group(1))

    # ① 交叉引用：帶部分號的「第X部分 A.B」必須指得到
    _tot = _dangling = 0
    _bad_refs = []
    for _m in re.finditer(r"第([一二三四五六七八九十]+)部分\s*([0-9]+\.[0-9]+)", body):
        _tot += 1
        if (_m.group(1), _m.group(2)) not in _idx:
            _dangling += 1
            _s = max(0, _m.start() - 40)
            _bad_refs.append(f"第{_m.group(1)}部分 {_m.group(2)} —— 指向不存在的章節"
                             f"（上下文：…{body[_s:_m.end() + 16].replace(chr(10), ' ')}…）")
    if not quiet:
        print(f"  {OK if not _dangling else NG} 帶部分號的引用 {_tot} 處，指向不存在章節 {_dangling} 處")
        for _b in _bad_refs[:6]:
            print(f"       ✗ {_b}")
    if _dangling:
        hard_errors.append(f"交叉引用 {_dangling} 處指向不存在的章節（共 {_tot} 處引用）："
                           + "；".join(_bad_refs[:4])
                           + "　→ 改結構後必須同步改引用（見 references/11-防返工交付协议.md 鐵律 4）")

    # ② 章號重複
    _seen, _dups = {}, []
    for _p, _c, _n in _chaps:
        _k = (_p, _c)
        if _k in _seen:
            _dups.append(f"第{_p}部分「{_c}、{_n}」與「{_c}、{_seen[_k]}」編號重複")
        _seen[_k] = _n
    if not quiet:
        print(f"  {OK if not _dups else NG} 章節（### 中文數字、）共 {len(_chaps)} 個，編號重複 {len(_dups)} 處")
        for _d in _dups[:6]:
            print(f"       ✗ {_d}")
    if _dups:
        hard_errors.append("章節編號重複：" + "；".join(_dups[:4]))

    # ③ 同一部分內子編號重複
    _sub_dup = []
    for _p in {p for p, _, _ in _chaps} | {p for p, _ in _idx}:
        _by = [s for (pp, s) in _idx if pp == _p]
        for _s in set(_by):
            if _by.count(_s) > 1:
                _sub_dup.append(f"第{_p}部分子編號 {_s} 出現 {_by.count(_s)} 次")
    if not quiet:
        print(f"  {OK if not _sub_dup else NG} 同部分內子編號重複 {len(_sub_dup)} 處")
        for _d in _sub_dup[:6]:
            print(f"       ✗ {_d}")
    if _sub_dup:
        hard_errors.append("子章節編號重複：" + "；".join(_sub_dup[:4]))

    # ④ 章號是否遞增（同一部分內）
    _order_bad = []
    _lastp, _last = None, 0
    for _p, _c, _n in _chaps:
        if _p != _lastp:
            _lastp, _last = _p, 0
        _v = _cn.get(_c, 0)
        if _v and _v < _last:
            _order_bad.append(f"第{_p}部分：「{_c}、{_n}」排在更大的編號之後（應遞增）")
        _last = max(_last, _v)
    # ⑤ 章內子編號是否遞增
    _sub_order_bad = []
    for _k, _lst in _subs.items():
        _se = [int(x.split(".")[1]) for x in _lst]
        if _se != sorted(_se):
            _bad_at = next(i for i in range(1, len(_se)) if _se[i] < _se[i - 1])
            _sub_order_bad.append(f"第{_k[0]}部分「{_k[1]}」章內子編號非遞增："
                                  f"{_lst[_bad_at - 1]} → {_lst[_bad_at]}")
    if not quiet:
        _nw = len(_order_bad) + len(_sub_order_bad)
        print(f"  {OK if not _nw else WARN} 編號順序問題 {_nw} 處（章號倒序／章內子編號非遞增）")
        for _d in (_order_bad + _sub_order_bad)[:6]:
            print(f"       ⚠ {_d}")
    for _d in _order_bad + _sub_order_bad:
        warnings.append(_d + "　→ 建議按正文出現順序重編號（結構一改就要同步改引用）")

    # ── 【14】實質與創意判據（2026-09-17 新增，回應 4A／貝恩／BCG 三視角的第 6–9 條）
    #    共同病灶：**「有檢查」但攔不住空話** —— 標題在場就算通過、字數夠就算寫開。
    #    本關四組判據全部針對「實質」：
    #      14a 執行摘要門檻（決策者唯一會讀的一頁，原本零門檻）
    #      14b AI 腔掃描（`09` 明文禁形容詞堆砌，但腳本一直沒有詞表）
    #      14c 場景章深度（原本只查標題存在，正文 0 字也過）
    #      14d Big Idea 可複述性（創意完全沒有專屬判據）
    if not quiet:
        print("\n【14】實質與創意判據（執行摘要／AI 腔／場景深度／Big Idea）")

    _secs = {}
    for _m in re.finditer(r"(?m)^##\s+(.+?)\s*$", body):
        _start = _m.end()
        _nxt = re.search(r"(?m)^##\s+", body[_start:])
        _secs[_m.group(1)] = body[_start:_start + (_nxt.start() if _nxt else len(body))]

    # 14a 執行摘要
    _abs = next((v for k, v in _secs.items() if "執行摘要" in k or "执行摘要" in k), "")
    _n_num = len(re.findall(r"\d[\d,.]*\s*(?:元|%|％|万|萬|单|單|人|店|次|万|萬)", _abs))
    _has_bl = bool(re.search(r"盈虧線|盈亏线|保本|打平", _abs))
    if _abs:
        _ok_a = _n_num >= 4 and _has_bl
        if not quiet:
            print(f"  {OK if _ok_a else NG} 執行摘要：{len(_abs)} 字、帶單位數字 {_n_num} 個"
                  f"（需 ≥4）、含盈虧線/保本 {'是' if _has_bl else '否'}")
        if not _ok_a:
            hard_errors.append(
                f"執行摘要不達標（數字 {_n_num}/4，盈虧線 {'有' if _has_bl else '無'}）—— "
                "決策者常常只看這一頁；它必須自帶 ≥4 個可核驗數字 ＋ 一句盈虧線。")
    else:
        warnings.append("找不到「執行摘要」區塊，14a 未生效")

    # 14b AI 腔
    _smell = {}
    for _w in AI_SMELL_WORDS:
        _c = body.count(_w)
        if _c:
            _smell[_w] = _c
    _struct = []
    if len(re.findall(r"不是[^，。]{1,12}——?是", body)) >= 3:
        _struct.append("「不是…是…」句式 ≥3 次")
    if len(re.findall(r"[\u4e00-\u9fff]{4}[，、][\u4e00-\u9fff]{4}[，、][\u4e00-\u9fff]{4}", body)) >= 3:
        _struct.append("四字格连排 ≥3 处")
    if not quiet:
        print(f"  {OK if not _smell and not _struct else WARN} AI 腔："
              f"詞 {len(_smell)} 種{'（' + '、'.join(list(_smell)[:6]) + '）' if _smell else ''}"
              f"、結構特徵 {len(_struct)} 項")
    if _smell or _struct:
        warnings.append("AI 腔：詞 " + "、".join(f"{k}×{v}" for k, v in list(_smell.items())[:6])
                        + ("；" + "；".join(_struct) if _struct else "")
                        + "　→ `09` 明文禁形容詞堆砌，改成動作與數字")

    # 14c 場景章深度
    _scene_req = {
        "大赛": ["创意设计执行", "媒介排期表", "提案脚本", "评委问答预判"],
        "B端": ["生意拆解与机会量化", "财务测算与盈亏平衡", "组织与人力可行性", "商务条款"],
        "G端": ["政策依据与上位规划", "绩效目标与考核", "资金与保障", "汇报与评审"],
        "投标": ["商务响应偏离表", "需求理解", "实施与保障", "业绩与售后"],
    }
    _thin_ch = []
    for _title, _txt in _secs.items():
        for _sc, _req in _scene_req.items():
            if any(c in _title for c in _req):
                _nums = len(re.findall(r"\d[\d,.]*\s*(?:元|%|％|万|萬|天|周|個月|个月|次|单|單)", _txt))
                _tbl = _txt.count("\n|")
                _fill = len(re.findall(r"【填】|\{FILL\}", _txt))
                if _nums < 3 or _tbl < 1 or _fill > 0:
                    _thin_ch.append(f"{_title[:18]}（數字 {_nums}/3、表格行 {_tbl}、殘留 【填】 {_fill}）")
    if not quiet:
        print(f"  {OK if not _thin_ch else NG} 場景章深度：不達標 {len(_thin_ch)} 章")
        for _c in _thin_ch[:6]:
            print(f"       ✗ {_c}")
    if _thin_ch:
        hard_errors.append("場景章內容不達標（只有標題不算完整）：" + "；".join(_thin_ch[:5])
                           + "　→ 每章須 ≥3 個帶單位數字、≥1 張表、無 【填】 殘留")

    # 14d Big Idea（僅在出現「大賽／提案」字樣時判）
    _bi = re.search(r"Big Idea[^\n]*[:：]\s*(.+)", body)
    if _bi:
        _s = re.sub(r"[\s【】]", "", _bi.group(1))[:80]
        _len_ok = 6 <= len(_s) <= 22
        _conc = any(w in _s for w in CONCRETE_ACTION_WORDS + CONCRETE_OBJECT_WORDS)
        _gen = [w for w in GENERIC_CATEGORY_WORDS if w in _s]
        _prob = []
        if not _len_ok:
            _prob.append(f"長度 {len(_s)} 字（需 6–22，超長即不可複述）")
        if not _conc:
            _prob.append("未綁定具體動作或具體物")
        if _gen:
            _prob.append("含品類通用詞：" + "、".join(_gen))
        if not quiet:
            print(f"  {OK if not _prob else NG} Big Idea：{_s[:30]}…"
                  + (f"（{'；'.join(_prob)}）" if _prob else ""))
        if _prob:
            hard_errors.append("Big Idea 不達標：" + "；".join(_prob)
                               + "　→ 判據是「一句能被別人複述、且綁定了具體動作或物」。")
    elif not quiet:
        print(f"  {INFO} 未見 Big Idea（非大賽／提案場景可忽略）")

    # ── 【15】新增章节的实质校验（2026-09-17 随 R1 的 C 组一起加）
    #    原则同【14】：**标题在场不算数**，要看它有没有被真填、且填得够硬。
    if not quiet:
        print("\n【15】新增章节实质校验（利益相关者／Red Team／洞察／取舍／回指／渠道）")

    # 15a 利益相关者与阻力处理
    _stake = [v for k, v in _secs.items() if "利益相关者" in k]
    if _stake:
        _txt = _stake[0]
        _rows = [r for r in _txt.split("\n") if r.strip().startswith("|")][1:]
        _against = len(re.findall(r"反对", _txt))
        _ok = len(_rows) >= 3 and _against >= 1
        if not quiet:
            print(f"  {OK if _ok else NG} 利益相关者：{len(_rows)} 个角色行（需 ≥3）、"
                  f"出现「反对」{_against} 次（需 ≥1）")
        if not _ok:
            hard_errors.append(
                "利益相关者章不达标 —— 需 ≥3 个角色且**至少 1 个反对者**。"
                "全是「支持」等于这份方案没做过落地推演。")
    else:
        warnings.append("未見「利益相关者与阻力处理」章 —— 桌面档／B端／G端 交付必须补（见 12-范式库）")

    # 15b Red Team
    _rt = [v for k, v in _secs.items() if "最可能怎么死" in k]
    if _rt:
        _txt = _rt[0]
        _n_arg = len(re.findall(r"最强反方论点", _txt))
        _n_cond = len(re.findall(r"成立的条件", _txt))
        _n_date = len(re.findall(r"成立的条件[^\n]*\d", _txt))
        _ok = _n_arg >= 3 and _n_cond >= 3 and _n_date >= 3
        if not quiet:
            print(f"  {OK if _ok else NG} Red Team：论点 {_n_arg}/3、条件 {_n_cond}/3、"
                  f"含数字或日期的条件 {_n_date}/3")
        if not _ok:
            hard_errors.append("Red Team 不达标 —— 定长三条，且每条的「成立条件」必须含数字或日期。")
    else:
        warnings.append("未見「这个方案最可能怎么死」（Red Team）章 —— 建议补")

    # 15c 洞察萃取
    _ins = [v for k, v in _secs.items() if "洞察萃取" in k]
    if _ins:
        _txt = _ins[0]
        _ok = ("共鸣测试" in _txt) and bool(re.search(r"(人|用户|用戶)", _txt))
        if not quiet:
            print(f"  {OK if _ok else NG} 洞察萃取：含共鸣测试 {'是' if '共鸣测试' in _txt else '否'}")
        if not _ok:
            hard_errors.append("洞察萃取不达标 —— 必须有共鸣测试（念给 3 个人，几人说「啊，我也是」）。")

    # 15d 主动放弃
    _con = [v for k, v in _secs.items() if "约束与风险底线" in k]
    if _con:
        _n_give = len(re.findall(r"放弃|不做|砍掉|砍哪", _con[0]))
        _ok = _n_give >= 2
        if not quiet:
            print(f"  {OK if _ok else NG} 主动放弃：出现 {_n_give} 次（需 ≥2）")
        if not _ok:
            hard_errors.append("「主动放弃了什么」不足 2 条 —— 只写约束不写放弃，等于没做取舍（80/20 的反面）。")

    # 15e 创意回指
    if re.search(r"Big Idea", body):
        _n_trace = len(re.findall(r"回指", body))
        _ok = _n_trace >= 1 and bool(re.search(r"打法\s*\{?【?填?】?\}?\s*\d*", body))
        if not quiet:
            print(f"  {OK if _ok else NG} 创意回指：「回指」出现 {_n_trace} 次")
        if not _ok:
            hard_errors.append("创意没有回指策略 —— 每个样稿必须写「回指：本条创意解决【打法 N】的第【X】步」。")

    # 15g 议题树与假设台账（BCG 判据：没有议题树就写正文＝不合格）
    #     ⚠️ 2026-09-17 把关范围收窄：原先的「无条件硬错误」会误伤**速览类快案**
    #        （实测 smoke_test 的标杆稿 —— 一份便利店开学季快案 —— 因没有议题树被判硬错误）。
    #        → 议题树是**完整版方案**的判据，不是速览稿的。改为：
    #          · 稿里用了「〇 · 议题树与假设台账」这章 → 必须写够（硬错误）
    #          · 稿是完整版（八篇骨架）却没用这章 → 硬错误（漏了 BCG 的题眼）
    #          · 稿是速览类（没有完整八篇） → 只提醒，不拦
    _has_issue_tree = "议题树与假设台账" in body
    _is_full_plan = all(x in body for x in ["现状分析", "策略", "定位与口径", "预算明细"])
    _h_all = re.findall(r"\bH(\d+)\b", body)
    _distinct = sorted(set("H" + n for n in _h_all))
    _refer = sorted(h for h in _distinct if body.count(h) >= 2)   # 定义＋被引≥1 次
    if _has_issue_tree:
        _ok_g = len(_distinct) >= 3 and len(_refer) >= 3
        if not quiet:
            print(f"  {OK if _ok_g else NG} 议题树：H 编号 {len(_distinct)} 条（需 ≥3）、"
                  f"被正文引用 ≥1 次的 {len(_refer)} 条（需 ≥3）")
        if not _ok_g:
            hard_errors.append(
                f"议题树与假设台账不达标 —— 需要 ≥3 条可证伪的 H，且每条在正文里至少被引用一次"
                f"（现在有 {len(_distinct)} 条、被引 {len(_refer)} 条）。"
                "写在台账里却不被回应，等于没做假设驱动。")
    elif _is_full_plan:
        if not quiet:
            print(f"  {NG} 完整版方案缺「〇 · 议题树与假设台账」")
        hard_errors.append(
            "完整版方案缺「〇 · 议题树与假设台账」—— BCG 判据：没有议题树就写正文＝不合格。")
    else:
        if not quiet:
            print(f"  {INFO} 未使用议题树结构（速览类快案可忽略）")

    # 15f 渠道不可移植元素
    _ch = [v for k, v in _secs.items() if "不同形态" in k]
    if _ch:
        _txt = _ch[0]
        _rows = [r for r in _txt.split("\n") if r.strip().startswith("|")][1:]
        _ok = len(_rows) >= 1 and "不可移植" in _txt
        if not quiet:
            print(f"  {OK if _ok else NG} 渠道形态表：{len(_rows)} 行、含「不可移植元素」列 "
                  f"{'是' if '不可移植' in _txt else '否'}")
        if not _ok:
            hard_errors.append("渠道只是「换名字」—— 5.1 表必须有「不可移植元素」列，且每渠道至少 1 个。")

    # ── 【16】合規紅線與量化可驗（2026-09-17 隨 R2 一起加）
    #    ⚠️ 本關的很多要求屬「**完整版方案才該有**」。今天已經**連續四次**因為
    #       新硬關無條件生效而誤傷速覽類快案（smoke_test 的標杆稿）：
    #         ① `8a 為什麼這麼做須含實質`  ② `15g 議題樹`  ③ `16f 敏感性`  ④ `16g KPI 頻率/責任人`
    #       所以不再逐次打補丁，改成一個顯式助手 —— 新加的「完整版要求」一律走它。
    def _hard_if_full(msg):
        """完整版才判硬錯誤；速覽類快案降為警告。（判據：_is_full_plan）"""
        if _is_full_plan:
            hard_errors.append(msg)
        else:
            warnings.append(msg + "（速覽類快案可忽略；若本案其實是完整版請補）")

    if not quiet:
        print("\n【16】合規紅線與量化可驗（個人信息／文號／偏離值／可證偽／因果／敏感性）")

    # 16a 個人信息紅線（R2-18）
    _pid = re.findall(r"\b1[3-9]\d{9}\b", body)
    _idc = re.findall(r"\b\d{17}[\dXx]\b", body)
    if _pid or _idc:
        if not quiet:
            print(f"  {NG} 疑似個人信息：手機號 {len(_pid)} 處、身份證號 {len(_idc)} 處")
        hard_errors.append(f"疑似出現個人信息（手機號 {len(_pid)}／身份證 {len(_idc)}）—— "
                           f"數據合規紅線，交付前必須刪除或脫敏。")
    elif not quiet:
        print(f"  {OK} 未見手機號／身份證號")

    # 16b G 端政策文號（R2-16）
    if re.search(r"政策依据|政策依據", body):
        _doc_no = re.findall(r"〔\s*20\d{2}\s*〕\s*第?\d+\s*號?号?|國發|国发|國辦發|国办发", body)
        if not _doc_no:
            if not quiet:
                print(f"  {NG} G 端政策依據：未見任何公文文號（〔20XX〕第 N 號／國發 等）")
            hard_errors.append("政策依據章沒有公文文號 —— 寫「依據國家相關政策」等於沒依據，"
                               "評審第一關即出局。需寫到「文件名稱＋文號＋具體條款」。")
        elif not quiet:
            print(f"  {OK} 政策文號：命中 {len(_doc_no)} 處")

    # 16c 投標偏離表響應值（R2-17）
    if re.search(r"商務響應偏離表|商务响应偏离表", body):
        _rows = [r for r in re.findall(r"(?m)^\|.*響應.*\|.*$|^\|.*响应.*\|.*$", body)]
        _resps = re.findall(r"(完全響應|完全响应|正偏離|正偏离|負偏離|负偏离)", body)
        if not _resps:
            if not quiet:
                print(f"  {NG} 投標偏離表：未見「完全響應／正偏離／負偏離」的響應判定")
            hard_errors.append("商務響應偏離表沒寫響應判定 —— 每條招標要求必須標"
                               "「完全響應／正偏離／負偏離」，負偏離還需給補救說明。")
        elif not quiet:
            print(f"  {OK} 投標偏離表：響應判定 {len(_resps)} 處"
                  f"（負偏離 {sum(1 for x in _resps if '負' in x or '负' in x)} 處）")

    # 16d 假設可證偽（R2-1）
    _htab = re.search(r"(?m)^\|\s*H#.*$", body)
    if _htab:
        _rows = [r for r in re.findall(r"(?m)^\|\s*H\d+.*$", body)]
        _weak = [r for r in _rows
                 if not re.search(r"若|如果|一旦|可驗證|可验证|驗證方式|验证方式|數據截止|数据截止", r)]
        if not quiet:
            print(f"  {OK if not _weak else NG} 假設可證偽：{len(_rows)} 行，其中 {len(_weak)} 行看不出證偽條件")
        if _weak:
            hard_errors.append(
                f"{len(_weak)} 條假設看不出「怎麼被證偽」——寫「用戶喜歡新品」這種不可證偽的假設"
                f"不算假設驅動。每條須能寫出「若拿到什麼，就說明我錯了」。")

    # 16e 相關當因果（R2-10）
    _causal_claims = []
    for _m in re.finditer(r"(帶動|带动|帶來|带来|提升|拉動|拉动)[^。]{0,15}?\d+(\.\d+)?\s*[%％]", body):
        _s = body[max(0, _m.start() - 20):_m.end() + 10]
        if not re.search(r"較|较|vs|VS|基期|對照|对照|前提|假設|假设|預估|预估", _s):
            _causal_claims.append(_s.replace("\n", " ")[:36])
    if _causal_claims:
        if not quiet:
            print(f"  {WARN} 疑似「相關當因果」{len(_causal_claims)} 處（無基期／對照／前提）")
            for _c in _causal_claims[:3]:
                print(f"       ⚠ {_c}…")
        warnings.append(f"疑似把相關當因果 {len(_causal_claims)} 處 —— 效果類數字須帶"
                        f"「較／基期／對照／前提」，否則只是願望：{'；'.join(_causal_claims[:2])}")
    elif not quiet:
        print(f"  {OK} 效果類數字未見裸因果句")

    # 16f 敏感性分析（R2-3）
    #    ⚠️ 2026-09-17 第三次踩同一个坑：新加的硬关又误伤了**速览类快案**
    #       （smoke_test 的标杆稿 —— 便利店开学季快案）。
    #       前两次分别是「议题树」（15g）与「为什么这么做须含实质」（8a）。
    #       → 固化成规律，不再逐次打补丁：
    #         **凡是「完整版才该有」的要求，一律先判 `_is_full_plan`；
    #           速览类快案只提醒、不判硬错误。**
    #         判据：完整版＝同时有「现状分析／策略／定位与口径／预算明细」四章。
    if re.search(r"盈虧線|盈亏线|保本", body):
        _sens = re.search(r"樂觀[\s\S]{0,300}?悲觀|乐观[\s\S]{0,300}?悲观", body)
        if _sens:
            if not quiet:
                print(f"  {OK} 敏感性分析：命中三档模式")
        else:
            if not quiet:
                print(f"  {'❌' if _is_full_plan else WARN} 有盈亏线但无三档敏感性"
                      + ("（完整版强制）" if _is_full_plan else "（速览类快案可忽略）"))
            _hard_if_full("有盈亏线却没有敏感性分析 —— 单点盈亏线是假精确；"
                          "关键结论须给乐观／基准／悲观三档。")
    elif not quiet:
        print(f"  {INFO} 未見盈虧線，16f 未生效")

    # 16g KPI 的「观测频率」与「谁来测」（R2-5）
    #    ⚠️ 没有频率与责任人的 KPI ＝ 没人会去看的指标。
    _kpi_hdr = re.search(r"(?m)^\|[^\n]*KPI[^\n]*\|\s*$", body)
    if _kpi_hdr:
        _h = _kpi_hdr.group(0)
        _has_freq = bool(re.search(r"頻率|频率|每日|每周|每月|多久", _h))
        _has_owner = bool(re.search(r"誰|谁|負責|负责|盯|觀測人|观测人", _h))
        if not quiet:
            print(f"  {OK if (_has_freq and _has_owner) else NG} KPI 表：频率列 "
                  f"{'有' if _has_freq else '缺'}、责任人列 {'有' if _has_owner else '缺'}")
        if not (_has_freq and _has_owner):
            _hard_if_full(
                "KPI 表缺「观测频率」或「谁来测」—— 没有频率与责任人的指标没人会去看，"
                "等于没有指标。（表头需含 频率/多久 与 谁/负责 两类列）")
    else:
        warnings.append("未找到 KPI 表头，16g 未生效")

    # 16h 数字三要素（来源／口径／时点）（R2-4）—— 先只警告，不拦
    _nums = re.findall(r"[^\n。；]{0,30}?\d+(?:\.\d+)?\s*(?:%|％|元|万元|萬)", body)
    _nu = [x for x in _nums if not re.search(r"预算|分項|分项|行動|行动|合計|合计|【填】|占位", x)]
    if _nu:
        _ok_n = [x for x in _nu
                 if re.search(r"來源|来源|据《|據《|來自|来自|後台|后台|年報|年报|問卷|问卷|"
                              r"n\s*=|我方測算|我方测算|假設|假设|估算|口徑|口径", x)]
        _rate = len(_ok_n) / len(_nu)
        if not quiet:
            print(f"  {OK if _rate >= 0.8 else WARN} 数字三要素（来源／口径／时点）："
                  f"{len(_ok_n)}/{len(_nu)} = {_rate:.0%}（建议 ≥80%）")
        if _rate < 0.8:
            warnings.append(
                f"数字三要素覆盖率 {_rate:.0%}（{len(_ok_n)}/{len(_nu)}）—— "
                f"裸数字（无来源的 %、金额）会被客户追问。建议补「来源／口径／时点」。")

    # ── 結論
    print("\n" + "=" * 64)
    if hard_errors:
        print(f"{NG} 自檢不通過（{len(hard_errors)} 項硬錯誤）：")
        for e in hard_errors:
            print(f"   · {e}")
        if warnings:
            print(f"\n{WARN} 另有 {len(warnings)} 項警告需人工確認：")
            for w in warnings:
                print(f"   · {w}")
        print("\n→ 修正硬錯誤後重跑。**不得宣告交付**（協議 3）。")
        emit_json(hard_errors, warnings, 1)
        sys.exit(1)

    print(f"{OK} 自檢通過（硬錯誤 0 項）。")
    if warnings:
        print(f"{WARN} {len(warnings)} 項警告，交付前請人工確認：")
        for w in warnings:
            print(f"   · {w}")
    print("\n→ 請把 12 項《交付自檢單》原樣輸出在交付回覆中（協議 3）。")
    emit_json([], warnings, 0)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{WARN} 已中斷（Ctrl+C）。")
        sys.exit(130)
    except Exception as e:
        print(f"\n{NG} 腳本執行出錯：{type(e).__name__}: {e}")
        print("→ 依協議 8（卡死處理）：")
        print("   1) 依上面訊息修正後重跑；")
        print("   2) 若屬環境問題（檔案讀不到／編碼異常），改用 Markdown 協議手工比對 §六 清單，不要卡在這裡；")
        print("   3) 同一項連續 2 次不過 → 停止重試，把問題攤給用戶決定。")
        sys.exit(2)
