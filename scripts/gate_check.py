#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
門禁校驗 · gate_check.py  （marketing-playbook 協議 1）

用途：AI 問完門禁後、動筆寫方案前，跑一次這個腳本。
      門禁 13 項有任何一項沒填、或《任務規則表》沒經用戶確認、或**缺「交付長度」（第 14 項）**
      → 直接報錯，不准往下走。

用法：
    python gate_check.py gate.json
    cat gate.json | python gate_check.py -     # 從 stdin 讀

輸入 JSON 格式（欄位名可自由，腳本按別名匹配；匹配不到則按順序兜底）：
{
  "client": "客戶名",
  "gate": {
    "賣什麼": "川菜館，人均 60，毛利約 55%",
    "賣給誰": "周邊 3 公里上班族",
    ...共 13 項...
  },
  "rules_table_confirmed": true
}

退出碼：0 = 通過；1 = 不通過（AI 必須補齊後重跑）
"""

import json
import sys

# 13 項門禁（順序即標準順序）+ 別名，用於寬鬆匹配
GATE_ITEMS = [
    ("賣什麼（產品/服務、客單價、毛利）",
     ["卖什么", "賣什麼", "品类", "品類", "主营", "主營", "产品", "產品", "服务", "服務",
      "客单价", "客單價", "毛利", "生意", "卖点", "賣點"]),
    ("賣給誰（人群、場景）",
     ["卖给谁", "賣給誰", "客群", "受众", "受眾", "目标人群", "目標人群", "人群", "用户", "用戶", "场景", "場景"]),
    ("現在什麼規模",
     ["规模", "規模", "营收", "營收", "营业额", "營業額", "流水", "GMV", "门店", "門店", "用户数", "用戶數",
      "粉丝", "粉絲", "订单", "訂單"]),
    ("卡在哪（客戶原話）",
     ["卡在哪", "卡點", "卡点", "瓶颈", "瓶頸", "痛点", "痛點", "最大问题", "最大問題", "问题", "問題", "原话", "原話"]),
    ("預算多少",
     ["预算", "預算", "预算区间", "可投入", "投入", "费用", "費用"]),
    ("有什麼現成資源",
     ["现成资源", "現成資源", "资源", "資源", "人手", "团队", "團隊", "渠道", "供应商", "供應商", "私域"]),
    ("時間要求（死線/節點）",
     ["时间", "時間", "死线", "死線", "节点", "節點", "排期", "截止", "上线", "上線", "deadline", "窗口"]),
    ("硬約束（合規/場地/授權/不能做什麼）",
     ["硬约束", "硬約束", "约束", "約束", "合规", "合規", "场地", "場地", "授权", "授權", "红线", "紅線", "禁止", "不能"]),
    ("對接人與決策人",
     ["对接人", "對接人", "决策人", "決策人", "负责人", "負責人", "拍板", "老板", "老闆", "决策链", "決策鏈"]),
    ("競爭對手", ["竞争", "競爭", "竞品", "競品", "对手", "對手", "对标", "對標", "同行"]),
    ("過去試過什麼", ["过去", "過去", "试过", "試過", "之前做", "历史", "歷史", "复盘", "復盤", "已有经验", "已有經驗"]),
    ("怎麼算成功（驗收標準）",
     ["验收", "驗收", "算成功", "成功标准", "成功標準", "KPI", "指标", "指標", "目标", "目標", "考核"]),
    ("目標字數", ["目标字数", "目標字數", "字数", "字數", "页数", "頁數", "字数限制", "篇幅"]),
]

OK = "✅"
NG = "❌"


def load_json(path: str) -> dict:
    if path == "-":
        return json.load(sys.stdin)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_filled(v) -> bool:
    if v is None:
        return False
    s = str(v).strip()
    if not s:
        return False
    # 佔位符／「查不到」也算沒填（門禁項不接受「不知道」）
    bad = ["todo", "tbd", "待補", "待补", "待定", "待確認", "待确认", "未知", "不清楚",
           "不確定", "不确定", "暂无", "暫無", "无", "無", "没有", "沒有", "未定", "未確認",
           "未确认", "n/a", "na", "?", "？", "查不到", "未提供", "-", "—", "nil", "null"]
    return s.lower() not in bad


def match_item(gate: dict, aliases: list, used: set):
    """按別名匹配 gate 裡的 key；回傳 (key, value) 或 (None, None)。

    改進（2026-09-16）：舊版「第一個命中的 key」會在短別名（如「問題」「人群」）上誤配。
    現在取「最長命中別名」的 key（完全相等再加權），把誤配降到最低。
    """
    best_k, best_v, best_score = None, None, -1
    for k, v in gate.items():
        if k in used:
            continue
        kl = str(k).lower()
        for a in aliases:
            al = a.lower()
            if not al:
                continue
            if al in kl:
                score = len(al) + (1000 if kl == al else 0)  # 完全相等最優先
                if score > best_score:
                    best_k, best_v, best_score = k, v, score
    return best_k, best_v


USAGE = """用法: python gate_check.py <gate.json|->

