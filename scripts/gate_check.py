#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
门禁校验 · gate_check.py  （marketing-playbook 协议 1）

用途：AI 问完门禁后、动笔写方案前，跑一次这个脚本。
      门禁 13 项有任何一项没填、或《任务规则表》没经用户确认、或**缺「交付长度」（第 14 项）**
      → 直接报错，不准往下走。

用法：
    python gate_check.py gate.json
    cat gate.json | python gate_check.py -     # 从 stdin 读

输入 JSON 格式（字段名可自由，脚本按别名匹配；匹配不到则按顺序兜底）：
{
  "client": "客户名",
  "gate": {
    "卖什么": "川菜馆，人均 60，毛利约 55%",
    "卖给谁": "周边 3 公里上班族",
    ...共 13 项...
  },
  "rules_table_confirmed": true
}

退出码：0 = 通过；1 = 不通过（AI 必须补齐后重跑）
"""

import json
import sys

# 13 项门禁（顺序即标准顺序）+ 别名，用于宽松匹配
GATE_ITEMS = [
    ("卖什么（产品/服务、客单价、毛利）",
     ["卖什么", "卖什么", "品类", "品类", "主营", "主营", "产品", "产品", "服务", "服务",
      "客单价", "客单价", "毛利", "生意", "卖点", "卖点"]),
    ("卖给谁（人群、场景）",
     ["卖给谁", "卖给谁", "客群", "受众", "受众", "目标人群", "目标人群", "人群", "用户", "用户", "场景", "场景"]),
    ("现在什么规模",
     ["规模", "规模", "营收", "营收", "营业额", "营业额", "流水", "GMV", "门店", "门店", "用户数", "用户数",
      "粉丝", "粉丝", "订单", "订单"]),
    ("卡在哪（客户原话）",
     ["卡在哪", "卡点", "卡点", "瓶颈", "瓶颈", "痛点", "痛点", "最大问题", "最大问题", "问题", "问题", "原话", "原话"]),
    ("预算多少",
     ["预算", "预算", "预算区间", "可投入", "投入", "费用", "费用"]),
    ("有什么现成资源",
     ["现成资源", "现成资源", "资源", "资源", "人手", "团队", "团队", "渠道", "供应商", "供应商", "私域"]),
    ("时间要求（死线/节点）",
     ["时间", "时间", "死线", "死线", "节点", "节点", "排期", "截止", "上线", "上线", "deadline", "窗口"]),
    ("硬约束（合规/场地/授权/不能做什么）",
     ["硬约束", "硬约束", "约束", "约束", "合规", "合规", "场地", "场地", "授权", "授权", "红线", "红线", "禁止", "不能"]),
    # ⚠️ 2026-09-17（R6 连锁加盟 + R5 私域视角）：这两件事反复被指出「门禁不问、下游全凭猜」——
    #   但**门禁 13 项是全局不变式**（SKILL／README／流程状态行都写 13），加项会连带改一圈。
    #   → 折中：本项**只加别名**（用户提到就认得），另在 SKILL §0 列为「补充项」建议一并问。
    ("对接人与决策人",
     ["对接人", "对接人", "决策人", "决策人", "负责人", "负责人", "拍板", "老板", "老板", "决策链", "决策链"]),
    ("竞争对手", ["竞争", "竞争", "竞品", "竞品", "对手", "对手", "对标", "对标", "同行"]),
    ("过去试过什么", ["过去", "过去", "试过", "试过", "之前做", "历史", "历史", "复盘", "复盘", "已有经验", "已有经验"]),
    ("怎么算成功（验收标准）",
     ["验收", "验收", "算成功", "成功标准", "成功标准", "KPI", "指标", "指标", "目标", "目标", "考核"]),
    ("目标字数", ["目标字数", "目标字数", "字数", "字数", "页数", "页数", "字数限制", "篇幅"]),
]

OK = "✅"
NG = "❌"
OPT = "⚠️"


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
    # 占位符／「查不到」也算没填（门禁项不接受「不知道」）
    # 注意：「无／没有」**不算**没填 —— 「现成资源：无」「竞争对手：无」是合法答案（2026-09-16 修）
    bad = ["todo", "tbd", "待补", "待补", "待定", "待确认", "待确认", "未知", "不清楚",
           "不确定", "不确定", "暂无", "暂无", "未定", "未确认", "未确认",
           "n/a", "na", "?", "？", "查不到", "未提供", "-", "nil", "null"]
    return s.lower() not in bad


def match_item(gate: dict, aliases: list, used: set):
    """按别名匹配 gate 里的 key；回传 (key, value) 或 (None, None)。

    改进（2026-09-16）：旧版「第一个命中的 key」会在短别名（如「问题」「人群」）上误配。
    现在取「最长命中别名」的 key（完全相等再加权），把误配降到最低。
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
                score = len(al) + (1000 if kl == al else 0)  # 完全相等最优先
                if score > best_score:
                    best_k, best_v, best_score = k, v, score
    return best_k, best_v


