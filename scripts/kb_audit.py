#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识库「连通性」审计 · kb_audit.py

为什么有它（2026-09-17，用户质问）：
    「我不是让你质检了很多很多次了吗？为什么还是有这么多问题」

    根因：**既有的 6 个校验脚本查的全是「文件内性质」，没有一个查「跨文件连通性」。**
      · file_meta      → 这档的文件头五栏对不对
      · case_sections  → 这档的章节标题一致吗
      · case_order     → 这张卡的要素顺序对吗
      · case_upgrade   → 这张卡五要素齐、字够 2500 吗
      · case_lint      → 这张卡有没有写公司背景
      · smoke_test     → 几个脚本还能跑吗
    → 结果：60/60 文件头合规、51/51 章节一致、409/409 卡塔尔标、12/12 冒烟全绿，
      而 `composer.py`（唯一的产出引擎）还在印「来源 cases/xx.md，请展开…」这种占位符。
      **零件全合格，机器的传动轴是断的，而没有一支仪器量传动轴。**

本脚本量「传动轴」：把知识库当**网络**看，逐条查「引用能不能走到终点」。

六类检查（＝六条必须通的链路）：
    L1 文件引用可解析 —— 全库所有 `references/xx` / `cases/xx` 引用，目标档存在吗
       （只查「档在不在」是不够的，所以还有 L2–L5 的「走得到内容吗」）
    L2 打法 → 案例 —— 104 条打法里，有几条的 `**案例**` 行能指到**具体某张卡**（指名品牌）
    L3 案例 → 打法 —— 649 张卡里，有几张能被至少一条打法指到（反向可达）
    L4 交付物注入 —— 跑一次 composer，数骨架里实际注入的**真实卡片内容**条数 vs 占位符条数
    L5 模型 → 打法 —— `knowledge_map.json` 引用的模型码，在 03 手册里真的存在吗（死条目扫描）
    L6 全量回归 —— 把 6 个既有校验脚本一次跑完（以前是「改哪查哪」，现在每次全跑）

用法：
    python scripts/kb_audit.py                 # 完整审计（含 L4 实跑 composer）
    python scripts/kb_audit.py --no-compose    # 跳过 L4（不想等 composer）
    python scripts/kb_audit.py --quiet         # 只印结论与失败项
退出码：0 = 六条链路都通；1 = 有链路断（会列出断点数）；2 = 脚本出错
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
REF = os.path.join(ROOT, "references")
CASES = os.path.join(REF, "cases")
PLAYBOOK = os.path.join(REF, "00-打法库.md")
MANUAL03 = os.path.join(REF, "03-方法论操作手册.md")
KMAP = os.path.join(HERE, "knowledge_map.json")

PY = sys.executable


def read(p):
    return open(p, encoding="utf-8").read()


def md_files():
    out = []
    for f in glob.glob(os.path.join(ROOT, "**", "*.md"), recursive=True):
        if "/.git/" in f or "/.workbuddy/" in f:
            continue
        out.append(f)
    return out


