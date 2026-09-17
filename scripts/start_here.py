#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""start_here.py — 开新会话的第一条命令（**用「查」代替「读」**）

为什么要有它（用户 2026-09-17 指出）：
    「**下一次不是还要重新读**」
    这是真问题：仓库已经长到 references/ 8.2M、14 份编号参考 ＋ 52 份行业案例 ＋
    293 节范式库 ＋ 116 条打法。**每次开新会话，执行 AI 都得从头读一遍** ——
    整理目录只解决「人找得到」，没解决「AI 读得少」。

它怎么解决：
    把「读什么」从**通读**变成**查询**。三条子命令：
      --client "客户情况…"  → 只输出「**该读哪几份、读哪一节、多少字**」＋「**明确不要读什么**」
      --grep  "关键词"      → 跨库检索，只回传命中的行（**替代通读整份文件**）
      --files               → 全库清单＋字数（让你知道预算，再决定读不读）

    ⛔ 它的输出**不是文件**，是**给执行 AI 的阅读清单**。
       读完这份清单（约 20 行），就知道这单案子该碰哪 2000 字、不该碰哪 40 万字。

用法：
    python scripts/start_here.py --client "武汉光谷川菜馆，一家店，人均 60，客流掉三成"
    python scripts/start_here.py --grep "场景化"
    python scripts/start_here.py --files
