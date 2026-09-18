#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
事实底稿校验 · facts_check.py

为什么要有这支脚本（2026-09-19 · C 批「体系1 #5 事实底稿来源分层与版本」）：

  事实底稿是**全案的原料仓**：后面每一章都只从它取材（见 `01-接案输出模板.md` 附件 C）。
  但原先它只要「有这份文件、含九个小节」——**没有一条字段是「来源／口径／时点」**。
  后果不是难看，是**没法回溯**：
    · 两个看起来一样的数字（日均 42 单）口径不同，被放在一起算出错的加法；
    · 半年后数字过期了没人知道；
    · 客户问「你这个数哪来的」，只能回去翻聊天记录。

  `selfcheck.py` 跑的是**交付稿**，管不到这份**内部文档**（协议：内部文档不进交付稿）。
  所以单独一支来查它。

用法：
    python facts_check.py 事实底稿.md
    python facts_check.py 事实底稿.md --template   # 只印表头模板
退出码：0 = 通过；1 = 不通过；2 = 用法错误

判据（可判定）：
  ① 事实表必须有四栏：来源层级｜口径｜时点｜可信度（**查表头行**，不查整节）
  ② 每条事实行的四栏都非空（空栏＝这条事实没有出处）
  ③ 可信度取值必须是【已核实】／【行业认知】／【未核实】三者之一（自己发明档位不算）
  ④ 底稿必须写**版本**与**变更记录**
  ⑤ 【未核实】的事实**必须有对应的核实动作**（写清「怎么核、什么时候核」）
     —— 否则它就会以「事实」的样子流进方案
