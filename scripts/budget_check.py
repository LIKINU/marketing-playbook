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


AMT_KEYS = ("金額", "金额", "預算", "预算", "費用", "费用", "成本", "單價", "单价", "價格", "价格")
NAME_KEYS = ("分項", "分项", "項目", "项目", "名稱", "名称", "物料", "行動", "行动", "類別", "类别", "品項", "品项")


def _parse_amt(s: str):
    """把單元格解析成金額（容忍 **粗體**、¥、千分位、「萬/万」）。解析不了回 None。"""
    if s is None:
        return None
    t = re.sub(r"[¥￥$*`,\s元]", "", str(s))
    m = re.match(r"^(\d+(?:\.\d+)?)(萬|万)?$", t)
    if not m:
        return None
    v = float(m.group(1))
    return v * 10000 if m.group(2) else v


def parse_md_table(text: str):
    """從 Markdown 抓「項目 | 金額」表格，回傳 (items, total)。

    改進（2026-09-16）：舊版寫死「金額在第 2 列」，遇到 skill 自帶的 3 列表
    （`| # | 分項 | 金額 |`）會取錯列、且表頭行被當成資料 → 整表解析失敗。
    現在逐個表格區塊：先由表頭關鍵詞定金額列，定不到就選「多數行可解析成金額」的那列；
    再定名稱列；並支援粗體與「萬」。
    """
    tables = list(_iter_tables(text))
    # 第一遍：只認「表頭含『金額』」的表（這才是預算表）；第二遍才退而求其次
    for rows in tables:
        r = _extract_budget(rows, require_money=True)
        if r:
            return r
    for rows in tables:
        r = _extract_budget(rows, require_money=False)
        if r:
            return r
    return [], None


def _iter_tables(text):
    """把 Markdown 切成一個一個表格（已去掉分隔行）。"""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if "|" not in lines[i]:
            i += 1
            continue
        blk = []
        while i < len(lines) and "|" in lines[i]:
            blk.append(lines[i])
            i += 1
        rows = [[c.strip() for c in raw.strip().strip("|").split("|")] for raw in blk]
        rows = [r for r in rows if not all(re.match(r"^[-:\s]*$", c or "") for c in r)]
        if len(rows) >= 2:
            yield rows


