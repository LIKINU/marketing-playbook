#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
预算校验 · budget_check.py  （marketing-playbook 协议 3 自检单第 7 项）

用途：方案里的预算表必须「分项加总 = 合计」。这个脚本把它变成机械校验，
      算错就直接报错，不允许交付。

用法：
    python budget_check.py budget.json
    python budget_check.py plan.md          # 自动抓第一个含「金额」的表格
    cat budget.json | python budget_check.py -

输入 JSON 格式：
{
  "items": [
    {"name": "物料印刷", "amount": 3000, "note": "A4 海报 50 张"},
    {"name": "达人投放", "amount": 8000}
  ],
  "total": 15000,
  "unit_economics": {          // 可选：算盈亏线
    "price": 60,               // 客单价
    "cost": 27,                // 单位成本
    "orders": 500,             // 预计单量
    "fixed_cost": 2000         // 可选：固定成本
  }
}

退出码：0 = 通过；1 = 不通过
"""

import json
import re
import sys

OK = "✅"
NG = "❌"
WARN = "⚠️"
TOL = 0.01  # 金额容差


def load(path: str):
    if path == "-":
        return json.load(sys.stdin), None
    if path.lower().endswith((".md", ".markdown", ".txt")):
        with open(path, "r", encoding="utf-8") as f:
            return None, f.read()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f), None


AMT_KEYS = ("金额", "金额", "预算", "预算", "费用", "费用", "成本", "单价", "单价", "价格", "价格")
NAME_KEYS = ("分项", "分项", "项目", "项目", "名称", "名称", "物料", "行动", "行动", "类别", "类别", "品项", "品项")


def _parse_amt(s: str):
    """把单元格解析成金额（容忍 **粗体**、¥、千分位、「万/万」）。解析不了回 None。"""
    if s is None:
        return None
    t = re.sub(r"[¥￥$*`,\s元]", "", str(s))
    m = re.match(r"^(\d+(?:\.\d+)?)(万|万)?$", t)
    if not m:
        return None
    v = float(m.group(1))
    return v * 10000 if m.group(2) else v


def parse_md_table(text: str):
    """从 Markdown 抓「项目 | 金额」表格，回传 (items, total)。

    改进（2026-09-16）：旧版写死「金额在第 2 列」，遇到 skill 自带的 3 列表
    （`| # | 分项 | 金额 |`）会取错列、且表头行被当成资料 → 整表解析失败。
    现在逐个表格区块：先由表头关键词定金额列，定不到就选「多数行可解析成金额」的那列；
    再定名称列；并支持粗体与「万」。
    """
    tables = list(_iter_tables(text))
    # 第一遍：只认「表头含『金额』」的表（这才是预算表）；第二遍才退而求其次
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
    """把 Markdown 切成一个一个表格（已去掉分隔行）。"""
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
    """从一个表格抽出 (items, total)；不是预算表就回 None。"""
    header = rows[0]
    if require_money:
        amt_idx = next((j for j, c in enumerate(header) if "金额" in c or "金额" in c), -1)
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
    if nums < 2:            # 真预算表至少 2 个金额行（挡掉「渠道表」也有预算列的情况）
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
        if any(k in name for k in ("合计", "合计", "总计", "总计", "小计", "小计")):
            total = amt
        else:
            items.append({"name": name or f"项 {len(items) + 1}", "amount": amt})
    return (items, total) if items else None


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("用法: python budget_check.py <budget.json|plan.md|->")
        print("  校验「分项加总 = 合计」；可吃 JSON、含预算表的 Markdown，或 stdin(-)")
        sys.exit(0)
    if len(sys.argv) < 2:
        print("用法: python budget_check.py <budget.json|plan.md|->")
        sys.exit(1)

    try:
        data, md = load(sys.argv[1])
    except Exception as e:
        print(f"{NG} 无法读取输入：{e}")
        sys.exit(1)

    if md is not None:
        items, total = parse_md_table(md)
        if not items:
            print(f"{NG} 在 Markdown 里找不到可解析的预算表（需含「| 项目 | 金额 |」字段）。")
            print("→ 建议改用 JSON 输入，或确认预算表格式。")
            sys.exit(1)
        data = {"items": items, "total": total}

    # ── R2-8：从成稿里**回读**单位经济（原实现只认 JSON 的 unit_economics，
    #    于是成稿里写的「单客获取成本 X 元」永远不会被复算 —— 写错也全绿）
    if md is not None and not data.get("unit_economics"):
        _ue = {}
        # ⚠️ 2026-09-17 修 BUG（投资人视角第 1 条，实测会崩）：
        #   原写法 `_pat + r"[^\n]{0,20}?(\d+)"` —— **捕获组在第三个分支里**，
        #   一旦文字被前两个分支（单客获取成本／生命周期价值）命中，group(1) 就是 None，
        #   float(None) → TypeError，脚本 exit 2。改成**整组加括号**，三个分支都带捕获。
        for _k, _pat in (("cac", r"(?:单客获取成本|单客获取成本|CAC)"),
                         ("ltv", r"(?:生命周期价值|生命周期价值|LTV)"),
                         ("payback", r"(?:回本周期|回本周期|回本周期\(月\))")):
            _m = re.search(_pat + r"[^\n]{0,40}?(\d+(?:\.\d+)?)", md)
            if _m and _m.group(1):
                _ue[_k] = float(_m.group(1))
        # 读不到 CAC 或 LTV → 报出来（原先静默跳过，等于「没算」也算过）
        for _need in ("cac", "ltv"):
            if _need not in _ue:
                print(f"  {NG} 成稿里读不到「{_need.upper()}」—— 单位经济无法复算，请补齐五项")
        if len(_ue) >= 2:
            data["unit_economics"] = _ue
            print(f"→ 从成稿回读到单位经济：{_ue}（将参与复算）")
        if _ue.get("cac") and _ue.get("ltv"):
            _ratio = _ue["ltv"] / _ue["cac"]
            _mark = OK if _ratio >= 3 else NG
            print(f"  {_mark} LTV / CAC = {_ratio:.2f}（判据 ≥3；<1 是卖一单亏一单）")

    # ── R2-9：百分比基数与口径混用（原实现只查「分项加总＝合计」一条）
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
            # ① 占比列加总 ≠ 100%（同一张表内）
            if re.search(r"占比|占比|比例", _hdr) and not re.search(r"金额|金额|元", _hdr):
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
        print(f"{NG} 预算表为空（items 没有内容）。")
        sys.exit(1)

    print("=" * 64)
    print("预算校验")
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
    print(f"  {'分项加总':<24} {s:>12,.2f}")
    if WARNS:
        for _w in WARNS:
            print(f"{WARN} {_w}")

    total = data.get("total")
    failed = bool(oc_bad)      # 口径问题也算失败（R2-9）

    if total is None:
        print(f"  {'表内合计':<24} {'(未提供)':>12}")
        print(f"{WARN} 没有填「合计」字段 → 无法交叉校验，请补上。")
        failed = True
    else:
        total = float(total)
        print(f"  {'表内合计':<24} {total:>12,.2f}")
        diff = abs(s - total)
        if diff <= TOL:
            print(f"{OK} 分项加总 = 合计（差额 {diff:.2f}）")
        else:
            print(f"{NG} 对不上！差额 {s - total:+,.2f}（分项 {s:,.2f} vs 合计 {total:,.2f}）")
            failed = True

    # 盈亏线
    ue = data.get("unit_economics") or data.get("unitEconomics")
    if ue:
        print("\n" + "-" * 64)
        print("单位经济与盈亏线")
        print("-" * 64)
        try:
            price = float(ue.get("price", 0))
            cost = float(ue.get("cost", 0))
            orders = float(ue.get("orders", 0))
            fixed = float(ue.get("fixed_cost", 0) or 0)
            if price <= 0:
                print(f"{WARN} 客单价未填或为 0，跳过盈亏测算。")
            else:
                margin = price - cost
                rate = margin / price
                print(f"  客单价 {price:,.2f} ｜ 单位成本 {cost:,.2f} ｜ 单位毛利 {margin:,.2f} ｜ 毛利率 {rate:.1%}")
                if orders:
                    gross = margin * orders
                    print(f"  预计单量 {orders:,.0f} → 总毛利 {gross:,.2f}")
                    if fixed:
                        print(f"  固定成本 {fixed:,.2f} → 净利 {gross - fixed:,.2f}")
                        if margin > 0:
                            be = fixed / margin
                            print(f"  保本单量 = 固定成本 ÷ 单位毛利 = {be:,.0f} 单"
                                  f"（约为预计单量的 {be / orders:.0%}）")
                        else:
                            print(f"{NG} 单位毛利 ≤ 0，永远无法保本。")
                            failed = True
                else:
                    print(f"{WARN} 没填预计单量，无法算总毛利。")
        except Exception as e:
            print(f"{WARN} 盈亏测算失败：{e}")

    print("=" * 64)
    if failed:
        print(f"{NG} 预算校验不通过 → 修正后重跑（协议 3 自检单第 7 项未过）。")
        sys.exit(1)
    print(f"{OK} 预算校验通过。")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{WARN} 已中断（Ctrl+C）。")
        sys.exit(130)
    except Exception as e:
        print(f"\n{NG} 脚本执行出错：{type(e).__name__}: {e}")
        print("→ 依协议 8（卡死处理）：")
        print("   1) 依上面讯息修正后重跑；")
        print("   2) 若 Markdown 表格解析失败，改用 JSON 输入；")
        print("   3) 仍不行 → 手工核对「分项加总 = 合计」，在交付说明里注明未经脚本校验。")
        sys.exit(2)
