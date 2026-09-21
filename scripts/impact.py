#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""impact.py — 改一处，自动算出「影响面」（**替代靠人记住跑哪几条**）

为什么要有它（用户 2026-09-18 质问）：
    「**那不应该是修了一个就自己把所有东西都预测好，预计好会影响什么东西吗？
      为什么要多次质检？**」

    这个直觉是对的，而且它就是编译器／类型系统在做的事：
    **改一个函数签名 → 编译器把所有呼叫点列给你**。它之所以能做到，是因为
    **依赖边是明确写在资料里的**（谁 import 谁、类型是什么）。

    而这个仓库原先的依赖边是**散在文字里的**：
      · 「改骨架要同步 paradigm_data」→ 写在 SKILL 的一句话里
      · 「改卡片要跑 case_sections」→ 写在维护纪律表里
      · 「SKILL 里写的脚本数要跟著改」→ 没人写，全靠 optimize_scan 事后抓
    → 于是「影响面」只能靠**人记得**，而人一定会漏。漏了就只能靠**再跑一轮质检**兜。

    本工具就是把那些边**从文字搬进资料**，并提供两条命令：
      `--git`     改完直接跑：读 `git status`，算出「你现在必须重跑什么」
      `--changed` 指定改了哪个文件／哪一类，输出影响面
      `--verify`  不只列清单，**直接把该跑的跑一遍**（可验证，不靠自觉）

用法：
    python scripts/impact.py                 # 自动看 git 改了什么
    python scripts/impact.py --changed scripts/composer.py
    python scripts/impact.py --list          # 列出所有受管对象
    python scripts/impact.py --verify        # 列出后直接执行
