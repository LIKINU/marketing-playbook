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

from _common import OK, NG, WARN, HINT, INFO   # noqa: E402  统一符号，不要在各自文件里重定义

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
# 允許出現在「禁用詞表」章節內（那是在說「不能說」）
BANNED_CONTEXT_SAFE = ["禁用詞", "禁用词", "禁用", "不能說", "不能说", "紅線", "红线", "不得", "禁止"]

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
    fill_cnt = len(re.findall(r"【填】", text))
    if not quiet:
        print(f"  {'✅' if fill_cnt < 3 else NG} composer 占位符【填】殘留：{fill_cnt} 處（<3 視為已填完）")
    if fill_cnt >= 3:
        hard_errors.append(f"方案殘留 {fill_cnt} 處 composer 占位符【填】 —— 骨架未填完，不得交付")

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
        if any(c in ln for c in BANNED_CONTEXT_SAFE):
            for j in range(max(0, i - 2), min(len(lines), i + 3)):
                safe_idx.add(j)
    scan_text = "\n".join(ln for i, ln in enumerate(lines) if i not in safe_idx)
    # 套用財務／統計語境白名單（避免「保本單量」這類術語誤報）
    for pat in BANNED_WHITELIST_PATTERNS:
        scan_text = re.sub(pat, "", scan_text)
    found = sorted({b for b in banned if b and b in scan_text})
    if found:
        for b in found:
            if not quiet:
                print(f"  {WARN} 疑似違規用語：「{b}」")
        warnings.append(f"疑似違規用語 {len(found)} 個：{'、'.join(found[:12])}"
                        + ("…" if len(found) > 12 else ""))
    elif not quiet:
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
            if solid < 25:
                _thin.append(i)
        if _thin:
            if not quiet:
                print(f"  {NG} 打法 {_thin} 的「為什麼這麼做」沒寫開（<25 實字）")
            hard_errors.append(
                f"打法 {_thin} 的「為什麼這麼做」只有編號或空話 —— 必須寫成客戶看得懂的內容"
                "（這套動作背後的道理是什麼、照著改為什麼不會跑偏），不能只寫理論名稱"
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

    # 結論
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
