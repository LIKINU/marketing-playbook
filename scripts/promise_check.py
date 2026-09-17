#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""promise_check.py — 「文档承诺 ↔ 实际执行」对账关

为什么要有它（2026-09-17，三个 agent 审出来的元规律）：
    三个 agent（BCG／贝恩／4A）各独立审一遍，31 条候选里有 **9 条是同一个病**：
    **能力写在文档里，但没有一条链路真的执行它。**
    · `09` 说「不许形容词堆砌」→ 脚本一直没有 AI 腔词表
    · `SKILL` 说「风险要挂失败归因」→ 脚本反而拦这个编号
    · `SKILL` 承诺了「核心结论卡片／2.3／7.3／附件 A–E」→ composer 根本不生成
    · `paradigm_data` 的 must 说「要写主动放弃了什么」→ 零脚本消费
    · `04-失败归因总库` 有 34 条失败预演 → 零消费
    · 打法库的「难度」字段 → 解析进内存又丢掉
    跟之前那批 bug 同族：**文档承诺 ≠ 机械执行**。

本脚本做三件**可机械化**的对账（承诺本身是散文，无法全自动，所以只做能机械化的部分）：
    ① **字段消费**：composer 解析了打法库的哪些字段？每个是否**真的被印进输出**？
       （专抓「解析进内存又丢掉」这一类——「难度」「不适用」就是实测踩到的）
    ② **参考文件消费**：references/ 下每个文件，是否**有被某支脚本真的读到**？
       （专抓「46,010 字的库零消费」这一类）
    ③ **骨架承诺消费**：`paradigm_data.GUIDE` 里每节的 `must` 约定，在 selfcheck 里
       有没有对应的**可判定关卡**？（must 里用了粗体**必须**的点，最好都有脚本管）

用法：
    python scripts/promise_check.py                 # 全量对账
    python scripts/promise_check.py --report 对账.md

退出码：0 无未消费；1 有（默认只报、不阻，毕竟有些「零消费」是故意的）
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import OK, NG, WARN, HINT   # noqa: E402  统一符号（不要在各自文件里重定义）


def read(p):
    return io.open(p, encoding="utf-8").read()


def py_files():
    return sorted(glob.glob(os.path.join(HERE, "*.py")))


# 解析端用的「内部字段」：这些是解析/路由用的原始材料，本来就不用印进输出
_INTERNAL_FIELDS = {"raw", "cases_raw", "cases", "case_line", "id", "major", "name"}


def field_consumption():
    """① composer 解析了哪些字段、每个是否被印进输出。

    ⚠️ 2026-09-17 实测误报并修正：① 输出端写的是 `p.get('difficulty')`（**单引号**），
       初版只查双引号 → 把明明已输出的字段全判成「未输出」；② `raw/cases_raw` 这类
       是解析用的中间材料，本来就不该进输出 —— 列入 `_INTERNAL_FIELDS` 豁免。
    """
    src = read(os.path.join(HERE, "composer.py"))
    keys = sorted(set(re.findall(r'p\["(\w+)"\]\s*=', src)))
    m = re.search(r"def play_block\(.*?(?=\ndef )", src, re.S)
    lite = re.search(r"def build_lite\(.*?(?=\ndef )", src, re.S)
    skel = re.search(r"def build_skeleton\(.*?(?=\ndef )", src, re.S)
    out_src = (m.group(0) if m else "") + (lite.group(0) if lite else "") \
        + (skel.group(0) if skel else "")
    missing = []
    for k in keys:
        if k in _INTERNAL_FIELDS:
            continue
        # 同时认 p["k"] / p['k'] / p.get("k") / p.get('k') 四种写法
        pat = (r'p\s*\[\s*[\"\']' + re.escape(k) + r'[\"\']\s*\]'
               r'|p\.get\(\s*[\"\']' + re.escape(k) + r'[\"\']')
        if not re.search(pat, out_src):
            missing.append(k)
    return keys, missing


