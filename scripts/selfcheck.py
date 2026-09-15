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
import re
import sys

OK, NG, WARN = "✅", "❌", "⚠️"

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


def main():
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
    m_appendix = re.search(r"\n#{1,4}\s*(附件|附錄|附录)\s*[A-D]?\s*[:：·]?\s", text)
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
    for i, ln in enumerate(lines):
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

    # 7a 打法組合表 —— 硬錯誤（這是本 skill 的核心產物）
    combo = re.search(r"(?m)^\|[^\n]*(為什麼用它|为什么用它)[^\n]*\|", text)
    if combo:
        hdr = combo.group(0)
        cols = [c.strip() for c in hdr.strip("|").split("|")]
        # ⚠️ 繁简任一命中即可（修正 2026-09-16：此前要求繁简全中，簡體稿永遠誤報缺列）
        groups = {"打法": ["打法"], "具體動作": ["具體動作", "具体动作"], "誰做": ["誰做", "谁做"]}
        missing = [name for name, alts in groups.items() if not any(a in hdr for a in alts)]
        if not quiet:
            print(f"  {OK} 打法組合表存在（{len(cols)} 列）")
        if missing:
            warnings.append(f"打法組合表可能缺列：{'、'.join(missing)}")
    else:
        if not quiet:
            print(f"  {NG} 未找到「打法組合表」（表頭須含「為什麼用它」列）")
        hard_errors.append(
            "缺少《打法組合表》——須為：打法｜為什麼用它｜具體動作｜誰做｜花多少｜多久見效｜驗收指標｜可抄案例"
        )

    # 7b 問題類型 A–H 歸類 —— 警告
    mt = re.search(r"問題類型|问题类型", text)
    if mt and re.search(r"[A-H]", text[mt.start():mt.start() + 100]):
        if not quiet:
            print(f"  {OK} 問題類型已歸類（A–H）")
    else:
        if not quiet:
            print(f"  {WARN} 診斷未見「問題類型（A–H）」歸類")
        warnings.append("診斷缺「問題類型（A–H）」——見 SKILL.md 第 2 步分類表（認知/交易/渠道/信任/復購/定價/組織/合規）")

    # 7c 風險掛失敗歸因編號 —— 警告
    modes = re.findall(r"模式\s*\d{1,2}", text)
    if modes:
        if not quiet:
            print(f"  {OK} 風險已對照失敗歸因總庫（{'、'.join(sorted(set(modes))[:6])}）")
    else:
        if not quiet:
            print(f"  {WARN} 風險未掛「模式 NN」編號")
        warnings.append("風險自檢未掛「模式 NN」——請對照 04-失败归因总库.md 逐條標註（如「時機錯誤（模式 08）」）")

    # 7d 可抄案例引用 —— 警告
    case_refs = re.findall(r"(?:case\s*\d+|cases/\d{2})", text)
    if case_refs:
        # 2026-09-16：引用之外必須展開（別人怎麼做的）—— 只留卡片號＝不合格
        expanded = re.search(r"(別人怎麼做|别人怎么做|他面對什麼|他面对什么|怎麼用|怎么用|具體做了什麼|具体做了什么)", text)
        if not quiet:
            print(f"  {OK} 已引用案例庫可抄案例（{len(case_refs)} 處）"
                  + ("，且已展開成文字" if expanded else ""))
        if not expanded:
            warnings.append("可抄案例只有卡片號、未展開成文字 —— 須寫清「別人怎麼做的＋我們怎麼用」（用戶 2026-09-16 糾正）")
    else:
        if not quiet:
            print(f"  {WARN} 未引用案例庫可抄案例")
        warnings.append("打法組合表建議加「可抄案例」列（引用 cases/01–49 的具體卡片）——611 張卡應被調用")

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
        sys.exit(1)

    print(f"{OK} 自檢通過（硬錯誤 0 項）。")
    if warnings:
        print(f"{WARN} {len(warnings)} 項警告，交付前請人工確認：")
        for w in warnings:
            print(f"   · {w}")
    print("\n→ 請把 12 項《交付自檢單》原樣輸出在交付回覆中（協議 3）。")
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
