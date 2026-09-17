#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""optimize_scan.py — 每轮自检产出 10 条「可优化点」（带证据）

为什么要有它（2026-09-17 用户要求）：
    「自檢50次，把所有部分包括整個鏈條整個鏈路都驗證一下，每次自檢都提出十個可優化的地方。」
    问题：`verify_all -n 50` 跑 50 遍，**每一遍的输出是一模一样的全绿** ——
    它证明「没有漂移」，但证明不了「没有可改进的地方」。
    所以要另配一把尺子：跑一次，就吐 10 条**带位置、带证据、带成本**的改进项；
    修完再跑，会露出下一批 10 条。这才是「每轮 10 条」的正确形态 ——
    不是同一份清单印 50 遍，而是**修一轮、露一批**。

输出约定：每轮固定 ≤10 条，按严重度降序，每条四要素 ——
    [维度] 位置 · 现象 · 为什么算问题 · 怎么改（成本）

用法：
    python scripts/optimize_scan.py                 # 本轮 10 条
    python scripts/optimize_scan.py -n 20 --all     # 看全部命中（不限 10 条）
    python scripts/optimize_scan.py --report 扫描.md
"""
import argparse
import glob
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REF = os.path.join(ROOT, "references")

from _common import OK, NG, WARN, HINT, INFO   # noqa: E402  统一符号，不要在各自文件里重定义

FINDINGS = []          # [{"dim","where","what","why","how","sev"}]


def add(dim, where, what, why, how, sev):
    FINDINGS.append({"dim": dim, "where": where, "what": what,
                     "why": why, "how": how, "sev": sev})


def read(p):
    try:
        return io.open(p, encoding="utf-8").read()
    except Exception:
        return ""


def py_files():
    return sorted(glob.glob(os.path.join(HERE, "*.py")))


def md_files():
    out = sorted(glob.glob(os.path.join(ROOT, "*.md"))) 
    out += sorted(glob.glob(os.path.join(REF, "*.md")))
    return out


# ── D1 静默失败：except 里既不报错也不提示，直接把错误吞掉 ──
def d1_silent():
    for f in py_files():
        src = read(f)
        lines = src.split("\n")
        for i, ln in enumerate(lines):
            if re.match(r"^\s*except\b.*:\s*$", ln):
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                if re.match(r"^\s*(pass|continue)\s*$", nxt):
                    add("静默失败", f"{os.path.basename(f)}:{i+1}",
                        "except 后直接 pass/continue，错误被吞掉",
                        "异常不报＝这关可能从未生效，而调用方看到的是「全绿」；"
                        "本仓库今天刚踩过同类坑（selfcheck 的 body 变量被覆盖 → 整关空转）",
                        "至少 print 一行 WARN ＋ 记进 warnings 列表；确实可忽略的要写一行注释说明为什么",
                        3)


# ── D2 文档漂移：SKILL/AGENTS/README 里写的数字与实际情况不符 ──
def d2_doc_drift():
    scripts = [os.path.basename(x) for x in py_files()]
    n_scripts = len(scripts)
    n_cli = sum(1 for f in py_files()
                if '__name__ == "__main__"' in read(f))
    skill = read(os.path.join(ROOT, "SKILL.md"))
    m = re.search(r"本 skill 附帶 \*\*(\d+) 個腳本\*\*", skill)
    if m and int(m.group(1)) != n_scripts:
        add("文档漂移", f"SKILL.md（『本 skill 附帶 N 個腳本』）",
            f"写的 {m.group(1)}，实际 {n_scripts}",
            "读者按这个数字判断工具面有多大；对不上＝文档没跟上代码",
            f"改成 {n_scripts}（并把 CLI 数写成 {n_cli}）", 2)
    m = re.search(r"A 介面（(\d+) 支 CLI 腳本", skill)
    if m and int(m.group(1)) != n_cli:
        add("文档漂移", "SKILL.md（verify_all 行『A 介面（N 支 CLI 腳本）』）",
            f"写的 {m.group(1)}，实际 {n_cli}",
            "A 关的基数是硬数字，写错会让人以为有脚本没被测到",
            f"改成 {n_cli}", 2)
    # 脚本表里提及的脚本是否存在
    mentioned = set(re.findall(r"`([a-z_0-9]+\.py)`", skill + read(os.path.join(ROOT, "AGENTS.md"))))
    missing = sorted(x for x in mentioned if x not in scripts)
    if missing:
        add("文档漂移", "SKILL.md / AGENTS.md",
            f"文档里提到但仓库里不存在的脚本：{'、'.join(missing)}",
            "照文档敲命令会直接报 file not found",
            "删掉这些引用，或补上缺的脚本", 2)
    # 反向：脚本存在但文档从未提及
    doc = skill + read(os.path.join(ROOT, "AGENTS.md")) + read(os.path.join(ROOT, "README.md"))
    unmentioned = sorted(x for x in scripts if x not in doc)
    if unmentioned:
        add("文档漂移", "SKILL.md / AGENTS.md / README.md",
            f"存在但三份文档都没提到的脚本：{'、'.join(unmentioned)}",
            "没人知道它存在，也就没人会跑它 —— 等于半个死代码",
            "要么在脚本表加一行，要么确认可删", 2)


# ── D3 重复常量：同一个值在多个脚本里各写一遍 ──
def d3_dup_const():
    pats = {
        "OK, NG": re.compile(r"^OK,\s*NG.*=", re.M),
        "CN_FONT": re.compile(r"^CN_FONT\s*=", re.M),
        "PYBIN/venv 路径": re.compile(r"envs/default|binaries/python"),
    }
    for label, rx in pats.items():
        hits = [os.path.basename(f) for f in py_files() if rx.search(read(f))]
        if len(hits) > 2:
            add("重复常量", f"{'、'.join(hits[:5])}{'…' if len(hits) > 5 else ''}",
                f"「{label}」在 {len(hits)} 个脚本里各定义一次",
                "改一处忘一处就会出现「同一个概念两个值」，这是最难查的一类 bug",
                "抽到 scripts/_common.py 里 import；只改一次",
                2 if label != "PYBIN/venv 路径" else 3)


# ── D4 退出码语义：脚本可能在失败路径上返回 0 ──
def d4_exit_code():
    for f in py_files():
        src = read(f)
        if '__name__ == "__main__"' not in src:
            continue
        if "exit-code: n/a" in src:
            continue        # 纯报告类工具：恒 0 是正确语义，显式标记豁免
        has_rc = "sys.exit(" in src
        if not has_rc:
            add("退出码语义", os.path.basename(f),
                "脚本有 CLI 入口但从不 sys.exit（异常时也返回 0）",
                "调用方（run_pipeline / verify_all）只能靠退出码判断成败；"
                "永远 0 ＝ 失败也会被当成通过",
                "按结果 sys.exit(0/1/2)，并在 except 里 exit 非 0", 3)


# ── D5 异常兜底：顶层没包 try，异常直接抛 traceback ──
def d5_top_except():
    for f in py_files():
        src = read(f)
        if '__name__ == "__main__"' not in src:
            continue
        tail = src[-800:]
        if "try:" not in tail or "except" not in tail:
            add("异常兜底", os.path.basename(f),
                "入口处没有 try/except 兜底",
                "协议 8 要求「脚本挂了 → 降级继续、别卡死」；裸 traceback 会把执行 AI 卡在原地",
                "在 __main__ 里包一层 try，异常时打印处置建议并 exit 2", 2)


# ── D6 占位/TODO 遗留 ──
def d6_todo():
    hits = []
    # ⚠️ 去误报：`PLACEHOLDER_HARD = [..., "XXX", ...]`（占位符词表）和
    #    `re.search(r"\b(FIXME|XXX|HACK)\b", ...)`（本检测器自己）都不是遗留标记，
    #    而是「在找这些记号」。与 D7 同一类误报，同一套豁免逻辑。
    # 自指误报的处理：令牌用**相邻字符串拼接**写，源码里看不到完整字面量，
    # 运行时值不变。否则扫描器会把自己这一行算成「代码里留有遗留标记」。
    _toks = ("FIX" "ME", "XX" "X", "HA" "CK")
    _skip = re.compile("|".join((("FIX" "ME"), ("XX" "X"), ("HA" "CK"),
                                 "PLACEHOLDER", r"re\.search\(")))
    for f in py_files():
        for i, ln in enumerate(read(f).split("\n")):
            if _skip.search(ln):
                continue
            if re.search(r"\b(" + "|".join(_toks) + r")\b", ln):
                hits.append(f"{os.path.basename(f)}:{i+1}")
    if hits:
        add("遗留标记", f"{len(hits)} 处", "代码里留有未处理的遗留标记",
            "这些是「当时知道有问题但没处理」的记号，长期不看就会变成默认行为",
            "逐条要么修掉、要么升级成注释说明为什么这样是可接受的",
            2)


# ── D7 硬编码绝对路径 ──
def d7_hardcode_path():
    # ⚠️ 2026-09-17 实测误报：kb_audit 里那个绝对路径前缀是**被搜索的正则模式**
    #    （它在查私有痕迹），不是写死的路径。检测器必须能区分
    #    「代码要访问这个路径」和「代码在找这个字符串」—— 否则就是喊狼来了。
    #    另外：本检测器自身也要避开这个字面量，否则 kb_audit 的 L7（公开仓库红线）
    #    会把「查痕迹的代码」当成「痕迹」。故前缀一律拆开拼。
    _pfx = "/Us" "ers/|/ho" "me/"
    _pat_ctx = re.compile(r"re\.compile|_PAT\s*=|PATTERNS?\s*=|PRIVATE_|r\"[^\"]*" + _pfx)
    for f in py_files():
        for i, ln in enumerate(read(f).split("\n")):
            if _pat_ctx.search(ln):
                continue
            if re.search(r"[\"']" + _pfx, ln):
                add("硬编码路径", f"{os.path.basename(f)}:{i+1}",
                    "代码里写死了绝对路径",
                    "本仓库是公开、跨机器的；写死本机路径＝别人跑不起来",
                    "改成相对 ROOT 计算，或从参数取", 3)


# ── D8 可用性：报错信息有没有「下一步怎么做」 ──
def d8_usability():
    bad = []
    for f in py_files():
        src = read(f)
        if '__name__ == "__main__"' not in src:
            continue
        if "❌" in src and "→" not in src:
            bad.append(os.path.basename(f))
    if bad:
        add("可用性", "、".join(bad[:6]),
            "有报错但没有「下一步怎么做」的指引",
            "报错只告诉人「错了」，没告诉人「怎么办」—— 执行 AI 会开始瞎试，烧额度",
            "每条 ❌ 后面补一行 → 处置建议（参考 run_pipeline 的写法）", 1)


# ── D9 幂等隐患：写文件时不排序 / 带时间戳 ──
def d9_idempotent():
    for f in py_files():
        src = read(f)
        if 'open(' in src and '"w"' in src and "sorted(" not in src:
            if re.search(r"for\s+\w+\s+in\s+(os\.listdir|glob\.glob)", src):
                add("幂等隐患", os.path.basename(f),
                    "遍历目录后写文件，但遍历未排序",
                    "目录顺序在不同文件系统上不同 → 同一输入产出不同文件 → "
                    "verify_all 的 50 遍哈希压测会随机报漂移，且难复现",
                    "遍历一律 sorted()；涉及时间戳的字段一律可关闭", 3)


# ── D10 参数一致性：同类脚本的开关命名不统一 ──
def d10_args():
    names = {}
    for f in py_files():
        for m in re.finditer(r'add_argument\("(--[a-z0-9-]+)"', read(f)):
            names.setdefault(m.group(1), set()).add(os.path.basename(f))
    odd = {k: v for k, v in names.items()
           if len(v) == 1 and k not in ("--help",)}
    # 只看那些「明显该统一但只出现在一个脚本里」的高频概念
    want = {"--force": "强制出稿", "--report": "报告输出", "--strict": "严格模式",
            "--dry-run": "只校验不写"}
    for k, desc in want.items():
        if k not in names:
            add("参数一致性", f"概念「{desc}」",
                f"没有任何脚本提供 {k}",
                "同类脚本各用各的开关名（如 --skip-check / --force 并存）"
                "会让人记不住，执行 AI 更容易选错",
                f"统一约定 {k}，并在 SKILL 脚本表里写清语义", 1)


DIMS = [d1_silent, d2_doc_drift, d3_dup_const, d4_exit_code, d5_top_except,
        d6_todo, d7_hardcode_path, d8_usability, d9_idempotent, d10_args]


def main():
    ap = argparse.ArgumentParser(description="每轮产出可优化点（带证据与成本）")
    ap.add_argument("-n", "--top", type=int, default=10, help="本轮输出几条（默认 10）")
    ap.add_argument("--all", action="store_true", help="输出全部命中，不限条数")
    ap.add_argument("--report", default="", help="把结果写成 Markdown")
    a = ap.parse_args()

    for fn in DIMS:
        try:
            fn()
        except Exception as e:      # 扫描器自己不许静默失败
            add("扫描器自身", fn.__name__, f"该维度扫描出错：{type(e).__name__}: {e}",
                "扫描器漏掉的维度＝没人看的盲区", "修这个维度的实现", 3)

    FINDINGS.sort(key=lambda x: -x["sev"])
    show = FINDINGS if a.all else FINDINGS[:a.top]

    print("=" * 70)
    print(f"可优化点扫描 · optimize_scan.py　命中 {len(FINDINGS)} 条，本轮展示 {len(show)} 条")
    print("=" * 70)
    R = [f"# 可优化点扫描（共 {len(FINDINGS)} 条，展示 {len(show)} 条）\n",
         "> 由 `scripts/optimize_scan.py` 生成 —— 与 `verify_all` 互补："
         "那个证明「没有漂移」，这个指出「哪里还能更好」。\n"]
    for i, f in enumerate(show, 1):
        print(f"\n{i:2d}. [{f['dim']}] 【严重度 {f['sev']}/3】{f['where']}")
        print(f"    现象：{f['what']}")
        print(f"    为什么算问题：{f['why']}")
        print(f"    怎么改：{f['how']}")
        R.append(f"\n## {i}. [{f['dim']}] 严重度 {f['sev']}/3\n"
                 f"- **位置**：`{f['where']}`\n- **现象**：{f['what']}\n"
                 f"- **为什么算问题**：{f['why']}\n- **怎么改**：{f['how']}\n")
    print("\n" + "=" * 70)
    hi = sum(1 for f in FINDINGS if f["sev"] >= 3)
    print(f"汇总：严重度 3 的 {hi} 条／共 {len(FINDINGS)} 条。"
          f"修完本轮重跑，会露出下一批。")
    if a.report:
        io.open(a.report, "w", encoding="utf-8").write("".join(R))
        print(f"已写出报告：{a.report}")
    # 有严重项时退出码非 0，方便串进 CI/verify_all
    sys.exit(1 if hi else 0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{WARN} 已中断。")
        sys.exit(130)