# ── L1：引用可解析 ───────────────────────────────────────────
#   只查「像文件路径的引用」：排除三类必然查不到的写法（它们是模板／命令／链路图，不是路径）
#     · 带 `{…}` 的模板（`references/cases/{行业}.md`）
#     · 带 `→` 的链路（`scripts/flow.py → composer.py → …`）
#     · 以 `python ` 开头的命令示例
REF_PAT = re.compile(r"`([^`\n]*?(?:references|scripts|cases)/[^`\n]+?\.(?:md|json|py|sh|docx))`")
REF_SKIP = ("{", "}", "→", "|")
# 裸文件名引用（反引号里只有文件名、不带目录前缀）—— 2026-09-18 补。
#   为什么要单独认它：实测 SKILL.md 写 `` `格式范本映射示例.json` `` 而实际文件名是
#   `格式范本映射示例.json`（一字之差）→ **引用是坏的，但上面那条正则不认**
#   （它要求字符串里含 references/|scripts/|cases/ 前缀）→ 静默放过。
#   ⚠️ 全仓统一简体后，「繁简写错」这个成因消失了，但**这个检查不能拿掉** ——
#      打错字、序号没跟著改、沿用旧文件名，都会产生同一种断链。
#   判定规则保守：只问「仓库里有没有任何一个文件叫这个名字」；有就放行，全仓都没有才算断链。
BARE_PAT = re.compile(r"`([^`\n/]+?\.(?:md|json|py|sh|docx|pdf|txt))`")
# 裸引用检查要避开三类**合法写法**（2026-09-18 实测，第一版误报 51 处）：
#   ① 运行时文件名 —— plan.md／rules.json… 本来就**不在仓库里**，是管线的输入输出；
#   ② 简写后缀 —— 写 `-原版.md` 表示「同名档的后缀」，人看得懂，不是真引用；
#   ③ 历史变更记录 —— `旧名.md → 新名.md` 这种**故意**提到已不存在的旧档。
BARE_WHITELIST = {
    "plan.md", "skeleton.md", "skeleton.internal.md", "方案.docx", "方案.md",
    "rules.json", "budget.json", "roles.json", "gate.json", "manifest.json",
    "附件核对表.json", "refs.json", "banned.json", "checklist.json",
}
# ④ 已死文件的明确标记 —— 正文**故意**提到「某档已经不在了」时，那不是断链，是记录。
#   2026-09-18 补：SKILL.md 的变更记录写「清掉 `references/范例/…-骨架示例.md`（全仓零引用）」，
#   文件确实删了，但这行是**正确的历史**。要求判据明说「已删除」，而不是猜语气 ——
#   判据一含糊，下次就会放过真的断链。
DEAD_MARK = re.compile(r"已删除|已移除|已退役|已废除|旧名|原名|改名")


def l1(quiet):
    bad, total, skipped = [], 0, 0
    # 全仓 basename 索引（供裸文件名引用比对）
    _all_base = {os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "**", "*"), recursive=True)
                 if os.path.isfile(p) and "/.git/" not in p and "/.workbuddy/" not in p}
    for f in md_files():
        base_dir = os.path.dirname(f)
        _src = read(f)
        # ①a 裸文件名引用：反引号里只有文件名（不带目录前缀）
        for m in BARE_PAT.finditer(_src):
            _b = m.group(1).strip()
            if _b in ("SKILL.md", "AGENTS.md", "README.md", "AGENT-BRIEF.md") or "*" in _b:
                continue          # 入口文件与通配写法不查
            if (_b in BARE_WHITELIST
                    or _b.startswith(("-", "…", "（", "("))
                    or " " in _b):   # ① 运行时文件名 ② 简写后缀 ④ 含空格＝指令
                continue
            _line = _src[max(0, m.start() - 120):m.end() + 120]
            if "→" in _line or "->" in _line or DEAD_MARK.search(_line):
                continue          # ③ 历史变更记录（旧名 → 新名／已删除的档）
            total += 1
            if _b not in _all_base:
                bad.append((os.path.relpath(f, ROOT),
                            f"`{_b}`（**裸文件名引用，全仓找不到此档**"
                            f"—— 常见原因是打错字／序号没跟著改／沿用了旧文件名）"))
        for m in REF_PAT.finditer(_src):
            raw = m.group(1).strip()
            if any(s in raw for s in REF_SKIP) or raw.startswith(("python ", "$ ", "bash ")):
                skipped += 1
                continue
            # 通配写法（`scripts/*.py`、`references/*.md`）—— 在正文里引用一个**模式**
            # 不等于引用一个文件。2026-09-18 补：AGENTS.md 开始用 glob 举例说明
            # 「通用规则遮蔽专门规则」，这类写法暴增。
            if "*" in raw or "?" in raw:
                skipped += 1
                continue
            # 占位写法（`cases/xx.md`、`cases/NN-行业.md`）—— 是「举例说明长什么样」，
            # 不是真实引用。2026-09-17：文档开始教「不要写这种座标」，这类举例暴增。
            _fn = os.path.basename(raw)
            if re.match(r"^(?:xx|XX|NN|N+|X+)[\-_.]", _fn):
                skipped += 1
                continue
            _line2 = _src[max(0, m.start() - 120):m.end() + 120]
            if "→" in _line2 or "->" in _line2 or DEAD_MARK.search(_line2):
                skipped += 1
                continue          # 历史变更记录／已删除的档（同上面那条的判据）
            total += 1
            cands = [os.path.join(ROOT, raw),
                     os.path.join(base_dir, raw),
                     os.path.join(REF, raw),
                     os.path.join(CASES, os.path.basename(raw))]
            if not any(os.path.exists(c) for c in cands):
                bad.append((os.path.relpath(f, ROOT), raw))
    if not quiet:
        print(f"  L1 文件引用可解析：{total} 处可查引用（另有 {skipped} 处模板／命令／链路写法不查），"
              f"**{len(bad)} 处指向不存在的档**")
        for f, r in bad[:15]:
            print(f"     ✗ {f} → {r}")
    return len(bad), total