"""
import argparse
import fnmatch
import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from _common import OK, NG, WARN, HINT   # noqa: E402

PY = sys.executable

# ═══ 变更 → 影响面 映射（**这就是把「散在文字里的依赖边」搬进资料**）═══
#   must_run  ：必须重跑的校验（不跑＝不知道有没有坏）
#   must_sync ：必须同步改的地方（不改＝下次校验会红灯）
#   why       ：为什么，一句话（给后来人看，避免被当成迷信）
RULES = [
    {
        "match": ["scripts/composer.py"],
        "what": "骨架组装器（章节／打法／注入逻辑）",
        "must_run": [["build_paradigm.py", "--doc-map", "README.md"],
                     ["agent_brief.py"],
                     ["smoke_test.py"]],
        "must_sync": ["scripts/paradigm_data.py 的 SKELETON_HEADS 与 GUIDE"
                      "（新增/删除章节必须同步，否则 build_paradigm 直接退出 1）",
                      "章节编号必须**与实际出现顺序同向**（插了新节要重编号）"],
        "why": "骨架是唯一真相：范式库、README 结构表、AGENT-BRIEF 都由它派生",
        "heavy": True,
    },
    {
        "match": ["scripts/paradigm_data.py"],
        "what": "逐节填写指引（资料层）",
        "must_run": [["build_paradigm.py", "--doc-map", "README.md"],
                     ["agent_brief.py"]],
        "must_sync": ["若新增章节 → 同步 composer 的骨架（两者必须一致）"],
        "why": "它与 composer 是**两份宣告同一件事**的资料，必须对账",
    },
    {
        "match": ["scripts/selfcheck.py"],
        "what": "交付前自检（18 关）",
        "must_run": [["smoke_test.py"], ["kb_audit.py"]],
        "must_sync": ["新增/删除关卡 → 同步 AGENT-BRIEF（关数）与 README §0.3（关清单）",
                      "新加的硬关**先问「这条要求对最轻的那档也成立吗」**——"
                      "已连续五次误伤速览类标杆稿，完整版才强制的走 _hard_if_full()"],
        "why": "自检是唯一拦截层，改它等于改交付门槛",
        "heavy": True,
    },
    {
        "match": ["scripts/_common.py"],
        "what": "跨脚本共用常量",
        "must_run": [["kb_audit.py"]],
        "must_sync": [],
        "why": "所有脚本都 import 它 —— 改坏＝全部崩",
        "heavy": True,
    },
    {
        "match": ["references/00-打法库.md"],
        "what": "116 条打法（打法／案例行／五要素）",
        "must_run": [["kb_audit.py"], ["case_play_index.py", "--fix"], ["smoke_test.py"]],
        "must_sync": ["案例行只接受「品牌关键词@档号」，由脚本解析生成，**不手写文件名**"],
        "why": "打法↔案例是 L2 链路；composer 直接解析这份文件",
    },
    {
        "match": ["references/cases/*.md", "references/cases/"],
        "what": "51 份行业案例卡",
        "must_run": [["case_sections.py", "--fix"], ["case_order.py"],
                     ["case_lint.py"], ["case_upgrade.py"],
                     ["case_play_index.py", "--fix"], ["kb_audit.py"]],
        "must_sync": ["卡片格式见 cases/README.md §四（**14 块**）",
                      "归因提醒（第 9 块）会被 composer 带进交付稿，不是可选项"],
        "why": "案例卡是**给模型看的教材**：教材教错，下游写出来一定错",
    },
    {
        "match": ["references/12-范式库.md"],
        "what": "六档范式库",
        "must_run": [],
        "must_sync": ["⛔ **不要手改这个文件** —— 它由 build_paradigm 生成；"
                      "要改就改 paradigm_data.py，再重跑 build_paradigm"],
        "why": "它是产物不是源头；手改会在下次生成时被覆盖，且造成两份真相",
    },
    {
        "match": ["README.md"],
        "what": "给人看的说明 + 仓库地图",
        "must_run": [["build_paradigm.py", "--doc-map", "README.md"]],
        "must_sync": ["DOCMAP 标记区块内的内容**不要手改**（会被重生成覆盖）；"
                      "要改结构就改 paradigm_data"],
        "why": "结构表是生成物，手写必然过时",
    },
    {
        "match": ["AGENT-BRIEF.md"],
        "what": "给 agent 的单文件快照",
        "must_run": [["agent_brief.py"]],
        "must_sync": ["⛔ 不要手改 —— 它是生成物"],
        "why": "同上；挂在 verify_all 里自动重生成",
    },
    {
        "match": ["SKILL.md"],
        "what": "唯一入口（门禁／八篇／路由表／自检清单）",
        "must_run": [["optimize_scan.py"], ["kb_audit.py"]],
        "must_sync": ["脚本数／CLI 数写在里面 —— 加脚本后要同步（optimize_scan 会抓）",
                      "⚠️ 文件头是 YAML frontmatter，**改开头前先看 `head -3`**，别盲插"],
        "why": "它是入口，数字错了会误导所有读者",
    },
    {
        "match": ["scripts/*.py"],
        "what": "新增／删除脚本",
        "must_run": [["optimize_scan.py"], ["agent_brief.py"]],
        "must_sync": ["SKILL 脚本表补索引 + 更新脚本数/CLI 数",
                      "OK/NG/WARN 常量一律 `from _common import`，**不要在各自档里重定义**",
                      "有 CLI 入口就必须有退出码语义（纯报告类加 `# exit-code: n/a`）"],
        "why": "脚本数与常量重复都是 optimize_scan 的检查项",
    },
    {
        "match": ["scripts/verify_all.py"],
        "what": "全链路验证器（A–F 关）",
        "must_run": [["smoke_test.py"]],
        "must_sync": ["FIXERS 里每一支都必须**幂等**（第 2 轮起哈希零漂移）"],
        "why": "改验证器本身＝改变门槛，且它自己也在被测",
    },
    {
        "match": ["references/*.md"],
        "what": "知识库编号文档（00–13）",
        "must_run": [["kb_audit.py"], ["file_meta.py"]],
        "must_sync": ["全仓统一**简体**（2026-09-18）；改了语言纪律要跑 `lang_unify.py` 复检",
                      "改文件名/编号要跑 rename_tidy.py（旧文件名不得残留）"],
        "why": "L1 文件引用可解析 ＋ L7 私有痕迹都靠这条链",
    },
    {
        "match": ["scripts/repo_hygiene.py"],
        "what": "仓库冗余／卫生扫描",
        "must_run": [["smoke_test.py"], ["optimize_scan.py"]],
        "must_sync": [
            "`JUNK_NAMES`／`JUNK_DIR_PAT`／`DERIVED_EXT` 是判据的唯一真相；"
            "`find_orphans`／`find_derived`／`find_junk` 三者**必须共用 `_junk_why()`** "
            "—— 两处各写一份判据早晚漂移，然后同一件事会报两次",
            "加进 verify_all 的 F 关时**不得带 `--clean`**：回归验证不该有副作用",
        ],
        "why": "它是唯一查「文件该不该存在」的尺子；判据散了就等于没有尺子",
    },
    {
        "match": ["scripts/lang_unify.py", "scripts/_common.py"],
        "what": "语言统一／繁体判据",
        "must_run": [["smoke_test.py"], ["optimize_scan.py"]],
        "must_sync": [
            "⛔ **不要**把这些「判据类」繁体顺手转简：`t2s_data.py` 的 `T2S_PAIRS`、"
            "`_common.py` 的 `TRAD_HINT`、`smoke_test.py` 的繁体负向夹具 —— "
            "它们本身就是「哪些字是繁体」的尺子，转了会让尺子反过来把简体判成繁体"
            "（2026-09-18 实测：简体标杆稿当场被判 67 种「繁体字」）",
            "新增判据类繁体一律放 `_common.py` 并用 `# lang-keep-trad` 护栏，不要在各自文件里重定义",
        ],
        "why": "判据不是内容；机械转换对判据的语义方向是反的",
    },
    {
        "match": ["references/范例/"],
        "what": "交付稿样张／输入文件样张",
        "must_run": [["smoke_test.py"], ["verify_all.py"]],
        "must_sync": [
            "⚠️ `便利店开学季战役-交付稿.md` 是 **3 支脚本的测试夹具**"
            "（`smoke_test`／`verify_all`／`depth_check` 都直接读它）—— 改它等于改测试",
            "`-任务规则表.json` 是 `build_docx --rules` 的输入、`-预算表.json` 是 "
            "`budget_check` 的输入、`-分工记录.json` 是 `role_check` 的输入；"
            "`（示例）区域茶饮新品牌-任务规则表.json` 是 `kb_audit` L4 的夹具",
            "**样张一律简体**（现在全仓都是简体，这条只剩「别手改样张」的意思）",
            "已删除的旧样张（骨架示例／交付稿 .docx）**不得再被引用**；"
            "要看 Word 版改为当场生成：`build_docx.py <该 .md>`",
        ],
        "why": "样张同时是「教材」与「测试夹具」—— 两重身分，改动影响面比看起来大",
    },
]

# 这些档「改了必须跑全量」—— 因为它们是别人的依赖，影响面无法枚举
FULL_REGRESSION = ["verify_all.py"]


def read(p):
    return io.open(p, encoding="utf-8").read()


def git_changed():
    try:
        out = subprocess.run(["git", "status", "--short", "--untracked-files=all"],
                             cwd=ROOT, capture_output=True, text=True).stdout
    except Exception:
        return []
    fs = []
    for ln in out.split("\n"):
        m = re.match(r"^\s*\S+\s+(.+)$", ln)
        if m:
            p = m.group(1).strip().strip('"')
            if p and not p.startswith(".workbuddy"):
                fs.append(p)
    return fs


def hit(rule, path):
    """这条规则命不命中这个路径。回传**命中的那个 pattern**（没命中回 None）——
    回传 pattern 而不是 True，是为了让呼叫端能比「谁更长＝更具体」。"""
    for pat in rule["match"]:
        if fnmatch.fnmatch(path, pat) or path.startswith(pat.rstrip("*")) or path == pat:
            return pat
    return None


def specificity(pat):
    """越具体＝越该赢。回传可比较的元组。

    判据是**通配符之前的字面前缀长度**（完全没有通配符＝全长），平手再比
    「去掉通配符后的净长度」。

    为什么不用「整条 pattern 的字符数」：`references/*.md`（15 字）比
    `references/范例/`（14 字）长，但前者只锁定 11 个字面前缀、后面全放行；
    后者 14 个字**全部是字面**。纯比长度会让「放行范围更大」的那条赢 —— 判反了。
    """
    prefix = re.split(r"[*?\[]", pat, 1)[0]
    literal = pat.replace("*", "").replace("?", "")
    return (len(prefix), len(literal))


def best_rule(path):
    """**最长键优先**：命中多条时取最具体的那条（见 `specificity()`）。

    为什么不是「第一条命中就停」：`fnmatch` 的 `*` 会跨 `/`，所以
    `scripts/*.py` 会把 `scripts/repo_hygiene.py` 遮掉、
    `references/*.md` 会把 `references/范例/` 遮掉。**判据是「谁更具体」，不是「谁先写」。**
    （与 AGENTS.md §四之一 记的「短键遮蔽长键」同类 —— 那次是 `play_overrides` 的 `'VI'`。）
    """
    best, best_key = None, (-1, -1)
    for r in RULES:
        pat = hit(r, path)
        if pat is None:
            continue
        key = specificity(pat)
        if key > best_key:
            best, best_key = r, key
    return best


def main():
    ap = argparse.ArgumentParser(description="改一处 → 自动算出影响面")
    ap.add_argument("--changed", default="", help="你改了哪个文件（可多次指定，逗号分隔）")
    ap.add_argument("--list", action="store_true", help="列出所有受管对象")
    ap.add_argument("--verify", action="store_true", help="列出影响面后直接跑一遍")
    a = ap.parse_args()

    if a.list:
        print("=" * 70)
        print("受管对象（改了它 → 影响面可枚举）")
        print("=" * 70)
        for r in RULES:
            print(f"\n· {r['what']}")
            print(f"    文件：{' / '.join(r['match'])}")
            print(f"    为什么：{r['why']}")
        print(f"\n{HINT} 不在表里的档（如新增的临时档）→ 保守起见直接跑 "
              f"`python {' '.join(FULL_REGRESSION)} -n 50`。")
        sys.exit(0)

    if a.changed:
        files = [x.strip() for x in a.changed.split(",") if x.strip()]
    else:
        files = git_changed()
        if not files:
            print(f"{OK} git 工作区是干净的 —— 没有变更，也就没有影响面要算。")
            sys.exit(0)
        print("=" * 70)
        print(f"从 git 看到 {len(files)} 个变更，正在算影响面…")
        print("=" * 70)

    matched, runs, syncs, heavy = [], [], [], False
    for f in files:
        # **最长键优先**（见 best_rule 的说明）。2026-09-18 前是「命中第一条就 break」，
        # 通用规则因此会遮蔽专门规则 —— 改 repo_hygiene 时算不出它真正该跑的 smoke_test。
        r = best_rule(f)
        if r:
            if r["what"] not in [x["what"] for x in matched]:
                matched.append(r)
            for cmd in r["must_run"]:
                if cmd not in runs:
                    runs.append(cmd)
            for s in r["must_sync"]:
                if s not in syncs:
                    syncs.append(s)
            if r.get("heavy"):
                heavy = True

    print(f"\n【你改了什么】")
    for f in files[:20]:
        print(f"  · {f}")
    if len(files) > 20:
        print(f"  …共 {len(files)} 个")

    print(f"\n【影响面 · 必须重跑】")
    if runs:
        for cmd in runs:
            print(f"  {HINT} python scripts/{' '.join(cmd)}")
    else:
        print(f"  （表里没有专属项 → 保守起见跑全量）")
    print(f"  {HINT} python scripts/verify_all.py -n 50   ← **最后一关，永远要跑**"
          + ("（本次有重档变更，务必）" if heavy else ""))

    if syncs:
        print(f"\n【影响面 · 必须同步改（不改＝下次校验红灯）】")
        for s in syncs:
            print(f"  ⚠️ {s}")

    if not matched:
        print(f"\n{WARN} 没有命中映射表 —— 说明这是个**还没建模的依赖边**。"
              f"\n{HINT} 处理完后，请把它加进 `scripts/impact.py` 的 RULES —— "
              f"**每补一条边，下次就少一次盲目重跑。**")

    if a.verify:
        print("\n" + "=" * 70)
        print("直接执行（--verify）")
        print("=" * 70)
        bad = 0
        for cmd in runs:
            print(f"\n→ python scripts/{' '.join(cmd)}")
            rc = subprocess.call([PY, os.path.join(HERE, cmd[0])] + list(cmd[1:]), cwd=ROOT)
            if rc != 0:
                bad += 1
                print(f"   {NG} rc={rc}")
        print("\n" + "-" * 70)
        print(f"{OK if not bad else NG} 轻量校验：{len(runs)-bad}/{len(runs)} 通过")
        print(f"{HINT} 记得最后跑 **verify_all -n 50**（含 50 遍幂等 + 端到端出稿）。")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"{NG} impact 执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
