#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
預算校驗 · budget_check.py  （marketing-playbook 協議 3 自檢單第 7 項）

用途：方案裡的預算表必須「分項加總 = 合計」。這個腳本把它變成機械校驗，
      算錯就直接報錯，不允許交付。

用法：
    python budget_check.py budget.json
    python budget_check.py plan.md          # 自動抓第一個含「金額」的表格
    cat budget.json | python budget_check.py -

輸入 JSON 格式：
{
  "items": [
    {"name": "物料印刷", "amount": 3000, "note": "A4 海報 50 張"},
    {"name": "達人投放", "amount": 8000}
  ],
  "total": 15000,
  "unit_economics": {          // 可選：算盈虧線
    "price": 60,               // 客單價
    "cost": 27,                // 單位成本
    "orders": 500,             // 預計單量
    "fixed_cost": 2000         // 可選：固定成本
  }
}

退出碼：0 = 通過；1 = 不通過
"""

import json
import re
import sys

OK = "✅"
NG = "❌"
WARN = "⚠️"
TOL = 0.01  # 金額容差


def load(path: str):
    if path == "-":
        return json.load(sys.stdin), None
    if path.lower().endswith((".md", ".markdown", ".txt")):
        with open(path, "r", encoding="utf-8") as f:
            return None, f.read()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f), None


def parse_md_table(text: str):
    """從 Markdown 抓「項目 | 金額」表格，回傳 (items, total)"""
    items, total = [], None
    lines = text.splitlines()
    for line in lines:
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        # 跳過表頭與分隔線
        if re.match(r"^[-:\s]+$", cells[0]) or "金額" in cells[1] or "金额" in cells[1] or "预算" in cells[1]:
            continue
        name = cells[0]
        raw = re.sub(r"[¥￥$,\s元]", "", cells[1])
        if not re.match(r"^\d+(\.\d+)?$", raw):
            continue
        amt = float(raw)
        if any(k in name for k in ("合計", "合计", "總計", "总计", "小計", "小计")):
            total = amt
        else:
            items.append({"name": name, "amount": amt})
    return items, total


def main():
    if len(sys.argv) < 2:
        print("用法: python budget_check.py <budget.json|plan.md|->")
        sys.exit(1)

    try:
        data, md = load(sys.argv[1])
    except Exception as e:
        print(f"{NG} 無法讀取輸入：{e}")
        sys.exit(1)

    if md is not None:
        items, total = parse_md_table(md)
        if not items:
            print(f"{NG} 在 Markdown 裡找不到可解析的預算表（需含「| 項目 | 金額 |」欄位）。")
            print("→ 建議改用 JSON 輸入，或確認預算表格式。")
            sys.exit(1)
        data = {"items": items, "total": total}

    items = data.get("items") or []
    if not items:
        print(f"{NG} 預算表為空（items 沒有內容）。")
        sys.exit(1)

    print("=" * 64)
    print("預算校驗")
    print("=" * 64)

    s = 0.0
    for it in items:
        name = str(it.get("name", "(未命名)"))
        amt = float(it.get("amount", 0))
        s += amt
        note = it.get("note")
        suffix = f"   （{note}）" if note else ""
        print(f"  {name:<24} {amt:>12,.2f}{suffix}")

    print("-" * 64)
    print(f"  {'分項加總':<24} {s:>12,.2f}")

    total = data.get("total")
    failed = False

    if total is None:
        print(f"  {'表內合計':<24} {'(未提供)':>12}")
        print(f"{WARN} 沒有填「合計」欄位 → 無法交叉校驗，請補上。")
        failed = True
    else:
        total = float(total)
        print(f"  {'表內合計':<24} {total:>12,.2f}")
        diff = abs(s - total)
        if diff <= TOL:
            print(f"{OK} 分項加總 = 合計（差額 {diff:.2f}）")
        else:
            print(f"{NG} 對不上！差額 {s - total:+,.2f}（分項 {s:,.2f} vs 合計 {total:,.2f}）")
            failed = True

    # 盈虧線
    ue = data.get("unit_economics") or data.get("unitEconomics")
    if ue:
        print("\n" + "-" * 64)
        print("單位經濟與盈虧線")
        print("-" * 64)
        try:
            price = float(ue.get("price", 0))
            cost = float(ue.get("cost", 0))
            orders = float(ue.get("orders", 0))
            fixed = float(ue.get("fixed_cost", 0) or 0)
            if price <= 0:
                print(f"{WARN} 客單價未填或為 0，跳過盈虧測算。")
            else:
                margin = price - cost
                rate = margin / price
                print(f"  客單價 {price:,.2f} ｜ 單位成本 {cost:,.2f} ｜ 單位毛利 {margin:,.2f} ｜ 毛利率 {rate:.1%}")
                if orders:
                    gross = margin * orders
                    print(f"  預計單量 {orders:,.0f} → 總毛利 {gross:,.2f}")
                    if fixed:
                        print(f"  固定成本 {fixed:,.2f} → 淨利 {gross - fixed:,.2f}")
                        if margin > 0:
                            be = fixed / margin
                            print(f"  保本單量 = 固定成本 ÷ 單位毛利 = {be:,.0f} 單"
                                  f"（約為預計單量的 {be / orders:.0%}）")
                        else:
                            print(f"{NG} 單位毛利 ≤ 0，永遠無法保本。")
                            failed = True
                else:
                    print(f"{WARN} 沒填預計單量，無法算總毛利。")
        except Exception as e:
            print(f"{WARN} 盈虧測算失敗：{e}")

    print("=" * 64)
    if failed:
        print(f"{NG} 預算校驗不通過 → 修正後重跑（協議 3 自檢單第 7 項未過）。")
        sys.exit(1)
    print(f"{OK} 預算校驗通過。")
    sys.exit(0)


if __name__ == "__main__":
    main()