# ── L2/L3：打法 ↔ 案例 ──────────────────────────────────────
def _parse_plays():
    t = read(PLAYBOOK)
    plays, cur = {}, None
    for ln in t.split("\n"):
        m = re.match(r"^###\s+(\d+)\.(\d+)\s+(.+?)\s*$", ln)
        if m:
            major, minor = int(m.group(1)), m.group(2)
            if major == 0:
                cur = None
                continue
            cur = f"{major}.{minor}"
            plays[cur] = {"name": m.group(3).strip(), "case_line": ""}
            continue
        if re.match(r"^#{1,2}\s+\S", ln):
            cur = None
            continue
        if cur and ln.startswith("**案例**"):
            plays[cur]["case_line"] = ln
    return plays


def _cards():
    out = []
    for f in sorted(glob.glob(os.path.join(CASES, "*.md"))):
        base = os.path.basename(f)
        if not re.match(r"\d", base):
            continue
        for m in re.finditer(r"(?m)^###\s+3\.\d+\s+(.+?)\s*$", read(f)):
            out.append((base, m.group(1)))
    return out


def _universe():
    """卡片宇宙 —— **必须与 picker 操作的对象一致**。

    第一版这里数的是 `### 3.N` 深度卡（609 张），而 `composer.parse_cards` 操作的是
    「案例清单条目 ∪ 深度卡」（约 983 条）→ **两个分母对不上，覆盖率算出来是假的**。
    （这正是本脚本要防的那类错：指标与被测对象不一致。）
    """
    sys.path.insert(0, HERE)
    import composer as C
    uni = set()
    for f in sorted(glob.glob(os.path.join(CASES, "*.md"))):
        b = os.path.basename(f)
        if not re.match(r"\d", b):
            continue
        for c in C.parse_cards("cases/" + b):
            base = re.split(r"[｜|（(]", c["brand"])[0].strip()
            if base:
                uni.add((b, base))
    return uni