def _extract_budget(rows, require_money):
    """從一個表格抽出 (items, total)；不是預算表就回 None。"""
    header = rows[0]
    if require_money:
        amt_idx = next((j for j, c in enumerate(header) if "金額" in c or "金额" in c), -1)
    else:
        amt_idx = next((j for j, c in enumerate(header) if any(k in c for k in AMT_KEYS)), -1)
        if amt_idx < 0:
            ncol = max(len(r) for r in rows[1:])
            tally = [(sum(1 for r in rows[1:] if j < len(r) and _parse_amt(r[j]) is not None), j)
                     for j in range(ncol)]
            tally = [(c, j) for c, j in tally if c > 0]
            if tally:
                amt_idx = max(tally)[1]
    if amt_idx < 0:
        return None
    nums = sum(1 for r in rows[1:] if amt_idx < len(r) and _parse_amt(r[amt_idx]) is not None)
    if nums < 2:            # 真預算表至少 2 個金額行（擋掉「渠道表」也有預算列的情況）
        return None
    name_idx = next((j for j, c in enumerate(header) if any(k in c for k in NAME_KEYS)), -1)
    if name_idx < 0 or name_idx == amt_idx:
        name_idx = 1 if (len(header) > 2 and amt_idx != 1) else 0
    items, total = [], None
    for r in rows[1:]:
        amt = _parse_amt(r[amt_idx]) if amt_idx < len(r) else None
        if amt is None:
            continue
        name = r[name_idx].strip("* ") if (name_idx < len(r) and name_idx != amt_idx) else ""
        if any(k in name for k in ("合計", "合计", "總計", "总计", "小計", "小计")):
            total = amt
        else:
            items.append({"name": name or f"項 {len(items) + 1}", "amount": amt})
    return (items, total) if items else None


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("用法: python budget_check.py <budget.json|plan.md|->")
        print("  校驗「分項加總 = 合計」；可吃 JSON、含預算表的 Markdown，或 stdin(-)")
        sys.exit(0)
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

    # ── R2-8：從成稿裡**回讀**單位經濟（原實現只認 JSON 的 unit_economics，
    #    於是成稿裡寫的「單客獲取成本 X 元」永遠不會被複算 —— 寫錯也全綠）
    if md is not None and not data.get("unit_economics"):
        _ue = {}
        for _k, _pat in (("cac", r"單客獲取成本|单客获取成本|CAC"),
                         ("ltv", r"生命週期價值|生命周期价值|LTV"),
                         ("payback", r"回本週期|回本周期")):
            _m = re.search(_pat + r"[^\n]{0,20}?(\d+(?:\.\d+)?)", md)
            if _m:
                _ue[_k] = float(_m.group(1))
        if len(_ue) >= 2:
            data["unit_economics"] = _ue
            print(f"→ 從成稿回讀到單位經濟：{_ue}（將參與複算）")
        if _ue.get("cac") and _ue.get("ltv"):
            _ratio = _ue["ltv"] / _ue["cac"]
            _mark = OK if _ratio >= 3 else NG
            print(f"  {_mark} LTV / CAC = {_ratio:.2f}（判據 ≥3；<1 是賣一單虧一單）")

    # ── R2-9：百分比基數與口徑混用（原實現只查「分項加總＝合計」一條）
    #    ⚠️ 2026-09-17 实测误报并修正：初版把「/月」与「/年」的检查做成**整份文档**范围，
    #       于是标杆稿（月度人力 + 年度投放分列在不同表、各自标注清楚）被误判。
    #       口径只能在**同一张表内**比较 —— 改成按表块判断。
    #       同时分两级：占比加总≠100% 是**算术错误**（拦）；月/年混列是**启发式**（只警告）。
    oc_bad = []
    WARNS = []       # 启发式警告（不拦）
    if md is not None:
        # 切出所有表块（连续以 | 开头的行）
        _blocks, _cur = [], []
        for _ln in md.split("\n"):
            if _ln.strip().startswith("|"):
                _cur.append(_ln)
            elif _cur:
                _blocks.append("\n".join(_cur)); _cur = []
        if _cur:
            _blocks.append("\n".join(_cur))
        for _blk in _blocks:
            _lines = [l for l in _blk.split("\n") if l.strip().startswith("|")]
            if len(_lines) < 2:
                continue
            _hdr = _lines[0]
            # ① 佔比列加總 ≠ 100%（同一张表内）
            if re.search(r"占比|佔比|比例", _hdr) and not re.search(r"金額|金额|元", _hdr):
                _vals = []
                for _ln in _lines[1:]:
                    if re.match(r"^\|[-:\s|]+\|$", _ln.strip()):
                        continue
                    _cs = [c.strip() for c in _ln.strip().strip("|").split("|")]
                    if len(_cs) >= 2:
                        _v = _cs[1].replace("%", "").replace("％", "").strip()
                        if re.match(r"^\d+(\.\d+)?$", _v):
                            _vals.append(float(_v))
                if len(_vals) >= 2 and abs(sum(_vals) - 100) > 0.5:
                    _msg = f"占比列加总 {sum(_vals):.1f}% ≠ 100%（可能是基数不一致）"
                    print(f"  {NG} 口径问题：{_msg}")
                    oc_bad.append(_msg)
            # ② 同一张表内月/年混列（警告，不拦）
            if re.search(r"/月|每月|月度", _blk) and re.search(r"/年|每年|年度|全年", _blk):
                print(f"  {WARN} 同一张表内同时出现月/年口径，未标明换算方式")
                WARNS.append("同一张表内月/年口径混用 —— 请标明换算或拆表")

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
    if WARNS:
        for _w in WARNS:
            print(f"{WARN} {_w}")

    total = data.get("total")
    failed = bool(oc_bad)      # 口徑問題也算失敗（R2-9）

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
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{WARN} 已中斷（Ctrl+C）。")
        sys.exit(130)
    except Exception as e:
        print(f"\n{NG} 腳本執行出錯：{type(e).__name__}: {e}")
        print("→ 依協議 8（卡死處理）：")
        print("   1) 依上面訊息修正後重跑；")
        print("   2) 若 Markdown 表格解析失敗，改用 JSON 輸入；")
        print("   3) 仍不行 → 手工核對「分項加總 = 合計」，在交付說明裡註明未經腳本校驗。")
        sys.exit(2)