輸入 JSON（欄位名可自由，腳本按別名匹配）：
{
  "client": "客戶名",
  "gate": { "賣什麼": "...", "賣給誰": "...", ...共 13 項... },
  "delivery": { "結構": "精煉版", "量級": "5 頁 Word" },
  "rules_table_confirmed": true
}
退出碼：0 通過 ｜ 1 不通過 ｜ 2 腳本錯誤"""


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(USAGE)
        sys.exit(0)
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(1)

    try:
        data = load_json(sys.argv[1])
    except Exception as e:
        print(f"{NG} 無法讀取輸入：{e}")
        sys.exit(1)

    gate = data.get("gate") or data.get("門禁") or data.get("門禁內容") or {}
    if not isinstance(gate, dict) or not gate:
        print(f"{NG} 找不到門禁資料。請在 JSON 裡提供 'gate' 物件。")
        sys.exit(1)

    client = data.get("client") or data.get("客戶") or data.get("客户") or "(未填客戶名)"
    confirmed = bool(
        data.get("rules_table_confirmed")
        or data.get("規則表已確認")
        or data.get("规则表已确认")
    )

    print("=" * 64)
    print(f"門禁校驗 · {client}")
    print("=" * 64)

    used = set()
    missing = []
    for label, aliases in GATE_ITEMS:
        k, v = match_item(gate, aliases, used)
        if k is not None:
            used.add(k)
        if k is not None and is_filled(v):
            short = str(v).strip().replace("\n", " ")
            if len(short) > 46:
                short = short[:46] + "…"
            print(f"{OK} {label}\n     {short}")
        else:
            print(f"{NG} {label}   ← 缺失")
            missing.append(label)

    # 未被匹配到的多餘欄位（提示，不算錯）
    extra = [k for k in gate.keys() if k not in used]
    if extra:
        print(f"\nℹ️  另有未匹配欄位（可能對應上面某項，請人工確認）：{'、'.join(map(str, extra))}")

    print("\n" + "-" * 64)
    print(f"規則表確認狀態：{'已確認 ' + OK if confirmed else '尚未確認 ' + NG}")

    print("-" * 64)
    if missing:
        print(f"{NG} 門禁不通過：還缺 {len(missing)} 項 →")
        for m in missing:
            print(f"   · {m}")
        print("\n→ 請把缺的項一次性問完，補進 gate.json 後重跑本腳本。")
        print("→ 門禁不通過時，禁止產出任何方案內容（協議 1）。")
        sys.exit(1)

    if not confirmed:
        print(f"{NG} 13 項已齊，但《任務規則表》尚未經用戶確認。")
        print("→ 請把規則表發給用戶確認，將 rules_table_confirmed 設為 true 後重跑。")
        sys.exit(1)

    print(f"{OK} 門禁通過：13 項齊全 + 規則表已確認。")

    # ── 第 14 項（2026-09-14 用戶要求「先問用戶要多少」寫進 skill）──
    #    必須有用戶選定的**交付長度**，否則不准往下走。
    #    理由：AI 反覆「不問就自己定長度」→ 用戶三次糾正。所以變成機械檢查。
    delivery = data.get("delivery") or data.get("交付") or data.get("交付規格") or {}
    target = str(
        delivery.get("量級") or delivery.get("目标长度") or delivery.get("目標長度")
        or delivery.get("目標字數") or delivery.get("目标字数") or delivery.get("頁數") or ""
    ).strip()
    if not target:
        print("\n" + "-" * 64)
        print(f"{NG} 缺少『交付長度』—— 規則表必須記錄用戶選定的長度與效果。")
        print()
        print("→ 依門禁第 13 項：**先給用戶「長度 ＋ 效果」選項讓他選**，選完才動筆。")
        print("   ⛔ 禁止開放式地問「你要多長」；必須給具體選項 + 預估篇幅（用戶才有尺寸感）。")
        print("   例：\"delivery\": {\"結構\": \"精煉版\", \"量級\": \"5 頁 Word\", \"字數硬要求\": \"無\"}")
        print("=" * 64)
        sys.exit(1)
    print(f"{OK} 交付長度（用戶已選）：{target}")

    print(f"{OK} 門禁通過：13 項 ＋ 規則表已確認 ＋ 交付長度已定 → 可以進入下一步（事實底稿）。")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{NG} 已中斷（Ctrl+C）。")
        sys.exit(130)
    except Exception as e:
        print(f"\n{NG} 腳本執行出錯：{type(e).__name__}: {e}")
        print("→ 依協議 8（卡死處理）：")
        print("   1) 依上面訊息修正後重跑；")
        print("   2) 若 JSON 格式有問題，用 --help 看輸入範例；")
        print("   3) 仍不行 → 手工核對 13 項門禁齊不齊，在回覆中列出，不要卡在這裡。")
        sys.exit(2)