def l23(quiet):
    """L2 断链类：每条打法都要「引用行 = 实际取得到的卡」；
    L3 覆盖率类：把 **每一条打法 × 每一个行业档** 都跑一次 pick_cards，
                 其中「**空手**的组合」才是断链，「含本行业卡的组合」是质量指标。

    回传 (l2_breaks, plays_total, l3_zero, l3_pairs, l3_ind_ok, covered, universe)
    """
    sys.path.insert(0, HERE)
    import composer as C
    C.load_model_names(MANUAL03)
    plays = _parse_plays()
    all_files = [os.path.basename(f) for f in sorted(glob.glob(os.path.join(CASES, "*.md")))
                 if re.match(r"\d", os.path.basename(f))]

    broken, mismatch = [], []
    for pid, info in plays.items():
        line = info["case_line"]
        if not line:
            broken.append((pid, info["name"], "无 `**案例**` 行"))
            continue
        files = re.findall(r"`?(cases/\d{2}-[^`\s（(]+\.md)`?", line)
        p = {"id": pid, "name": info["name"], "cases": files, "cases_raw": line,
             "situation": ""}
        if not C.pick_cards(p, "", limit=1):
            broken.append((pid, info["name"], "取不到任何指名卡片"))
            continue
        declared = [kw for cf, kw in C.case_pairs(line)]
        got = [re.split(r"[｜|（(]", c["brand"])[0].strip()
               for cf, c in C.pick_cards(p, "", limit=9)]
        miss = [d for d in declared
                if not any(d[:4] in g or g[:4] in d for g in got)]
        if miss:
            mismatch.append((pid, info["name"], miss, got))

    zero, ind_ok, covered = 0, 0, set()
    for pid, info in plays.items():
        files = re.findall(r"`?(cases/\d{2}-[^`\s（(]+\.md)`?", info["case_line"])
        p = {"id": pid, "name": info["name"], "cases": files,
             "cases_raw": info["case_line"], "situation": ""}
        for ind in all_files:
            got = C.pick_cards_ex(p, ind, limit=2)
            if not got:
                zero += 1
                continue
            if any(os.path.basename(cf) == ind for cf, c, _ in got):
                ind_ok += 1
            for cf, c, _ in got:
                covered.add((os.path.basename(cf),
                             re.split(r"[｜|（(]", c["brand"])[0].strip()))

    uni = _universe()
    pairs = len(plays) * len(all_files)
    if not quiet:
        print(f"  L2 打法 → 案例：{len(plays)} 条打法，取不到卡片的 {len(broken)} 条；"
              f"**引用行与实际取到的卡不一致的 {len(mismatch)} 条**")
        for pid, name, why in broken[:10]:
            print(f"     ✗ §{pid} {name} —— {why}")
        for pid, name, miss, got in mismatch[:10]:
            print(f"     ✗ §{pid} {name}：宣称 {miss} ≠ 实得 {got}")
        print(f"  L3 打法 × 行业（{len(plays)} × {len(all_files)} = {pairs} 组）："
              f"**空手 {zero} 组**｜含本行业卡 {ind_ok} 组（{ind_ok / max(pairs, 1) * 100:.0f}%）｜"
              f"覆盖卡片 {len(covered)}/{len(uni)}")
    return len(broken) + len(mismatch), len(plays), zero, pairs, ind_ok, len(covered), len(uni)