"""

import argparse
import os
import re
import sys

OK, NG, WARN, INFO = "✅", "❌", "⚠️", "ℹ️"
FOUR = ["来源层级", "口径", "时点", "可信度"]
CRED = ["已核实", "行业认知", "未核实"]


def read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def tables(text):
    """把 markdown 里的表格切成 [(表头, [数据行])]。"""
    out, hdr, rows = [], None, []
    for ln in text.split("\n"):
        s = ln.strip()
        if s.startswith("|"):
            if "---" in s:
                continue
            c = cells(s)
            if hdr is None:
                hdr = c
            else:
                rows.append(c)
        else:
            if hdr is not None:
                out.append((hdr, rows))
            hdr, rows = None, []
    if hdr is not None:
        out.append((hdr, rows))
    return out


def col(hdr, *keys):
    for i, c in enumerate(hdr):
        if any(k in c for k in keys):
            return i
    return -1


def cell(row, i):
    return row[i].strip() if 0 <= i < len(row) else ""


def main():
    ap = argparse.ArgumentParser(description="事实底稿校验（来源层级／口径／时点／可信度＋版本）")
    ap.add_argument("path", nargs="?", help="事实底稿 markdown")
    ap.add_argument("--template", action="store_true", help="只印表头模板")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    if a.template or not a.path:
        print("事实底稿事实表（照这个表头填，四栏缺一不可）：\n")
        print("| 事实（原话／数字） | 来源层级 | 口径 | 时点 | 可信度 |")
        print("|---|---|---|---|---|")
        print("| 日均 42 单 | 一手·客户后台 | 收银小票逐单，含退款 | 2026-08-01 至 08-31 | 【已核实】 |")
        print("\n来源层级：一手（客户后台／原话／现场观察）> 二手（报告／平台公开数据）> 推断（自己算的）")
        print("可信度：【已核实】／【行业认知】／【未核实】（第三者不得进对外结论）")
        print("另需一张「版本｜日期｜改了什么｜为什么改｜谁改的」变更记录表。")
        sys.exit(0 if a.path or a.template else 2)

    if not os.path.exists(a.path):
        print(f"{NG} 找不到文件：{a.path}")
        sys.exit(2)
    t = read(a.path)
    errs, warns = [], []

    # ① 找「带四栏的事实表」——按表头找，不按整节找（同 selfcheck 的教训：
    #    查「列在不在」必须查表头行，查整节会被正文里提到的词骗过去）。
    fact_tables, seen_any4 = [], []
    for hdr, rows in tables(t):
        hit = [k for k in FOUR if any(k in c for c in hdr)]
        if hit:
            seen_any4.append((hdr, rows, hit))
            if len(hit) == len(FOUR):
                fact_tables.append((hdr, rows))

    if not fact_tables:
        if seen_any4:
            _h, _r, _hit = seen_any4[0]
            errs.append(f"事实表四栏不全：只找到 {('／'.join(_hit))}，缺 "
                        f"{('／'.join(k for k in FOUR if k not in _hit))}")
        else:
            errs.append("没有找到带「来源层级｜口径｜时点｜可信度」四栏的事实表 —— "
                        "底稿里的事实必须逐条带出处（否则后面没法回溯）")

    # ②③ 逐行查空栏 + 可信度取值
    n_row, n_empty, n_badcred = 0, 0, 0
    bad_rows, unc_rows = [], []
    for hdr, rows in fact_tables:
        i_cred = col(hdr, "可信度")
        for r in rows:
            n_row += 1
            blanks = [k for k in FOUR if not cell(r, col(hdr, k))]
            if blanks:
                n_empty += 1
                bad_rows.append((cell(r, 0)[:24], blanks))
            v = cell(r, i_cred)
            if v and not any(c in v for c in CRED):
                n_badcred += 1
                bad_rows.append((cell(r, 0)[:24], [f"可信度写成「{v[:12]}」"]))
            if "未核实" in v:
                # 连同**可信度那一格的原文**一起记下 —— ⑤ 只判这一格，不判整行
                #  （初版扫整行时，「口径」格里写「未向校方确认」的「确认」把漏项放过了）。
                unc_rows.append((r, v))
    if n_empty:
        errs.append(f"{n_empty} 条事实有空白栏（共 {n_row} 条）—— 空栏＝这条事实没有出处")
    if n_badcred:
        errs.append(f"{n_badcred} 条可信度取值不在【已核实／行业认知／未核实】里")

    # ④ 版本与变更记录
    if not re.search(r"版本", t):
        errs.append("底稿没有「版本」记录 —— 说不清「当时是按哪一版做的」")
    if not re.search(r"变更记录|变更历史", t):
        errs.append("底稿没有「变更记录」表（版本｜日期｜改了什么｜为什么改｜谁改的）")

    # ⑤ 【未核实】必须自带核实动作 —— **判据只看「可信度」那一格**。
    #    ⚠️ 2026-09-19 初版扫整行，结果「口径」格里写「未向校方确认」里的「确认」
    #       就把这条**漏过去了**（判据读到了别的格）。**判断某一格的内容，就只看那一格。**
    #    约定：`【未核实：9/22 前找学生会核实】` 合格；光写 `【未核实】` 不合格。
    for r, c in unc_rows:
        if not re.search(r"核实|去核|待核|核对|确认|去问", c) or len(re.sub(r"[\s【】]", "", c)) <= 4:
            warns.append(f"【未核实】没写核实动作：「{cell(r, 0)[:28]}」"
                         f"（把动作写进**可信度那一格**：如【未核实：9/22 前找学生会核实】——"
                         f"否则它会以「事实」的样子流进方案）")

    if not a.quiet:
        print("=" * 64)
        print(f"事实底稿校验 · {os.path.basename(a.path)}")
        print("=" * 64)
        print(f"  四栏皆备的事实表：{len(fact_tables)} 张｜事实 {n_row} 条"
              f"｜空格 {n_empty} 处｜【未核实】{len(unc_rows)} 条")
        for m in errs:
            print(f"  {NG} {m}")
        for m in warns[:8]:
            print(f"  {WARN} {m}")
        if bad_rows:
            print("  （举例，最多 5 条）")
            for k, why in bad_rows[:5]:
                print(f"     · {k}：缺 {('／'.join(why))}")
        print("-" * 64)
    if errs:
        print(f"{NG} 不通过：{len(errs)} 类问题。**处置**：")
        print("   ① 缺四栏 → 给事实表补表头 `来源层级|口径|时点|可信度`（`--template` 有现成模板）；")
        print("   ② 空栏 → 逐条补齐；**不知道就写「待核」并给核实动作**，不要留空；")
        print("   ③ 可信度写法 → 只认【已核实】／【行业认知】／【未核实】三档，自己发明的不算；")
        print("   ④ 缺版本与变更记录 → 加两张表（版本号＋「版本|日期|改了什么|为什么改|谁改的」）；")
        print("   ⑤ 补完重跑本脚本；**不过就别进第 2 步**（底稿是全案原料仓）。")
        sys.exit(1)
    print(f"{OK} 通过：四栏齐、可信度合规、版本与变更记录在。"
          + (f"（{len(warns)} 条提醒）" if warns else ""))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(130)
    except Exception as e:
        print(f"{NG} 脚本执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