# 这些档**本来就是给人（或给执行 AI）读的参考册**，不该被脚本消费 —— 属「仅供人工」豁免
_HUMAN_FACING = {
    "01-接案输出模板.md": "写方案时给人看的逐章指南",
    "02-多Agent分工简报.md": "五份给人复制的角色简报",
    "10-文案与物料样本库.md": "给人抄的文案母版",
    "13-顶级机构对标标准.md": "对标量表，给人打分定位用",
    "11-防返工交付协议.md": "交付铁律，给人与执行 AI 读",
    "07-质量范式-便利店开学季案.md": "质量标尺范例",
}
# 这些档**是知识资产，本来就该被脚本消费** —— 零消费＝真问题（元规律的实证）
_MUST_CONSUME = {
    "04-失败归因总库.md": "46,010 字、34 条失败预演；R1 的贝恩 agent 已指出它零消费，待接入 composer --premortem",
}


def reference_consumption():
    """② references/*.md 顶层档，是否有脚本读到（用文件名在脚本源码里出现判定）。

    ⚠️ 2026-09-17 实测误报并修正：01/02/10/13 这类是**人读的参考册**，被脚本读到
       才奇怪 —— 不能一律当「零消费」。所以分三类：
         · _HUMAN_FACING（仅供人工，豁免）  · _MUST_CONSUME（该消费，零消费＝真问题）
         · 其余（有脚本读最好，没读只提醒）
    """
    refs = sorted(glob.glob(os.path.join(REF, "*.md")))
    # ⚠️ 「提到文件名」≠「读了内容」。这三支脚本只是在**注释/描述串**里提到文件名，并没有真的读：
    #    file_meta（文件名索引器）、promise_check（就是本脚本自己）、relocate_06（一次性迁移，
    #    只在一行注释里点名）。不排除它们，「零消费」就会被误判成「已消费」（引用 ≠ 消费）。
    _NON_CONSUMER = {"file_meta.py", "promise_check.py", "relocate_06.py"}
    scripts_src = "\n".join(read(f) for f in py_files()
                              if os.path.basename(f) not in _NON_CONSUMER)
    unreads, should_miss, exempt = [], [], []
    for f in refs:
        base = os.path.basename(f)
        if base in scripts_src:
            continue
        if base in _HUMAN_FACING:
            exempt.append(base)
        elif base in _MUST_CONSUME:
            should_miss.append(base)
        else:
            unreads.append(base)
    cases_globbed = bool(re.search(r"references.*cases|CASES\s*=", scripts_src))
    return unreads, should_miss, exempt, cases_globbed


# 判据对账表（curated，防误报）：R1 期间逐项补上、并被「selfcheck 脚本」承载的判据。
# 一旦有人把对应的关卡删掉，这张表就会把「承诺又变回零执行」抓出来 —— 它是回归守卫。
_CONTRACTS = {
    "为什么这么做须含实质": "至少含一条实质",
    "执行摘要门槛": "执行摘要不达标",
    "AI 腔拦截": "AI 腔",
    "场景章深度": "场景章内容不达标",
    "Big Idea 判据": "Big Idea",
    "利益相关者章": "利益相关者",
    "Red Team 定长三条": "Red Team",
    "洞察萃取": "洞察萃取",
    "主动放弃 ≥2": "「主动放弃了什么」不足",
    "议题树 H 被引用": "议题树",
    "交叉引用有效性": "指向不存在的章节",
    "施工语气拦截": "给 AI 的施工说明",
    "自检单防伪": "自检单防伪",
}


def must_consumption():
    """③ 判据对账：`_CONTRACTS` 里每个承诺，selfcheck 里必须有对应的可判定关。

    为什么不用「扫 GUIDE.must 的关键词」：那会把 38 节都误报成「没有关卡」——
    must 是散文，散文的可判定约定和 selfcheck 的检查词不会字面重合。
    所以改用 **curated 对账表**：承诺 → 判据关键词，显式、可回归、零误报。"""
    sc = read(os.path.join(HERE, "selfcheck.py"))
    uncovered = [name for name, kw in _CONTRACTS.items() if kw not in sc]
    return len(_CONTRACTS), uncovered