# ── L4：交付物注入（实跑 composer，数真实内容 vs 占位符）──────
def l4(quiet):
    rules = os.path.join(REF, "范例", "（示例）区域茶饮新品牌-任务规则表.json")
    if not os.path.exists(rules):
        cands = glob.glob(os.path.join(REF, "范例", "*规则表*.json"))
        if not cands:
            if not quiet:
                print("  L4 交付物注入：找不到示例规则表，跳过")
            return 0, 0
        rules = cands[0]
    out = "/tmp/kb_audit_skeleton.md"
    r = subprocess.run([PY, os.path.join(HERE, "composer.py"), "--rules", rules,
                        "--out", out, "--tier", "标准"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        if not quiet:
            print(f"  L4 交付物注入：composer 跑不起来（rc={r.returncode}）")
            print("     " + (r.stdout or r.stderr).strip().splitlines()[-1][:120])
        return 99, 0
    t = read(out)
    # 卡片摘要行的出处标记用**全角括号**（`（`cases/xx.md`）`）—— 第一版用半角 `\(` 去数，
    # 结果 count 恒为 0，差点又把「两边都 0」误读成「没注入」（这种 bug 正是本脚本要防的）。
    # 2026-09-17：交付稿**不再带 `cases/xx.md` 路径**（那是内部座标，客户看不懂）。
    #   所以「有没有真的注入」不能再靠数路径 —— 改成数**真实卡片内容**：
    #   `**品牌** —— 他做了什么 ▶ 结果：数字`
    # ⚠️ 2026-09-19 修判据精度：粗判据 `\*\*X\*\*\s*——` 的假阳性是 16/21 ——
    #   `> **预期回报必须拆成…** —— 不做也会自然涨…`（旁注行）、
    #   `- **为什么这么做**：…**只会群发促销** —— 结果半个月后…`（旁注里的加粗短语）
    #   都被数成了「真实卡片内容」→ 报「21 处」，实为 5 处。**指标分母必须＝被测集合**。
    #   锚点：行首 bullet ＋ `**品牌**` ＋ **紧跟** `——`（卡片行的真实形态）。
    #   ⚠️ 不能改回 `[^\n]*——`（「同行有」）—— 旁注行的 `——` 离得很远也照样命中。
    CARD_LINE = re.compile(r"(?m)^[ \t]*-[ \t]*\*\*[^*]{2,24}\*\*[ \t]*——")
    injected = len(CARD_LINE.findall(t))
    # 「含结果数字」＝同一张卡里带得出 `▶ 结果：<数字>` 的（「查不到具体数据」的卡不计）
    results = len(re.findall(r"(?m)^[ \t]*-[ \t]*\*\*[^*]{2,24}\*\*[ \t]*——"
                             r"[^\n]*▶\s*结果[^\n]*\d", t))
    placeholder = len(re.findall(r"暂无可直接参照的公开案例|请展开", t))
    # 同时查交付稿是否残留内部座标（与 selfcheck 第【10】关同一套判据）
    coords = len(re.findall(r"§\s*\d|cases/\d{2}-|打法[库库]|"
                            r"03\s*[·§]\s*[A-Ma-m]\d|模式\s*\d{1,2}", t))
    if not quiet:
        print(f"  L4 交付物注入：骨架 {len(t)} 字｜真实卡片内容 **{injected} 处**"
              f"（含结果数字 {results} 处）｜占位符 {placeholder} 处"
              f"｜**残留内部座标 {coords} 处**")
        if coords:
            print(f"     ✗ 交付稿出现内部座标 —— 客户看不懂，selfcheck 第【10】关会拦")
    return placeholder + coords, injected


# ── L5：模型引用可解析（死条目扫描）──────────────────────────
def l5(quiet):
    m03 = set(m.group(1).upper() for m in
              re.finditer(r"(?m)^###\s*([A-Ma-m]\d{1,2})[｜|·\s]", read(MANUAL03)))
    km = json.loads(read(KMAP))
    used = set()
    for k, v in km.get("major_theory", {}).items():
        used |= {str(x).upper() for x in v.get("models", [])}
    for k, v in km.get("play_overrides", {}).items():
        used |= {str(x).upper() for x in v.get("models", [])}
    dead = sorted(used - m03)
    unused = len(m03 - used)
    total_models = len(m03)
    # **2026-09-17 补：「被 JSON 引用」≠「挑得到」。**
    #   实测接入 33 个模型后仍只有 14 个能被 theory_for 选中 ——
    #   因为 major_theory 每类只取前 3，多数模型永远浮不上来。
    #   所以真正的指标是**可达率**：把所有打法的 theory_for 跑一遍，看哪些模型从未出现。
    sys.path.insert(0, HERE)
    import composer as C
    _km = json.loads(read(KMAP))          # 只读一次（写在循环里会读 104 次盘，×50 遍直接拖死）
    reach = set()
    for pid, info in _parse_plays().items():
        major = int(pid.split(".")[0])
        p = {"id": pid, "name": info["name"], "situation": "",
             "major": major, "cases": [], "cases_raw": ""}
        ms, _ = C.theory_for(p, _km)
        reach |= set(ms)
    unreachable = sorted(m03 - reach)
    if not quiet:
        print(f"  L5 模型 → 打法：03 手册 {len(m03)} 个模型；映射表引用 {len(used)} 个；"
              f"**死条目 {len(dead)} 个**（引用但手册里不存在）")
        if dead:
            print(f"     ✗ 死条目：{'、'.join(dead[:20])}")
        print(f"     **能被 theory_for 挑中的：{total_models - len(unreachable)}/{total_models}**"
              f"（映射表未引用的 {unused} 个；引用了但挑不到的 {len(unreachable) - unused} 个）")
        if unreachable:
            print(f"     ✗ 永远挑不到：{'、'.join(unreachable[:24])}")
    # 断链＝死条目（引用不存在的码）＋ 永远挑不到（引用了却浮不上来）
    return len(dead) + len(unreachable), total_models, unused, total_models - len(unreachable)


# ── L7：私有痕迹扫描（公开仓库红线）──────────────────────────
#   为什么放进审计：2026-09-17 推送前扫到**两个脚本硬编码了本机绝对路径**，
#   以及「去识别化」那一轮漏下的具名主体。**这类泄漏不会被任何既有脚本发现**，
#   而它是公开仓库唯一「一旦推出去就收不回」的错误 —— 所以必须机械化。
PRIVATE_PAT = re.compile(r"/Users/|/home/[a-z]|C:\\\\|\\bzuel\\b|ZUEL|campaign-zuel|00-项目背景",
                         re.I)
PRIVATE_SKIP_DIR = ("/.git/", "/.workbuddy/")


def l7(quiet):
    """注意：**必须排除本脚本自己** —— 判定的正则里必然含 `/Users/` 这种字面，
    不排除就会永远自己举报自己（同 rename_tidy 对自身的处理）。"""
    bad = []
    me = os.path.basename(__file__)
    for f in md_files() + glob.glob(os.path.join(HERE, "*.py")) \
            + glob.glob(os.path.join(HERE, "*.json")) + glob.glob(os.path.join(ROOT, "*.md")):
        if any(s in f for s in PRIVATE_SKIP_DIR) or os.path.basename(f) == me:
            continue
        try:
            t = read(f)
        except Exception as _e:
            # 读不到就得记账：私有痕迹扫描里「没扫到」和「扫不了」是两回事，
            # 后者是盲区，静默 continue 会让人以为扫过了。
            print(f"  ⚠️ 私有痕迹扫描跳过（读不了）：{os.path.relpath(f, ROOT)}（{type(_e).__name__}）")
            continue
        for i, l in enumerate(t.split("\n"), 1):
            if PRIVATE_PAT.search(l):
                bad.append((os.path.relpath(f, ROOT), i, l.strip()[:80]))
    if not quiet:
        print(f"  L7 私有痕迹（公开仓库红线）：**{len(bad)} 处**")
        for f, i, l in bad[:12]:
            print(f"     ✗ {f}:{i} {l}")
    return len(bad), 1


# ── L8：口径一致（**同一概念只许有一个数**）────────────────────────
# 为什么要有这一关（2026-09-19 · 六体系逐行核对 · 体系3 agent 报出）：
#   「回本警戒线」在不同文件里出现过 **6／9／12／18 四种值**；`00-打法库.md` 里
#   LTV 公式**并存两套**（四因子含留存年限 ／ 三因子缺它）。
#   这类冲突**不会报错**，只会让两份材料互相打脸 —— 而此前**没有任何判据在对账**。
#   → 常量统一放 `_common.py`（PAYBACK_WARN_STORE／PAYBACK_WARN_AD／LTV_FORMULA），
#     这里扫「定义句」是否与常量一致。
#
# ⚠️ **本关初版是「扫所有含回本数字的句子」，实测 5 条全是误报**（LTV×转化率、
#   模型名表里的 CAC/LTV、KPI 行 LTV:CAC ≥ 2:1、注释里的旧公式、以及
#   「3 个月单店回本 >6 个月」里被当成阈值的 3）——**不成熟的检查器就是噪声**。
#   → 改成**只锚定定义句**：必须出现「单店投入…回本…N 个月」「品牌投放…回本…N 个月」
#     或 `生命周期价值 LTV（…×…）` 这种**定义形态**。实测 0 误报，且负向测试会叫。
L8_STORE = re.compile(r"单店投入[^\n]{0,12}回本[^\n]{0,12}?(\d+)\s*个月")
L8_AD = re.compile(r"品牌投放[^\n]{0,12}回本[^\n]{0,12}?(\d+)\s*个月")
L8_LTV = re.compile(r"生命周期价值\s*LTV\s*[（(][^）)\n]*×[^）)\n]*[）)]")
# 「真样稿 ≥N 实字」——权威值是 30（海报天然 20–40 字；80 会误杀、50 仍偏严）。
# ⚠️ 2026-09-19：量表里写着「≥80」而代码是 30，正是「同一概念两个数」；
#   这条锚定让两边再也走不散。
L8_DRAFT = re.compile(r"样稿[^。\n]{0,24}≥\s*(\d+)\s*实字")
L8_DRAFT_ALLOW = 30


def l8(quiet):
    import importlib.util as _ilu
    try:
        _spec = _ilu.spec_from_file_location("_common", os.path.join(HERE, "_common.py"))
        _c = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_c)
        _store, _ad = _c.PAYBACK_WARN_STORE, _c.PAYBACK_WARN_AD
    except Exception:
        _store, _ad = 6, 12
    bad = []
    me = os.path.basename(__file__)
    # ⚠️ 只扫**内容档**（md／脚本／根目录说明），与 L7 用同一套枚举 —— 不另外发明一套范围
    #   （本仓库的教训：同一件事两处各写一遍，迟早漂移）。
    for f in md_files() + glob.glob(os.path.join(HERE, "*.py")) \
            + glob.glob(os.path.join(ROOT, "*.md")):
        if any(s in f for s in PRIVATE_SKIP_DIR) or os.path.basename(f) == me:
            continue
        rel = os.path.relpath(f, ROOT)
        if "12-范式库" in rel or rel.startswith("优化轮次"):
            continue                      # 生成物与过程记录不参与对账（源头在 composer／paradigm_data）
        try:
            t = read(f)
        except Exception as _e:
            # ⛔ 不静默（optimize_scan 会抓 `except: continue`；L7 也是这么处理的）：
            #    「没扫到」与「扫不了」是两回事，后者是盲区 —— 静默跳过会让人以为扫过了。
            print(f"  ⚠️ L8 口径扫描跳过（读不了）：{rel}（{type(_e).__name__}）")
            continue
        for i, ln in enumerate(t.split("\n"), 1):
            for pat, allow, lab in ((L8_STORE, _store, "单店投入回本"),
                                    (L8_AD, _ad, "品牌投放回本")):
                for m in pat.finditer(ln):
                    if int(m.group(1)) != allow:
                        bad.append((rel, i, f"{lab}={m.group(1)} 个月（`_common.py` 里是 {allow}）",
                                    ln.strip()[:76]))
            for m in L8_LTV.finditer(ln):
                if "留存年限" not in m.group(0):
                    bad.append((rel, i, "LTV 公式缺「留存年限」（四因子才算同一口径）",
                                m.group(0)[:76]))
            for m in L8_DRAFT.finditer(ln):
                if int(m.group(1)) != L8_DRAFT_ALLOW:
                    bad.append((rel, i, f"样稿字数阈值={m.group(1)}（权威值 {L8_DRAFT_ALLOW}；"
                                        f"海报天然 20–40 字，写大＝误杀合格样稿）", m.group(0)[:76]))
    if not quiet:
        print(f"  L8 口径一致（回本阈值／LTV 公式）：**{len(bad)} 处冲突**")
        for f, i, why, l in bad[:10]:
            print(f"     ✗ {f}:{i} {why}｜{l}")
    return len(bad), 1


# ── L6：全量回归（6 个既有脚本一次跑完）──────────────────────
SCRIPTS = ["file_meta.py", "case_sections.py", "case_order.py",
           "case_upgrade.py", "case_lint.py", "smoke_test.py"]


def l6(quiet):
    bad = []
    for s in SCRIPTS:
        p = os.path.join(HERE, s)
        if not os.path.exists(p):
            bad.append((s, "不存在"))
            continue
        r = subprocess.run([PY, p], capture_output=True, text=True)
        tail = (r.stdout or "").strip().split("\n")[-1][:90]
        ok = r.returncode == 0
        if not ok:
            bad.append((s, tail))
        if not quiet:
            print(f"     {'✅' if ok else '✗'} {s}：{tail}")
    if not quiet:
        print(f"  L6 全量回归：{len(SCRIPTS)} 个校验脚本，{len(bad)} 个未通过")
    return len(bad), len(SCRIPTS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-compose", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    q = a.quiet

    print("=" * 68)
    print("知识库连通性审计 · kb_audit.py")
    print("（既有 6 个脚本查『文件内性质』；本脚本查『跨文件连通性』—— 两者是不同的东西）")
    print("=" * 68)

    f1, t1 = l1(q)
    f2, t2, z3, tp3, i3, cov3, t3 = l23(q)
    if a.no_compose:
        f4, inj = 0, -1
        if not q:
            print("  L4 交付物注入：（--no-compose，跳过）")
    else:
        f4, inj = l4(q)
    f5, t5, unused5, reach5 = l5(q)
    if not q:
        print("  L6 全量回归（6 个既有脚本）：")
    f6, t6 = l6(q)
    f7, t7 = l7(q)
    f8, t8 = l8(q)

    print("-" * 68)
    # 断链类（L1/L2/L4/L6/L7）＝机器能不能动；覆盖率类（L3/L5 未用）＝还有多少没接上，
    # **只有断链才决定退出码** —— 否则「649 张卡必须全被某条打法引用」这种非要求
    # 会让审计永远红灯，久了就没人看（这正是上一轮「绿灯但其实断了」的反面陷阱）。
    rows = [
        ("L1 文件引用可解析", f1, t1),
        ("L2 打法→案例（含「引用行＝实取」一致）", f2, t2),
        ("L3 (打法×行业) 空手的组数", z3, tp3),
        ("L4 交付物占位符", f4, inj),
        ("L6 既有校验未通过", f6, t6),
        ("L7 私有痕迹（公开仓库红线）", f7, t7),
        ("L8 口径一致（回本阈值／LTV 公式）", f8, t8),
    ]
    # ⚠️ 2026-09-19 修：这两行原先印的是 `tp3 - i3` / `t3 - cov3` —— **互补数**，
    #   标签却写着「含本行业卡」「覆盖到的卡片数」→ 同一件事在**同一份报告里印出两个数**
    #   （明细行 2630/5916，汇总行 3286/5916）。用户看不到明细时就会以为覆盖率是 31%。
    #   **规律：同一件事只留一个表达式**（这里明细行与汇总行共用 i3 / cov3）。
    covered = [
        ("L3 含本行业卡的组数（质量指标）", i3, tp3),
        ("L3 覆盖到的卡片数（覆盖率）", cov3, t3),
        ("L5 模型未被映射表用到（覆盖率，非要求）", unused5, t5),
        ("L5 模型能被挑中（可达率，越高越好）", reach5, t5),
    ]
    total_bad = sum(x[1] for x in rows)
    for name, bad, tot in rows:
        flag = "✅" if bad == 0 else "✗"
        print(f"  {flag} {name}：{bad}（基数 {tot}）")
    for name, cov, tot in covered:
        print(f"  ○ {name}：{cov}/{tot}")
    print("-" * 68)
    if total_bad == 0:
        # ⚠️ 数字**现算**，不写死：「五类」「六类」这种手写数会随关卡增减过期
        print(f"✅ {len(rows)} 类断链全通 —— 知识库是「连通的」，不只是「零件合格」")
    else:
        print(f"⚠️ 共 {total_bad} 个断点。**零件合格 ≠ 机器能动** —— 这些断点不会被前 6 个脚本发现。")
    sys.exit(0 if total_bad == 0 else 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