USAGE = """用法: python gate_check.py <gate.json|->

输入 JSON（字段名可自由，脚本按别名匹配）：
{
  "client": "客户名",
  "gate": { "卖什么": "...", "卖给谁": "...", ...共 13 项... },
  "delivery": { "结构": "精炼版", "量级": "5 页 Word" },
  "rules_table_confirmed": true
}
退出码：0 通过 ｜ 1 不通过 ｜ 2 脚本错误"""


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
        print(f"{NG} 无法读取输入：{e}")
        sys.exit(1)

    gate = data.get("gate") or data.get("门禁") or data.get("门禁内容") or {}
    if not isinstance(gate, dict) or not gate:
        print(f"{NG} 找不到门禁资料。请在 JSON 里提供 'gate' 物件。")
        sys.exit(1)

    client = data.get("client") or data.get("客户") or data.get("客户") or "(未填客户名)"
    confirmed = bool(
        data.get("rules_table_confirmed")
        or data.get("规则表已确认")
        or data.get("规则表已确认")
    )

    print("=" * 64)
    print(f"门禁校验 · {client}")
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

    # 未被匹配到的多余字段（提示，不算错）
    extra = [k for k in gate.keys() if k not in used]
    if extra:
        print(f"\nℹ️  另有未匹配字段（可能对应上面某项，请人工确认）：{'、'.join(map(str, extra))}")

    print("\n" + "-" * 64)
    print(f"规则表确认状态：{'已确认 ' + OK if confirmed else '尚未确认 ' + NG}")

    print("-" * 64)
    if missing:
        print(f"{NG} 门禁不通过：还缺 {len(missing)} 项 →")
        for m in missing:
            print(f"   · {m}")
        print("\n→ 请把缺的项一次性问完，补进 gate.json 后重跑本脚本。")
        print("→ 门禁不通过时，禁止产出任何方案内容（协议 1）。")
        sys.exit(1)

    if not confirmed:
        print(f"{NG} 13 项已齐，但《任务规则表》尚未经用户确认。")
        print("→ 请把规则表发给用户确认，将 rules_table_confirmed 设为 true 后重跑。")
        sys.exit(1)

    print(f"{OK} 门禁通过：13 项齐全 + 规则表已确认。")

    # ── 答案质量（2026-09-16）：只查「填了没」不够，关键项还要「够不够具体」──
    #    MIN_LEN：低于此长度视为笼统（如「预算：待定」「卡在：没人知道」）→ 方案会失准
    MIN_LEN = {"卡在哪（客户原话）": 12, "卖什么（产品/服务、客单价、毛利）": 8,
               "卖给谁（人群、场景）": 6, "怎么算成功（验收标准）": 8}
    used_q, weak = set(), []
    for label, aliases in GATE_ITEMS:
        k, v = match_item(gate, aliases, used_q)
        if k is not None:
            used_q.add(k)
        if k is not None and is_filled(v) and label in MIN_LEN and len(str(v).strip()) < MIN_LEN[label]:
            weak.append((label, str(v).strip()))
    if weak:
        print("\n" + "-" * 64)
        for label, val in weak:
            print(f"{OPT} {label}：内容过短（「{val}」）—— 填了但太笼统")
        print(f"{OPT} {len(weak)} 项答案过短 —— 建议补具体的数字／场景／客户原话，否则方案会失准")

    # ── 第 14 项（2026-09-14 用户要求「先问用户要多少」写进 skill）──
    #    必须有用户选定的**交付长度**，否则不准往下走。
    #    理由：AI 反复「不问就自己定长度」→ 用户三次纠正。所以变成机械检查。
    delivery = data.get("delivery") or data.get("交付") or data.get("交付规格") or {}
    target = str(
        delivery.get("量级") or delivery.get("目标长度") or delivery.get("目标长度")
        or delivery.get("目标字数") or delivery.get("目标字数") or delivery.get("页数") or ""
    ).strip()
    if not target:
        print("\n" + "-" * 64)
        print(f"{NG} 缺少『交付长度』—— 规则表必须记录用户选定的长度与效果。")
        print()
        print("→ 依门禁第 13 项：**先给用户「长度 ＋ 效果」选项让他选**，选完才动笔。")
        print("   ⛔ 禁止开放式地问「你要多长」；必须给具体选项 + 预估篇幅（用户才有尺寸感）。")
        print("   例：\"delivery\": {\"结构\": \"精炼版\", \"量级\": \"5 页 Word\", \"字数硬要求\": \"无\"}")
        print("=" * 64)
        sys.exit(1)
    print(f"{OK} 交付长度（用户已选）：{target}")

    print(f"{OK} 门禁通过：13 项 ＋ 规则表已确认 ＋ 交付长度已定 → 可以进入下一步（事实底稿）。")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{NG} 已中断（Ctrl+C）。")
        sys.exit(130)
    except Exception as e:
        print(f"\n{NG} 脚本执行出错：{type(e).__name__}: {e}")
        print("→ 依协议 8（卡死处理）：")
        print("   1) 依上面讯息修正后重跑；")
        print("   2) 若 JSON 格式有问题，用 --help 看输入范例；")
        print("   3) 仍不行 → 手工核对 13 项门禁齐不齐，在回复中列出，不要卡在这里。")
        sys.exit(2)