def main():
    ap = argparse.ArgumentParser(description="「文档承诺 ↔ 实际执行」对账关")
    ap.add_argument("--report", default="")
    a = ap.parse_args()

    print("=" * 68)
    print("文档承诺 ↔ 实际执行 · 对账")
    print("=" * 68)
    findings = []
    R = ["# 文档承诺 ↔ 实际执行 · 对账\n"]

    # ① 字段消费
    keys, missing = field_consumption()
    print(f"\n【1】字段消费（composer 解析了 {len(keys)} 个字段）")
    R.append(f"\n## ① 字段消费（{len(keys)} 个字段）\n")
    if missing:
        print(f"  {NG} 解析进内存却**没被印进输出**的字段：{'、'.join(missing)}")
        findings.append(f"字段被解析却未输出：{'、'.join(missing)}")
        R.append(f"- ❌ 解析进内存却没被印进输出：{'、'.join(missing)}"
                 f"（这正是「难度」当年踩过的那类坑）\n")
    else:
        print(f"  {OK} 每个被解析的字段都进了输出")
        R.append(f"- ✅ 每个被解析的字段都进了输出\n")

    # ② 参考文件消费
    unreads, should_miss, exempt, cases_globbed = reference_consumption()
    print(f"\n【2】参考文件消费（references/ 顶层 {len(glob.glob(os.path.join(REF, '*.md')))} 档）")
    R.append(f"\n## ② 参考文件消费\n")
    if should_miss:
        for b in should_miss:
            print(f"  {NG} **该消费却零消费**：{b} —— {_MUST_CONSUME[b]}")
            R.append(f"- ❌ 该消费却零消费：`{b}` —— {_MUST_CONSUME[b]}\n")
        findings.append(f"该消费却零消费：{'、'.join(should_miss)}")
    if unreads:
        print(f"  {WARN} 没有脚本读到（未列入豁免，需人确认）：{'、'.join(unreads)}")
        R.append(f"- ⚠️ 没有脚本读到（未列入豁免）：{'、'.join(unreads)}\n")
    if exempt:
        print(f"  {OK} 仅供人工（豁免，正确）：{len(exempt)} 档")
        R.append(f"- ✅ 仅供人工（豁免）：{'、'.join(exempt)}\n")
    if not should_miss and not unreads:
        print(f"  {OK} 除豁免外，每个文件都至少被一支脚本读到")
        R.append(f"- ✅ 除豁免外，每个文件都至少被一支脚本读到\n")
    print(f"  {OK if cases_globbed else WARN} cases/ 由 glob 加载：{cases_globbed}")
    R.append(f"- cases/ 由 glob 加载：{cases_globbed}（kb_audit 的 L2 另验其可达性）\n")

    # ③ 判据对账
    total_must, uncovered = must_consumption()
    print(f"\n【3】判据对账（{_CONTRACTS.__len__()} 项承诺）")
    R.append(f"\n## ③ 判据对账\n")
    if uncovered:
        for name in uncovered:
            print(f"  {NG} 承诺有、关卡没有：{name}")
            R.append(f"- ❌ 承诺有、关卡没有：{name}\n")
        findings.append(f"{len(uncovered)} 项承诺没有可判定关：{'、'.join(uncovered[:4])}")
    else:
        print(f"  {OK} {total_must} 项承诺全部有对应关卡")
        R.append(f"- ✅ {total_must} 项承诺全部有对应关卡\n")

    print("\n" + "=" * 68)
    if findings:
        print(f"{WARN} 对账差异 {len(findings)} 项（见上）。建议：能机械化的补关卡，"
              f"属「仅供人工」的标明豁免 —— **不要让它静默挂著**。")
        for x in findings:
            print(f"   · {x}")
        print("=" * 68)
        sys.exit(1)
    print(f"{OK} 对账一致：承诺的都有执行。")
    if a.report:
        io.open(a.report, "w", encoding="utf-8").write("".join(R))
        print(f"已写出：{a.report}")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{WARN} 已中断。")
        sys.exit(130)
    except Exception as e:
        print(f"\n{NG} promise_check 执行出错：{type(e).__name__}: {e}")
        print(f"{HINT} 依协议 8：修正后重跑。")
        sys.exit(2)