"""
import argparse
import glob
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REF = os.path.join(ROOT, "references")
CASES = os.path.join(REF, "cases")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import OK, NG, WARN, HINT   # noqa: E402  统一符号（不要在各自文件里重定义）

# 「明确不要读」清单：这些档**只能按需查单节**，通读是浪费
NEVER_READ_THROUGH = {
    "03-方法论操作手册.md": "13 万字、111 个模型 —— 只按需查单个模型码，不通读",
    "00-打法库.md": "116 条打法 —— 只读 §0 一页速查表，其余按 §编号查",
    "04-失败归因总库.md": "12 模式 ＋ 34 条预演 —— 由 `composer --internal` 自动注入相关条目",
}
# 推荐给「不确定」时的第一份（最小可用组合）
STARTER = ["SKILL.md", "references/12-范式库.md"]


def read(p):
    try:
        return io.open(p, encoding="utf-8").read()
    except Exception:
        return ""


def n_chars(p):
    return len(re.sub(r"\s", "", read(p)))


def human(n):
    return f"{n/10000:.1f} 万字" if n >= 10000 else f"{n} 字"


def load_map():
    try:
        return json.loads(read(os.path.join(HERE, "knowledge_map.json")))
    except Exception:
        return {}


def infer_case_file(client, kmap):
    """**复用 composer 已验过的 `infer_industry`**，不自己写一份。

    ⚠️ 教训（本脚本第一次写时踩的）：我原本用 bigram 相似度猜行业档，结果
    「武汉光谷川菜馆」被判成 `25-潮玩文创IP.md` —— **噪声当信号**。
    `knowledge_map.industry_to_cases` 是**最长关键词优先**的确定性映射（已被 kb_audit 验过），
    直接用它才对。**同一个判断不要有两份实现。**
    """
    if not client:
        return "", 0
    sys.path.insert(0, HERE)
    try:
        import composer as C
        f = C.infer_industry({"卖什么": client, "卖给谁": client, "品类": client}, kmap)
        if f:
            # ⚠️ 映射表里的值**不带 .md 后缀**（如 "03-美妆个护"）—— 第一次没补后缀，
            #    于是每个客户都判成「匹配度不足」。补上再验存在性。
            base = os.path.basename(f)
            for cand in (os.path.join(CASES, base + ".md"),
                         os.path.join(CASES, base),
                         os.path.join(REF, base + ".md"),
                         os.path.join(REF, base)):
                if os.path.exists(cand):
                    return cand, 99
    except Exception as e:
        # 不许静默：行业判定失败会被读成「这个客户没有对应行业档」，
        # 而实际是判定本身出错 —— 两者对下游的含义完全不同。
        print(f"  {WARN} 行业判定失败（{type(e).__name__}）—— 请手工指定案例档", file=sys.stderr)
    return "", 0


def matched_routes(client, kmap):
    hits = []
    for r in kmap.get("路由规则", []):
        got = [k for k in r["kw"] if k in client]
        if got:
            hits.append((len(got), got, r["方向"]))
    hits.sort(key=lambda x: -x[0])
    return hits


def cmd_client(client, _):
    kmap = load_map()
    print("=" * 68)
    print("开新会话第一步 · 这单案子该读什么（**别通读**）")
    print("=" * 68)

    total = sum(n_chars(f) for f in glob.glob(os.path.join(REF, "**", "*.md"), recursive=True)
                if os.path.isfile(f))
    print(f"\n全库体量：references/ 约 {human(total)}（通读一遍＝烧掉大量上下文）")
    print(f"本清单把「要读的」压到 3 份以内。\n")

    print("【① 必读（按这个顺序）】")
    n = 0
    for rel in STARTER:
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            n += 1
            print(f"  {n}. {rel}　（{human(n_chars(p))}）")
    note = ("· SKILL.md：只读 §0 门禁 13 项 ＋ §二路由表 ＋ §六自检清单，**不用通读**\n"
            "· 12-范式库.md：**只读你这单对应的那一档**（速览／标准／大赛／B端／G端／投标），约 1 万字")
    print(f"     {note}")

    hits = matched_routes(client, kmap)
    if hits:
        print("\n【② 客户状况命中的打法方向（去 00-打法库.md 按 §编号查，不要通读）】")
        for cnt, kws, dirs in hits[:4]:
            print(f"  · 命中 {cnt} 个关键词（{'、'.join(kws[:4])}）→ {'、'.join(dirs[:6])}")

    cf, score = infer_case_file(client, kmap)
    if cf and score >= 4:
        print(f"\n【③ 最相关的行业案例档】{os.path.relpath(cf, ROOT)}（{human(n_chars(cf))}）")
        print("     → **只读「案例清单」那一段**（30 秒扫完），挑中 1–3 条再看「深度拆解」")
    else:
        print(f"\n【③ 行业案例】匹配度不足，**先别读案例库**；等门禁问完行业再来查（--grep 更快）")

    print("\n【④ 明确不要通读】")
    for f, why in NEVER_READ_THROUGH.items():
        print(f"  ⛔ {f} —— {why}")
    print("  ⛔ 另外 51 个**非本行业**案例档")

    print("\n【⑤ 想查某个词，用检索代替通读】")
    print('  python scripts/start_here.py --grep "场景化"')

    print("\n【⑥ 下一步】")
    print("  python scripts/flow.py --dir 案子目录     # 看目前卡在哪一步")
    print("  python scripts/composer.py --rules rules.json --out skeleton.md --tier 标准 --internal skeleton.internal.md")
    print("=" * 68)


def cmd_grep(kw, _):
    print("=" * 68)
    print(f'跨库检索：「{kw}」（**用查代替读**）')
    print("=" * 68)
    hits, files = 0, {}
    for f in sorted(glob.glob(os.path.join(REF, "**", "*.md"), recursive=True)):
        if not os.path.isfile(f):
            continue
        for i, ln in enumerate(read(f).split("\n"), 1):
            if kw in ln:
                hits += 1
                rel = os.path.relpath(f, ROOT)
                files.setdefault(rel, []).append((i, ln.strip()[:96]))
    if not hits:
        print(f"{WARN} 没命中。换个词，或先跑 --files 看有哪些档。")
        return
    for rel, ls in list(files.items())[:14]:
        print(f"\n{rel}（{len(ls)} 处）")
        for i, s in ls[:3]:
            print(f"   {i}: {s}")
        if len(ls) > 3:
            print(f"   …另有 {len(ls)-3} 处")
    print(f"\n{HINT} 共 {hits} 处、{len(files)} 个文件。**只读命中的那几行，不要通读整份文件。**")


def cmd_files(_, __):
    print("=" * 68)
    print("全库清单（**先看字数，再决定读不读**）")
    print("=" * 68)
    rows = []
    for f in sorted(glob.glob(os.path.join(REF, "*.md"))):
        rows.append((os.path.relpath(f, ROOT), n_chars(f)))
    cn = sum(n_chars(f) for f in glob.glob(os.path.join(CASES, "*.md")))
    rows.append((f"references/cases/（{len(glob.glob(os.path.join(CASES, '*.md')))} 档）", cn))
    for f in sorted(glob.glob(os.path.join(REF, "范例", "*.md"))):
        rows.append((os.path.relpath(f, ROOT), n_chars(f)))
    for rel, n in sorted(rows, key=lambda x: -x[1]):
        flag = "  ⛔ 别通读" if os.path.basename(rel) in NEVER_READ_THROUGH else ""
        print(f"  {human(n):>10}  {rel}{flag}")
    print(f"\n  {'合计':>10}  {human(sum(n for _, n in rows))}")


def main():
    ap = argparse.ArgumentParser(description="开新会话第一步：告诉你该读什么、明确不要读什么")
    ap.add_argument("--client", default="", help="客户情况一段话（门禁答案或 brief）")
    ap.add_argument("--grep", default="", help="跨库检索（替代通读）")
    ap.add_argument("--files", action="store_true", help="全库清单＋字数")
    a = ap.parse_args()
    if a.grep:
        cmd_grep(a.grep, None)
    elif a.files:
        cmd_files(None, None)
    elif a.client:
        cmd_client(a.client, None)
    else:
        cmd_client("", None)
        print(f"\n{WARN} 没给 --client，上面是通用清单。给了客户情况会更准。")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{WARN} 已中断。")
        sys.exit(130)
    except Exception as e:
        print(f"\n{NG} start_here 执行出错：{type(e).__name__}: {e}")
        print(f"{HINT} 依协议 8：直接用 SKILL.md 的「第 -1 步」手工判断要读哪几份，不要卡在这里。")
        sys.exit(2)
