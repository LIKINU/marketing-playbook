#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交付前自检 · selfcheck.py  （marketing-playbook 协议 3）

用途：宣告交付前跑一次。机械校验「方案是否具备硬要素」。
      有 ❌ → 不准交付，修正后重跑。

用法：
    python selfcheck.py plan.md
    python selfcheck.py plan.md --banned banned.json      # 自订禁用词表
    python selfcheck.py plan.md --quiet                   # 只输出结论

退出码：0 = 全部通过；1 = 有硬错误（必须修）
判断分三级：
    ❌ 硬错误 → 退出码 1，必须修
    ⚠️ 警告   → 需人工确认（不影响退出码）
    ✅ 通过
"""

import json
import os
import re
import sys

from _common import (OK, NG, WARN, HINT, INFO, VAGUE_WORDS, AI_SMELL_WORDS,
                     CAUSAL_WORDS, GENERIC_CATEGORY_WORDS,
                     CONCRETE_ACTION_WORDS, CONCRETE_OBJECT_WORDS,
                     TRAD_HINT)   # noqa: E402

# 繁→简单字表（与 composer 共用 `scripts/t2s_data.py`，机械生成、零依赖）
def _load_t2s():
    try:
        _here = os.path.dirname(os.path.abspath(__file__))
        if _here not in sys.path:
            sys.path.insert(0, _here)
        from t2s_data import T2S_PAIRS as _P
        return {_P[i]: _P[i + 1] for i in range(0, len(_P) - 1, 2)}
    except Exception:
        return {}


_T2S_MAP = _load_t2s()

# 结构清单（关键词宽松匹配，命中任一即可）
# 三元组 = (名称, 关键词, 是否仅「完整版」需要)
#   —— 用户定调（2026-09-14）：交付结构由用户选（**精炼版**／**完整版**）
#      精炼版 = 终稿只放能执行的，**分析类内容（现状／竞品）留支撑稿** → 故标 True（可省）
SECTIONS = [
    ("执行摘要", ["执行摘要", "执行摘要", "TL;DR", "核心结论", "核心结论"], False),
    ("一 · 现状分析", ["现状分析", "现状分析", "生意现状", "生意现状", "问题诊断", "问题诊断"], True),
    ("二 · 策略", ["策略", "方案成立的前提", "节奏排期", "节奏排期", "货盘", "货盘"], False),
    ("三 · 定位与口径", ["定位", "禁用词", "禁用词", "口径", "口径", "差异化支点", "差异化支点"], False),
    ("四 · 触达与渠道", ["触达", "触达", "渠道", "投放", "传播路径", "传播路径"], False),
    ("五 · 落地文案与物料", ["落地文案", "文案", "物料", "话术", "话术"], False),
    ("六 · KPI 与追踪", ["KPI", "追踪", "追踪", "指标", "指标", "监测", "监测"], False),
    ("七 · 预算明细", ["预算明细", "预算明细", "预算表", "预算表", "盈亏线", "盈亏线"], False),
    ("八 · 执行与风控", ["执行与风控", "执行与风控", "行动清单", "行动清单", "风险", "风险", "关键假设", "关键假设"], False),
]

# 内部过程文档关键词 —— 硬错误（真正「怎么干活」的内部术语，不该出现在给客户的稿里）
INTERNAL_LEAK_HARD = [
    "多 Agent", "多Agent", "Agent 分工", "Agent分工", "内部备注", "内部备注",
]
# 软警告 —— 这些词在合规稿件里会**合法**出现，只提示人工确认：
#  ·「门禁／流程状态」→ 交付自检单里会写（如「门禁 13 项已问全」）
#  ·「裁决记录／主理人裁决」→ 12 项自检单第 12 条明文要求「裁决记录与产出索引」，
#     且**保留反对意见的裁决痕迹是质量特征**（罗森案原版就有「主理人对 5 处冲突的裁决」）
#  ·「事实底稿」→ 精炼版的「支撑稿索引」里会提到它（分析类内容在那里）
INTERNAL_LEAK_SOFT = [
    "门禁", "门禁", "流程状态", "流程状态",
    "裁决记录", "裁决记录", "主理人裁决", "主理人裁决",
    "事实底稿", "事实底稿",
]

# 预设禁用词（营销常见违规／高风险）
BANNED_DEFAULT = [
    # 绝对化用语
    "最好", "最佳", "最便宜", "最低价", "最强", "第一品牌", "国家级", "国家级",
    "唯一", "独一无二", "独一无二", "极致", "极致", "顶级", "顶级", "最优", "最优",
    "100%有效", "100%见效", "百分百有效",
    # 功效／医疗
    "治疗", "治疗", "治愈", "治愈", "根治", "痊愈", "痊愈", "包治", "无副作用", "无副作用",
    "药到病除", "药到病除", "特效",
    # 金融 —— 注意：单独的「保本」不算（「保本单量／保本点／保本线」是财务术语），
    #        只有「保本理财／保本收益」这种组合才是违规表述
    "保本收益", "保本理财", "保本理财", "保收益", "稳赚", "稳赚",
    "零风险", "零风险", "稳赚不赔", "稳赚不赔",
]
# ⛔ 硬错误级违规词（2026-09-17 新增，R2 合规视角第 1 条）：
#    「疑似违规用语」原本**全部只判警告** —— 而广告法第九条绝对化用语、化妆品医疗功效宣称
#    是**罚款级红线**，跟「建议补案例」同级是不对的。这里把它们升为硬错误。
#    另外原表缺了美妆高频违规词（祛痘／美白／药妆／医美级… ）—— 一并补上。
BANNED_HARD = [
    # 广告法第九条：绝对化用语
    "最好", "最佳", "最便宜", "最低价", "最低价", "最强", "最强", "第一品牌", "销量第一",
    "销量第一", "国家级", "国家级", "国家级产品", "唯一", "独一无二", "独一无二", "极致",
    "极致", "顶级", "顶级", "最优", "最优", "史上最", "绝无仅有", "绝无仅有", "首选",
    "首选", "领导品牌", "领导品牌", "驰名商标", "驰名商标", "100%有效", "100%见效",
    "百分百有效", "百分百见效", "全网最低", "全网最低",
    # 化妆品医疗功效宣称（普通化妆品不得宣称医疗功效）
    "治疗", "治疗", "治愈", "治愈", "根治", "痊愈", "痊愈", "包治", "药到病除", "药到病除",
    "特效", "疗效", "疗效", "消炎", "杀菌", "杀菌", "抗菌", "除菌", "抗敏", "祛疤", "生发",
    "生发", "丰胸", "丰胸", "减肥", "减肥", "溶脂", "药妆", "药妆", "医美级", "医美级",
    "医学护肤品", "医学护肤品", "速效", "一洗白", "永久", "无副作用", "无副作用",
    # 私域专属红线（2026-09-17 R5 私域视角第 8 条）：诱导分享一次判罚就能封链，
    # 整条私域路径断掉 —— 与广告法同级，故进硬错误。
    "诱导分享", "诱导分享", "助力", "集赞", "集赞", "砍价免费拿", "砍价免费拿",
    "分享才能", "不转不是", "转发才能", "个人号收款", "个人号收款",
    # 美妆常见违规宣称（R2 补）
    "祛痘", "祛斑", "美白", "去黑眼圈", "祛眼袋", "抗皱", "抗皱", "除螨", "除螨", "脱敏",
    "脱敏", "激素", "排毒",
]

# 允许出现在「禁用词表」章节内（那是在说「不能说」）
#    ⚠️ 2026-09-17 收窄（R2 合规视角第 3 条）：原表含「不得／禁止」——
#       那是正常公文高频词（「价格不得低于」），命中就挖掉**前后各 2 行**，
#       会让附近真正的违规词合法逃逸（系统性盲区）。改为只认「明确在讲禁用词表」的标记，
#       且豁免范围从 ±2 行收到 ±1 行。
BANNED_CONTEXT_SAFE = ["禁用词", "禁用词", "不能说", "不能说", "红线词", "红线词"]

# 财务／统计语境白名单：命中则从扫描文本挖掉
# （例：「保本单量」是财务术语，不是金融产品的「保本」承诺 —— 不豁免会一直误报）
BANNED_WHITELIST_PATTERNS = [
    r"保本(单量|销量|销量|点|点|线|线|值|门槛|门槛|测算|测算|单数|单数|分析)",
    r"回本(周期|周期|单量|销量|销量|点|点|时间|时间|线|线)",
]


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _is_full_hint(text):
    """早期判断「这是不是完整版方案」——供【1b】用（那时 _is_full_plan 还没算出来）。
    判据同【15】：同时有 现状分析／策略／定位与口径／预算明细 四章。"""
    return all(x in text for x in ["现状分析", "策略", "定位与口径", "预算明细"])


def emit_json(hard, warns, code):
    """--json：给 CI／自动化消费的结构化输出（优化项 2026-09-16）。"""
    if "--json" in sys.argv:
        print(json.dumps({"exit": code, "hard_errors": hard, "warnings": warns}, ensure_ascii=False))


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("用法: python selfcheck.py <plan.md> [--banned banned.json] [--quiet] [--json]")
        print("  退出码 0=全过（可交付）｜1=有硬错误（不得交付）｜2=脚本出错")
        sys.exit(0)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    quiet = "--quiet" in sys.argv
    if not args:
        print("用法: python selfcheck.py <plan.md> [--banned banned.json] [--quiet]")
        sys.exit(1)
    path = args[0]

    banned = list(BANNED_DEFAULT)
    if "--banned" in sys.argv:
        i = sys.argv.index("--banned")
        try:
            with open(sys.argv[i + 1], "r", encoding="utf-8") as f:
                extra = json.load(f)
            banned += list(extra.get("banned", extra)) if isinstance(extra, (dict, list)) else []
        except Exception as e:
            print(f"{WARN} 读取自订禁用词表失败（用预设表继续）：{e}")

    try:
        text = read(path)
    except Exception as e:
        print(f"{NG} 无法读取方案档：{e}")
        sys.exit(1)

    hard_errors, warnings = [], []

    if not quiet:
        print("=" * 64)
        print(f"交付前自检 · {path}")
        print("=" * 64)

    # 1) 结构（支持两种交付结构：完整版／精炼版）
    if not quiet:
        print("\n【1】文档结构（完整版九部分；**精炼版可省「现状分析」**）")
    body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)  # 去掉 front matter
    optional_missing = []
    for name, keys, optional_only in SECTIONS:
        hit = any(k in body for k in keys)
        if not quiet:
            mark = OK if hit else (WARN if optional_only else NG)
            extra = "（精炼版可省 —— 分析留支撑稿）" if (optional_only and not hit) else ""
            print(f"  {mark} {name}{extra}")
        if not hit:
            if optional_only:
                optional_missing.append(name)
            else:
                hard_errors.append(f"缺少「{name}」章节")
    if optional_missing:
        warnings.append(
            f"未含 {'、'.join(optional_missing)} —— 若为**精炼版**属正常（分析放在支撑稿）；"
            f"若为完整版则需补上"
        )

    # 1a) 篇幅形状（优化项）：太短基本是空壳（除非明确是「速览版」）
    _chars = len(re.sub(r"\s", "", body))
    if not quiet:
        print(f"  {'✅' if _chars >= 1500 else WARN} 正文非空白字数：{_chars:,}")
    if _chars < 1500 and "速览" not in text and "速览" not in text:
        warnings.append(f"全文仅 {_chars} 字 —— 交付稿通常远不止此，请确认不是空壳稿")

    # 1b) composer 骨架占位符残留 —— 硬错误（未填完的骨架不得交付）
    # ⚠️ 2026-09-17 改 0 容忍（R2 合规视角第 9 条）：原阈值「<3 视为已填完」——
    #    但官方「不得留空」是 **0 容忍**，且 delivery_check 的 PLACEHOLDER_HARD 早已 0 容忍，
    #    两处口径不一致。留 1–2 处也能过 selfcheck ＝ 把漏洞开在自检最该严的地方。
    fill_cnt = len(re.findall(r"【填】", text))
    if not quiet:
        print(f"  {'✅' if fill_cnt == 0 else NG} composer 占位符【填】残留：{fill_cnt} 处（0 容忍）")
    if fill_cnt >= 1:
        hard_errors.append(f"方案残留 {fill_cnt} 处 composer 占位符【填】 —— 骨架未填完，不得交付"
                           f"（占位符为 0 容忍：官方「不得留空」不给额度）")

    # 1b) **与 paradigm_data 对账**（2026-09-17 反向榨第 1 条的治本措施）
    #   问题：上面的 `SECTIONS` 是**手写的 9 个关键词**，而 composer／paradigm_data 的骨架
    #   至少有 30+ 节。于是 SKILL 合约里承诺的「2.3 被低估的资产」「2.4 节奏排期」
    #   「7.3 追投与止损规则」—— composer 一个都不生成，**却没有任何一关会发现**
    #   （贝恩 R1 agent ＋ 运营 R3 agent 两个独立视角都指出了这件事）。
    #   → 改为直接读 `paradigm_data.COMMON_HEADS` 逐节对账。
    #     这条链就闭环了：composer 产出 → build_paradigm 校验宣告 → selfcheck 校验交付稿。
    try:
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            "paradigm_data", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "paradigm_data.py"))
        _pd = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_pd)
        _norm = lambda s: re.sub(r"[\s]", "", s)          # 去空白后比对
        _body_n = _norm(body)
        _skeleton_missing = [h for h in getattr(_pd, "COMMON_HEADS", [])
                             if _norm(h) not in _body_n]
        if not quiet:
            print("\n【1b】与 paradigm_data 骨架对账（治本：文档承诺 ≠ 实际生成）")
            print(f"  {'✅' if not _skeleton_missing else '❌'} 通用骨架 "
                  f"{len(getattr(_pd, 'COMMON_HEADS', []))} 节，缺 {len(_skeleton_missing)} 节"
                  + (f"：{'、'.join(_skeleton_missing[:6])}" if _skeleton_missing else ""))
        if _skeleton_missing:
            _hard_if_full_early = (
                "交付稿缺少 paradigm_data 声明的章节："
                + "、".join(_skeleton_missing[:8])
                + "　→ 这是「文档承诺了、实际没生成」的漂移（composer 有 build_paradigm 把关，"
                  "selfcheck 这一关负责把关交付稿）。")
            if _is_full_hint(text):
                hard_errors.append(_hard_if_full_early)
            else:
                warnings.append(_hard_if_full_early + "（速览类快案可忽略）")
    except Exception as _e:
        warnings.append(f"与 paradigm_data 对账失败（{type(_e).__name__}）—— 【1b】未生效")

    # 2) 交付自检单（协议 3：可写进文档附件，也可只在聊天回复输出 → 缺失仅警告，不拦）
    has_checklist = ("自检单" in text or "自检单" in text)
    box_count = len(re.findall(r"[✅❌]", text))
    if not quiet:
        print("\n【2】交付自检单")
        print(f"  {'✅' if has_checklist else WARN} 出现「自检单」字样：{has_checklist}")
        print(f"  {'✅' if box_count >= 12 else WARN} ✅/❌ 标记数量：{box_count}（建议 ≥12）")
    if not has_checklist:
        warnings.append("文档内未含《交付自检单》—— 协议 3 允许只在聊天回复输出，请确认回复中已附")
    elif box_count < 12:
        warnings.append(f"✅/❌ 标记只有 {box_count} 个，自检单可能没逐项标")

    # 3) 内部过程文档泄漏
    #    ⚠️ 注意（死结修正）：交付稿的「附件 C」按 SKILL.md §三 明文就叫「事实底稿」，
    #    所以检查必须跳过「附件／附录」之后的区域 —— 否则一份完全合规的稿必然被判违规，
    #    build_docx 永久拒绝出稿（强制层反而变成阻塞层）。
    if not quiet:
        print("\n【3】内部过程文档检查（不得出现在正文；附件区除外）")
    # 附件／附录标题（允许行末无内容、允许「## 附件」这种写法）
    m_appendix = re.search(r"(?m)^#{1,4}\s*(附件|附录|附录)\s*[A-D]?\s*[:：·]?", text)
    body_scope = text[:m_appendix.start()] if m_appendix else text
    leaks = sorted({k for k in INTERNAL_LEAK_HARD if k in body_scope})
    soft_leaks = sorted({k for k in INTERNAL_LEAK_SOFT if k in body_scope})
    if leaks:
        for k in leaks:
            if not quiet:
                print(f"  {NG} 发现内部字样：「{k}」")
        hard_errors.append(f"交付稿混入内部过程字样：{'、'.join(leaks)}")
    if soft_leaks:
        if not quiet:
            print(f"  {WARN} 出现流程用语：{'、'.join(soft_leaks)}（自检单里合法；若混进正文请删）")
        warnings.append(f"正文可能混入流程用语：{'、'.join(soft_leaks)}")
    if not leaks and not soft_leaks and not quiet:
        print(f"  {OK} 未发现内部过程字样")

    # 4) 未核实数据
    if not quiet:
        print("\n【4】可信度标注")
    unverified = len(re.findall(r"【未核实】|【未核实】", text))
    verified = len(re.findall(r"【已核实】|【已核实】", text))
    if not quiet:
        print(f"  {'⚠️' if unverified else '✅'} 【未核实】出现 {unverified} 处（>0 需从交付物剔除）")
        print(f"  ℹ️  【已核实】出现 {verified} 处")
    if unverified:
        warnings.append(f"交付稿含 {unverified} 处【未核实】数据，对外交付前应剔除或降级表述")

    # 5) 五要素（启发式）
    if not quiet:
        print("\n【5】动作五要素（启发式检查）")
    four = {
        "谁做": ["谁做", "谁做", "负责", "负责", "责任人", "责任人", "执行人", "执行人"],
        "时间": ["什么时候", "什么时候", "排期", "第 X 周", "第 X 周", "deadline", "截止", "日起", "月前"],
        "花多少": ["花多少", "预算", "预算", "费用", "费用", "元", "¥"],
        "怎么验收": ["验收", "验收", "指标", "指标", "达成", "达成", "目标值", "目标值"],
    }
    for k, keys in four.items():
        hit = any(x in text for x in keys)
        if not quiet:
            print(f"  {OK if hit else WARN} {k}")
        if not hit:
            warnings.append(f"可能缺「{k}」的描述")

    # 6) 禁用词
    if not quiet:
        print("\n【6】禁用词扫描（只扫描非「禁用词说明」段落）")
    # 粗略：把含「禁用词/不能说/红线」的段落挖掉再扫
    lines = text.splitlines()
    safe_idx = set()
    in_code = False
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("```"):     # 围栏代码块整段排除（范例／原文不该被当违规用语）
            in_code = not in_code
            safe_idx.add(i)
            continue
        if in_code:
            safe_idx.add(i)
            continue
        if any(c in ln for c in BANNED_CONTEXT_SAFE) or ln.strip().startswith(("- 禁用", "| 禁用", "- 不能")):
            for j in range(max(0, i - 1), min(len(lines), i + 2)):   # ±1 行（原 ±2）
                safe_idx.add(j)
    scan_text = "\n".join(ln for i, ln in enumerate(lines) if i not in safe_idx)
    # 套用财务／统计语境白名单（避免「保本单量」这类术语误报）
    for pat in BANNED_WHITELIST_PATTERNS:
        scan_text = re.sub(pat, "", scan_text)
    found = sorted({b for b in banned if b and b in scan_text})
    hard_found = sorted({b for b in BANNED_HARD if b and b in scan_text})
    if hard_found and not quiet:
        print(f"  {NG} ⛔ 硬红线违规词 {len(hard_found)} 个：{'、'.join(hard_found[:12])}")
    if hard_found:
        hard_errors.append(
            f"广告法／化妆品宣称硬红线：{'、'.join(hard_found[:12])}"
            + ("…" if len(hard_found) > 12 else "")
            + "　→ 绝对化用语与医疗功效宣称是罚款级红线，改成可核查的功能性表述。")
    soft = [b for b in found if b not in hard_found]
    if soft:
        for b in soft:
            if not quiet:
                print(f"  {WARN} 疑似违规用语：「{b}」")
        warnings.append(f"疑似违规用语 {len(soft)} 个：{'、'.join(soft[:12])}"
                        + ("…" if len(soft) > 12 else ""))
    if not found and not quiet:
        print(f"  {OK} 未发现预设禁用词")

    # 7) 核心方法论要素（2026-09-16 新增：把「好方案的三个特征」变成机械校验）
    #    来源：用户以《中百罗森新生开学引流方案》为基准的纠偏——该稿的诊断／打法组合／
    #    风险自检三章明显优于同期产出，遂固化为硬门槛。
    if not quiet:
        print("\n【7】核心方法论要素（打法组合表／问题类型／失败归因编号／可抄案例）")

    # 7a 打法组合 —— 硬错误（形式不限：多段文字 或 表格）
    #    2026-09-16 修正：8 列宽表在 Word 里会挤成一条竖线（用户实测反馈），
    #    推荐「多段文字」形式 → 校验改为看「要素标签」而非表头。
    combo_marks = re.findall(r"(?m)^\*\*打法\s*\d+", text)
    table_head = re.search(r"(?m)^\|[^\n]*(为什么用它|为什么用它)[^\n]*\|", text)
    labels = {
        "为什么用它": ["为什么用它", "为什么用它"],
        "具体动作": ["具体动作", "具体动作"],
        "谁做": ["谁做", "谁做"],
        "花多少": ["花多少"],
        "多久见效": ["多久见效", "多久见效"],
        "验收指标": ["验收指标", "验收指标"],
        "可抄案例": ["可抄案例"],
    }
    hit = sum(1 for alts in labels.values() if any(a in text for a in alts))
    if combo_marks or table_head:
        form = "多段文字" if len(combo_marks) >= 3 else "表格"
        if not quiet:
            print(f"  {OK} 打法组合存在（{form}形式，{len(combo_marks)} 条，要素标签 {hit}/7）")
        if hit < 6:
            if not quiet:
                print(f"  {NG} 打法要素标签只命中 {hit}/7")
            hard_errors.append(
                f"打法组合要素不全（{hit}/7）——每条须含：为什么用它／具体动作／谁做＋花多少＋多久见效／验收指标／可抄案例"
            )
    else:
        if not quiet:
            print(f"  {NG} 未找到打法组合（需「**打法 N｜名称」分段，或含「为什么用它」的表头）")
        hard_errors.append(
            "缺少《打法组合》——推荐多段文字：每条「**打法 N｜名称**」下写"
            "为什么用它／具体动作／谁做｜花多少｜多久见效／验收指标／可抄案例"
        )

    # 7b 问题类型 A–H 归类 —— 警告
    mt = re.search(r"问题类型|问题类型", text)
    _type_names = ["认知", "认知", "交易", "渠道", "信任", "复购", "复购", "私域",
                   "定价", "定价", "组织", "组织", "合规", "合规"]
    # 收紧：除了「问题类型」附近有 A–H 字母，还必须真的提到某一类名（否则模型码里的字母会误命中）
    if mt and re.search(r"[A-H]", text[mt.start():mt.start() + 120]) and any(n in text for n in _type_names):
        if not quiet:
            print(f"  {OK} 问题类型已归类（A–H）")
    else:
        if not quiet:
            print(f"  {WARN} 诊断未见「问题类型（A–H）」归类")
        warnings.append("诊断缺「问题类型（A–H）」——见 SKILL.md 第 2 步分类表（认知/交易/渠道/信任/复购/定价/组织/合规）")

    # 7c 风险四件套 —— 警告
    #    2026-09-17：不再要求挂「模式 NN」编号（那是内部座标，客户看不懂，第【10】关会拦）。
    #    改为检查风险本身写全了没：为什么会发生／预警信号／兜底预案／预防动作。
    _rk = re.search(r"^#{1,4}\s*[^\n]*[风风][险险](.*?)(?=^#{1,2}\s|\Z)", text, flags=re.S | re.M)
    _rt = _rk.group(1) if _rk else ""
    _r4 = [k for k in ("预警信号", "预警信号", "兜底预案", "兜底预案",
                       "预防动作", "预防动作", "为什么会发生", "为什么会发生") if k in _rt]
    if _rt and len(_r4) >= 3:
        if not quiet:
            print(f"  {OK} 风险四件套已写（{'／'.join(_r4[:4])}）")
    elif _rt:
        if not quiet:
            print(f"  {WARN} 风险只写了 {len(_r4)}/4 件套")
        warnings.append("风险清单每条要写全四件套：为什么会发生／预警信号／兜底预案／预防动作"
                        "（内部可对照失败归因总库，但交付稿里**不要**写「模式 NN」编号）")
    else:
        if not quiet:
            print(f"  {WARN} 未找到风险章节，跳过")
        warnings.append("未找到风险章节，无法校验风险四件套")

    # 7d 可抄案例 —— **必须有品牌＋有做法＋有结果**（2026-09-17 改）
    #    旧版看的是「有没有写 `cases/xx.md` 路径」，那等于鼓励把内部路径写进交付稿。
    #    新版看的是**内容**：拿得出品牌名吗？说得出结果数字吗？
    _cms = list(re.finditer(r"可抄案例", text))
    _weak = []
    for _n, _m in enumerate(_cms, 1):
        seg = text[_m.start():_m.start() + 400]
        has_brand = bool(re.search(r"\*\*[^*]{2,24}\*\*", seg))
        has_result = bool(re.search(r"结果|结果|率|增长|增长|提升|万|万|%|倍", seg))
        if not (has_brand and has_result):
            _weak.append(_n)
    if _cms and not _weak:
        if not quiet:
            print(f"  {OK} 可抄案例均含「品牌＋做法＋结果」（{len(_cms)} 处）")
    elif _cms:
        if not quiet:
            print(f"  {WARN} 第 {_weak} 处可抄案例缺品牌或缺结果")
        warnings.append("可抄案例要写「**品牌** —— 他做了什么 ▶ 结果：数字」，"
                        "只有品牌没结果（或只有做法没品牌）都不算可抄")
    else:
        if not quiet:
            print(f"  {WARN} 未见可抄案例段落")
        warnings.append("打法组合建议加「可抄案例」（写清别人怎么做的、结果如何、我们怎么用）")

    # 7e 每条打法的「具体动作」须精准到每一步（≥3 个编号步骤）—— 硬错误
    #    用户 2026-09-16：「策划具体操作流程还是没写好，要详细精准到每一步 —— 指策划案的打法和实操」
    p_blocks = re.split(r"(?m)^\*\*打法\s*\d+", text)[1:]
    thin = [i + 1 for i, b in enumerate(p_blocks)
            if len(re.findall(r"(?m)^\s*\d+[.、]", b)) < 3]
    if p_blocks:
        if not thin:
            if not quiet:
                print(f"  {OK} 每条打法都有 ≥3 步的逐步骤实操（{len(p_blocks)} 条）")
        else:
            if not quiet:
                print(f"  {NG} 有 {len(thin)} 条打法的实操不足 3 步")
            hard_errors.append(
                f"打法 {thin} 的「具体动作」不足 3 个编号步骤 —— 每条打法须写到「精准到每一步」"
                "（动作／谁做／时间／物料·话术／产出），不能只写一句话"
            )

    # 8) 知识展开度（2026-09-17 **反转**）
    #
    #    旧版**强制**交付稿挂「打法库 §X.X」「03 模型码」「（作者49）」——结果就是客户
    #    拿到一份满是内部座标的稿：看不懂、也查不到。用户原话：
    #      「不是只是引用了就行了，说有什么理论是没有任何意义的 —— 要写具体的操作」
    #      「交付出来的东西应该是可以直接看的，而不是有例如像（打法库 §4.1）这样的引用」
    #
    #    新规则：**知识必须写成内容，座标一律不得出现**。
    #      · 8a 每条打法的「为什么这么做」必须是**写开的内容**（不是编号、不是【填】）
    #      · 8b 策略篇必须真的用到 ≥3 个理论（用 03 手册的**模型中文名**验，不看编号）
    #      · 8c 全文 ≥1 处书籍观点（《书名》＋主张）
    #      · 座标本身的拦截 → 第【10】关
    if not quiet:
        print("\n【8】知识展开度（理论／案例须写成可执行内容，不得只留编号）")

    _ref_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "references")
    _m03 = os.path.join(_ref_dir, "03-方法论操作手册.md")

    # 8a 每条打法的「为什么这么做」必须展开成实质内容（≥25 个实字）
    _pb = re.split(r"(?m)^\*\*打法\s*\d+", text)
    if len(_pb) > 1:
        _thin = []
        for i, blk in enumerate(_pb[1:], 1):
            m = re.search(r"(?:为什么这么做|为什么这么做|理论依据|理论依据)[^\n]*?[：:]\s*(.+)", blk)
            # ⚠️ 2026-09-17 修：这里原本写 `body = ...`，**覆盖掉上面第 147 行定义的全文变量 `body`**。
            #    后果：【11】场景完整性与【13】交叉引用都变成在对「某条打法的『为什么』那半行」
            #    做检查 → 永远 0 命中 → 看起来全绿，其实整关从未生效。
            #    这是典型的「校验器自己坏掉、却回报通过」，比没有校验更危险。
            _why_txt = (m.group(1) if m else "").strip()
            solid = len(re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", _why_txt))
            # ⚠️ 2026-09-17 升级：原先只看「≥25 实字」，25 字空话稳过
            #    （「因为环境不好所以要稳健推进避免风险」21 字，加几个字就满分）。
            #    So-What 测的是「答不答得出**所以呢**」，不是长度 → 改为「长度 + 至少一条实质」：
            #      ① 含数字＋单位（可核验的量化）  ② 引了品牌或《书名》（有外部依据）
            #      ③ 含因果词（讲清了机制）
            #    并且不得通篇是模糊词。
            _has_num = bool(re.search(r"\d+\s*(?:元|%|％|万|万|天|周|周|个月|个月|次|单|单|人|店|条|条|倍|小时|小时)", _why_txt))
            _has_ref = bool(re.search(r"\*\*[^*]+\*\*|《[^》]+》", _why_txt))
            _has_cause = any(w in _why_txt for w in CAUSAL_WORDS)
            # ⚠️ 2026-09-17 调参（拿真稿验出来的）：只认「数字／引用／因果词」会**误伤**
            #    机制句 —— 实测「瞳话如果不在黄金层、没有插卡和堆头，就只是在给陈列做得
            #    更好的对手做背景」这句明明是机制说明，却因为没有「因为/所以」被误判。
            #    → 补三类同样算「讲清了机制」的句式：条件推演／对照取舍／推理链。
            _MECH = [
                r"如果[^，。]{2,20}[，,][^。]{2,}", r"若[^，。]{2,20}[，,][^。]{2,}",
                r"一旦[^，。]{2,20}[，,]", r"只要[^，。]{2,20}[，,]",
                r"越[^，。]{1,12}[，,]越", r"不是[^，。]{1,20}[，,]?而是",
                r"只有[^，。]{2,20}[，,]?才", r"与其[^，。]{2,20}[，,]?不如",
                r"而不是", r"而非", r"相比", r"→",
            ]
            _has_mech = any(re.search(p, _why_txt) for p in _MECH)
            _vague = sum(1 for w in VAGUE_WORDS if w in _why_txt)
            _solid_ok = (solid >= 25
                         and (_has_num or _has_ref or _has_cause or _has_mech)
                         and _vague <= 2)
            if not _solid_ok:
                _thin.append(i)
        if _thin:
            if not quiet:
                print(f"  {NG} 打法 {_thin} 的「为什么这么做」没写开（<25 实字）")
            hard_errors.append(
                f"打法 {_thin} 的「为什么这么做」不达标 —— 需同时满足："
                "①≥25 实字 ②至少含一条实质（数字＋单位／引品牌或《书名》／因果词／机制句「如果…就」「不是…而是」等／推理箭头）"
                "③模糊词（加强/提升/优化/赋能…）≤2 个。"
                "**写得长不等于写得清**：要答得出「所以呢」。"
            )
        else:
            if not quiet:
                print(f"  {OK} 每条打法的「为什么这么做」都已展开（{len(_pb)-1} 条）")
    else:
        if not quiet:
            print(f"  {WARN} 未找到「**打法 N」分段，跳过")
        warnings.append("未找到打法组合分段，无法校验「为什么这么做」是否展开")

    # 8b 策略篇须真的用到 ≥3 个理论 —— 用 03 手册的**模型中文名**比对（不认编号）
    # 知识库已全仓统一简体（2026-09-18），这里仍做一次 t2s：**幂等**，且万一
    # 有人贴了繁体进来，匹配就不会静默落空（历史上正是「不转换＝一个都匹配不上」）
    def _s2cn(x):
        return "".join(_T2S_MAP.get(c, c) for c in x)

    _names = {}
    if os.path.exists(_m03):
        try:
            for m in re.finditer(r"^###\s*([A-Ma-m]\d{1,2})[｜|·\s]+([^\n（(]+)",
                                 read(_m03), flags=re.M):
                nm = _s2cn(m.group(2).strip())
                if len(nm) >= 2:
                    _names[m.group(1).upper()] = nm
        except Exception as _e:
            # ⛔ 不能吞：这张表是 8b「策略篇须用 ≥3 个理论」的唯一依据。
            #    加载失败＝后面那条校验会拿空表去比，必然判「没用到理论」或直接跳过。
            warnings.append(f"模型名表加载失败（{type(_e).__name__}）—— 【8】的 8b 校验不可信，请检查 03 手册")
            print(f"  {WARN} 模型名表加载失败（{type(_e).__name__}）—— 8b 校验不可信")
    _ms = re.search(r"^#{1,4}\s*[^\n]*策略(.*?)(?=^#{1,2}\s*[^\n]*定位|\Z)", text, flags=re.S | re.M)
    _strat = _ms.group(1) if _ms else text
    _hit_names = sorted({nm for nm in _names.values() if nm in _strat})
    if len(_hit_names) >= 3:
        if not quiet:
            print(f"  {OK} 策略篇用到 {len(_hit_names)} 个理论（{'、'.join(_hit_names[:6])}…）")
    else:
        if not quiet:
            print(f"  {NG} 策略篇只用到 {len(_hit_names)} 个理论（需 ≥3）")
        hard_errors.append(
            f"策略篇只识别出 {len(_hit_names)} 个理论（需 ≥3）——理论要**写进做法里**"
            "（说清楚这套动作背后用的是什么道理），不是列一串理论名称"
        )

    # 8c 全文 ≥1 处书籍观点（《书名》＋主张）；排除内部文文件名
    _block_book = ("规则表", "规则表", "自检单", "自检单", "规则", "规则")
    _books = [b for b in re.findall(r"《[^》]{1,40}》", text) if not any(x in b for x in _block_book)]
    if _books:
        if not quiet:
            print(f"  {OK} 引用书籍观点 {len(_books)} 处（如 {_books[0]}）")
    else:
        if not quiet:
            print(f"  {NG} 全文未见任何书籍观点")
        hard_errors.append("未引用任何书籍观点（需 ≥1 处：《书名》＋它的核心主张，写进做法依据里）")

    # 8d 定位篇：≥1 个定位理论关键词（警告 —— 不挂编号后不再强制模型码）
    _mp = re.search(r"^#{1,4}\s*[^\n]*定位[与与]口[径径](.*?)(?=^#{1,2}\s|\Z)", text, flags=re.S | re.M)
    _pos = _mp.group(1) if _mp else ""
    _pos_kw = ["定位", "品牌资产", "品牌资产", "视觉锤", "视觉锤", "超级符号", "超级符号",
               "USP", "独特卖点", "独特卖点", "品类", "心智", "里斯", "特劳特", "凯勒",
               "华与华", "冯卫东", "江南春", "CBBE", "对立定位", "场景"]
    _kw_signals = {k for k in _pos_kw if k in _pos}
    if _pos and _kw_signals:
        if not quiet:
            print(f"  {OK} 定位篇理论关键词 {len(_kw_signals)} 个")
    elif _pos:
        if not quiet:
            print(f"  {WARN} 定位篇未见定位理论关键词")
        warnings.append("定位篇建议点明用的是哪一套定位理论（并说清楚怎么用在这一步）")
    else:
        if not quiet:
            print(f"  {WARN} 未找到第三篇定位章节，跳过")
        warnings.append("未找到第三篇 定位与口径，无法校验定位理论")

    # 9) 交付稿须简体（SKILL.md 硬要求）—— 侦测繁体字
    #    知识库已全仓统一简体，正常不会出现繁体 → 出现就是**外部粘贴**，更该拦
    # 判据来自 `_common.TRAD_HINT`（原先在这里写死一份，build_docx 又写一份，且已漂移）
    hit_trad = sorted({ch for ch in text if ch in set(TRAD_HINT)})
    if not quiet:
        print(f"\n【9】交付稿简体检查（SKILL 要求交付稿简体）")
        print(f"  {'✅' if len(hit_trad) < 15 else WARN} 侦测到繁体字 {len(hit_trad)} 种"
              + (f"（{'、'.join(hit_trad[:15])}…）" if hit_trad else ""))
    if len(hit_trad) >= 15:
        # 改为硬错误（2026-09-16）：SKILL 明定交付稿必须简体，只警告＝繁体稿照样能出 → 规则形同虚设
        hard_errors.append(f"交付稿疑似繁体（{len(hit_trad)} 种繁体字：{'、'.join(hit_trad[:10])}…）"
                           f"—— SKILL 要求对外交付稿用**简体**，请本地化后重跑")

    # 10) 交付稿洁净度 —— 硬错误（2026-09-17 新增）
    #
    #    这关是整套改造的**收口**：前面把座标从骨架里拿掉了，这里确保模型补写时
    #    也不会把座标加回来。出现任何一条 → 不准出稿。
    #    客户不需要知道我们内部怎么编号、文件放在哪、用了哪个脚本。
    if not quiet:
        print("\n【10】交付稿洁净度（不得出现任何内部座标）")
    _coord_pats = [
        (r"§\s*\d", "章节编号（§X.X）"),
        (r"cases/\d{2}-", "案例库文件路径"),
        (r"references/", "references 目录路径"),
        (r"打法[库库]", "「打法库」内部文件名"),
        (r"03\s*[·§]?\s*[A-Ma-m]\d", "03 模型码"),
        (r"模型\s*[A-Ma-m]\d{1,2}", "模型码"),
        (r"49\s*[）)]", "49 书籍编号"),
        (r"模式\s*\d{1,2}", "失败归因「模式 NN」编号"),
        (r"(?:composer|selfcheck|build_docx|run_pipeline|gate_check|kb_audit)\.py", "脚本文件名"),
        (r"(?:SKILL|AGENTS)\.md", "内部文档文件名"),
        (r"knowledge_map", "内部映射表文件名"),
        (r"方法论操作手册|方法论操作手册", "内部手册文件名"),
        # 2026-09-17 新增：**施工语气**。这些不是「座标」，但同样是给执行 AI 的指令，
        # 印进客户文档里一样穿帮（实测 composer 曾在交付稿留下
        # 「—— 说明用在定位的哪一步」）。【10】关原本 12 条正则一条都盖不到。
        (r"——\s*说明|——\s*说明", "给 AI 的施工说明"),
        (r"（自行填写|（自行填写|自行填写", "施工指引语气"),
        (r"按指引|依指引|照骨架|见骨架", "施工指引语气"),
        (r"\{FILL\}|【待填】|【待补】", "未替换的占位符"),
    ]
    _coord_hits = []
    for _pat, _label in _coord_pats:
        for _m in re.finditer(_pat, text):
            _coord_hits.append((text[:_m.start()].count("\n") + 1, _label, _m.group(0).strip()[:24]))
    if _coord_hits:
        if not quiet:
            print(f"  {NG} 发现 {len(_coord_hits)} 处内部座标：")
            for _ln, _label, _raw in _coord_hits[:10]:
                print(f"     · 第 {_ln} 行【{_label}】{_raw}")
        hard_errors.append(
            f"交付稿出现 {len(_coord_hits)} 处内部座标（"
            + "、".join(sorted({x[1] for x in _coord_hits}))
            + f"）——客户看不懂也不需要看。改成可读的内容；"
            f"溯源讯息请写进 `composer.py --internal` 那份文件里"
        )
    else:
        if not quiet:
            print(f"  {OK} 无内部座标（客户可直接阅读／提交）")

    # 11) 场景完整性（2026-09-17 新增）
    #     大赛／B端／G端／投标 各自有「必须有的章节」（见 references/09 + composer SCENE_SECTIONS）。
    #     缺一块＝不完整（「写得再好，缺一块就是不完整的」）。
    #     触发条件：正文出现「## 九 ·」场景章节标题 → 判定用了场景结构 → 必须补齐该场景后续章节。
    #     判定：场景可识别且核心章节缺失 → 硬错误（退出码 1，不得交付）；
    #           未用场景结构（无「九」章节）或「九」标题无法识别场景 → 只警告，不拦。
    #     ⚠️ 比对字符串与注解**都用简体**（全仓统一简体，2026-09-18）。
    if not quiet:
        print("\n【11】场景完整性（大赛／B端／G端／投标 各自必须有的章节）")
    _scene_detect = [
        ("大赛", "创意设计执行"),
        ("B端", "生意拆解与机会量化"),
        ("G端", "政策依据与上位规划"),
        ("投标", "商务响应偏离表"),
    ]
    _scene_req = {
        "大赛": ["创意设计执行", "媒介排期表", "提案脚本", "评委问答预判"],
        "B端": ["生意拆解与机会量化", "财务测算与盈亏平衡", "组织与人力可行性", "商务条款"],
        "G端": ["政策依据与上位规划", "绩效目标与考核", "资金与保障", "汇报与评审", "合规与舆情红线"],
        "投标": ["商务响应偏离表", "需求理解", "实施与保障", "业绩与售后", "报价与资质"],
    }
    # ⚠️ 2026-09-17 改（运营 R3 指出）：原先只认「## 九 ·」这一节的标题 ——
    #    而各档的场景章编号并不固定（标准/B端到十三、G端到十四），
    #    一旦场景章不在「九」就整关跳过，导致**多项检查静默空转**。
    #    改成扫描全部 `## ` 标题去找场景关键词。
    _detected = None
    m9 = None
    for _h in re.findall(r"(?m)^##\s+(.+?)\s*$", body):
        for sc, kw in _scene_detect:
            if kw in _h:
                _detected = sc
                m9 = re.search(r"(?m)^##\s*" + re.escape(_h) + r"\s*$", body)
                break
        if _detected:
            break
    if _detected:
        req = _scene_req[_detected]
        missing = [c for c in req if c not in body]
        if not quiet:
            print(f"  {OK if not missing else NG} 识别为「{_detected}」场景；"
                  f"应有 {len(req)} 个场景章节，缺失 {len(missing)} 个"
                  + (f"：{'、'.join(missing)}" if missing else "（齐全）"))
        if missing:
            hard_errors.append(
                f"「{_detected}」场景缺失核心章节：{'、'.join(missing)}"
                f"—— 见 references/09-完整策划标准与评分表.md 该场景的必写章节清单"
                f"（composer --scene {_detected} 会自动注入）"
            )
    elif m9:
        if not quiet:
            print(f"  {WARN} 出现「九 ·」章节但无法识别场景（标题：{m9.group(1)[:28]}…），跳过场景校验")
        warnings.append("「九 ·」章节标题无法识别场景类型（应为 创意设计执行／生意拆解／政策依据／商务响应偏离表 之一），未做场景完整性校验")
    else:
        if not quiet:
            print(f"  {WARN} 未使用场景结构（无「九 ·」章节）—— 若为大赛／B端／G端／投标 交付，须补场景章节")
        warnings.append("未检测到场景章节（## 九 ·）。若本案为大赛／B端／G端／投标 交付，需补该场景必有的章节（见 references/09-完整策划标准与评分表.md）")

    # ── 【12】交付自检单防伪（2026-09-17 补：原本号段缺【12】，且自检单是**模型自填**）
    #    问题：协议 3 要求输出 12 项自检单，但「结果」那一栏由模型自己填 ——
    #    填 12 个 ✅ 就过关。这让全表打分最高的「交付治理」变成自我声明（假绿）。
    #    做法：① 抽出文档里自检单的每一行判断；② 与脚本本轮的真实判定比对；
    #          **自评高于脚本判定 → 硬错误**。这正是「假绿」的可操作定义。
    if not quiet:
        print("\n【12】交付自检单防伪（自评不得高于脚本判定）")
    _rows = re.findall(r"(?m)^\s*\|[^|\n]*自检|^\s*[-*]\s*\[[ xX]\]", text)
    _claimed_ok = len(re.findall(r"✅", text))
    _claimed_bad = len(re.findall(r"❌", text))
    # 脚本判定的「还能有几项通过」：本轮 hard_errors / warnings 越多，可用额度越低
    _quota = max(0, 12 - len(hard_errors) * 2 - len(warnings))
    if not quiet:
        print(f"  文档自评：✅ {_claimed_ok} 个 ／ ❌ {_claimed_bad} 个"
              f"（表格行 {len(_rows)} 条）")
        print(f"  脚本判定上限：✅ 至多 {_quota} 个（依本轮 {len(hard_errors)} 项硬错误、"
              f"{len(warnings)} 项警告推算）")
    if _claimed_ok > 0 and _claimed_ok > _quota and hard_errors:
        hard_errors.append(
            f"自检单**自评高于脚本判定**：文档里标了 {_claimed_ok} 个 ✅，"
            f"但本轮有 {len(hard_errors)} 项硬错误、{len(warnings)} 项警告 —— "
            f"按脚本判定最多只允许 {_quota} 个 ✅。**自检单不是自我声明。**")
    elif not hard_errors and _claimed_ok == 0 and _claimed_bad == 0:
        warnings.append("未见任何 ✅/❌ 标记 —— 协议 3 要求把 12 项自检单原样输出在回复中")

    # ── 【13】交叉引用与编号连续性（2026-09-17 新增）
    #    为什么要这一关：瞳话案前 12 关全绿，却有 **4 处**「详见第三部分 1.1 的反对意见」
    #    指向**根本不存在的章节**，而且团队十章编号重复（「三」出现两次）／倒序
    #    （一→三→二）／断号（十章里的「十」消失）。
    #    → 前 12 关查的都是「这份文件自己的性质」；「指到别处的引用是否真的指得到」
    #      是**跨章节**的性质，没有一关在查 —— 同一类「零件全合格、传动轴是断的」漏检。
    #    判定：引用指向不存在的章节／章号重复／子编号重复 → 硬错误；
    #          章号非递增、章内子编号非递增 → 警告（不拦，但交付前要人工确认）。
    if not quiet:
        print("\n【13】交叉引用与编号连续性（指向不存在的章节＝硬错误）")
    _cn = {c: i for i, c in enumerate("一二三四五六七八九十", 1)}
    _part = None
    _idx = set()                 # (部分, A.B) —— 真实存在的子章节
    _chaps = []                  # (部分, 中文章号, 章名)
    _subs = {}                   # (部分, 桶) -> [A.B ...] 按出现顺序
    _cur = None                  # 当前「### 中文数字、」章号
    _sec = ""                    # 当前「##」节标题（给没章号的子节归桶，避免误判非递增）
    for _l in body.split("\n"):
        _m = re.match(r"^#\s*第([一二三四五六七八九十]+)部分", _l)
        if _m:
            _part, _cur, _sec = _m.group(1), None, ""
            continue
        _m = re.match(r"^##\s+(.+?)\s*$", _l)
        if _m:                    # 进入新的 ## 节 → 上一个「### 章」的作用域结束
            _cur, _sec = None, _m.group(1)
            continue
        _m = re.match(r"^###\s*([一二三四五六七八九十]+)、(.+?)\s*$", _l)
        if _m:
            _cur = _m.group(1)
            _chaps.append((_part, _cur, _m.group(2)))
            continue
        _m = re.match(r"^#{3,4}\s*([0-9]+\.[0-9]+)\s", _l)
        if _m:
            _idx.add((_part, _m.group(1)))
            _bucket = _cur if _cur else f"§{_sec}"
            _subs.setdefault((_part, _bucket), []).append(_m.group(1))

    # ① 交叉引用：带部分号的「第X部分 A.B」必须指得到
    _tot = _dangling = 0
    _bad_refs = []
    for _m in re.finditer(r"第([一二三四五六七八九十]+)部分\s*([0-9]+\.[0-9]+)", body):
        _tot += 1
        if (_m.group(1), _m.group(2)) not in _idx:
            _dangling += 1
            _s = max(0, _m.start() - 40)
            _bad_refs.append(f"第{_m.group(1)}部分 {_m.group(2)} —— 指向不存在的章节"
                             f"（上下文：…{body[_s:_m.end() + 16].replace(chr(10), ' ')}…）")
    if not quiet:
        print(f"  {OK if not _dangling else NG} 带部分号的引用 {_tot} 处，指向不存在章节 {_dangling} 处")
        for _b in _bad_refs[:6]:
            print(f"       ✗ {_b}")
    if _dangling:
        hard_errors.append(f"交叉引用 {_dangling} 处指向不存在的章节（共 {_tot} 处引用）："
                           + "；".join(_bad_refs[:4])
                           + "　→ 改结构后必须同步改引用（见 references/11-防返工交付协议.md 铁律 4）")

    # ② 章号重复
    _seen, _dups = {}, []
    for _p, _c, _n in _chaps:
        _k = (_p, _c)
        if _k in _seen:
            _dups.append(f"第{_p}部分「{_c}、{_n}」与「{_c}、{_seen[_k]}」编号重复")
        _seen[_k] = _n
    if not quiet:
        print(f"  {OK if not _dups else NG} 章节（### 中文数字、）共 {len(_chaps)} 个，编号重复 {len(_dups)} 处")
        for _d in _dups[:6]:
            print(f"       ✗ {_d}")
    if _dups:
        hard_errors.append("章节编号重复：" + "；".join(_dups[:4]))

    # ③ 同一部分内子编号重复
    _sub_dup = []
    for _p in {p for p, _, _ in _chaps} | {p for p, _ in _idx}:
        _by = [s for (pp, s) in _idx if pp == _p]
        for _s in set(_by):
            if _by.count(_s) > 1:
                _sub_dup.append(f"第{_p}部分子编号 {_s} 出现 {_by.count(_s)} 次")
    if not quiet:
        print(f"  {OK if not _sub_dup else NG} 同部分内子编号重复 {len(_sub_dup)} 处")
        for _d in _sub_dup[:6]:
            print(f"       ✗ {_d}")
    if _sub_dup:
        hard_errors.append("子章节编号重复：" + "；".join(_sub_dup[:4]))

    # ④ 章号是否递增（同一部分内）
    _order_bad = []
    _lastp, _last = None, 0
    for _p, _c, _n in _chaps:
        if _p != _lastp:
            _lastp, _last = _p, 0
        _v = _cn.get(_c, 0)
        if _v and _v < _last:
            _order_bad.append(f"第{_p}部分：「{_c}、{_n}」排在更大的编号之后（应递增）")
        _last = max(_last, _v)
    # ⑤ 章内子编号是否递增
    _sub_order_bad = []
    for _k, _lst in _subs.items():
        _se = [int(x.split(".")[1]) for x in _lst]
        if _se != sorted(_se):
            _bad_at = next(i for i in range(1, len(_se)) if _se[i] < _se[i - 1])
            _sub_order_bad.append(f"第{_k[0]}部分「{_k[1]}」章内子编号非递增："
                                  f"{_lst[_bad_at - 1]} → {_lst[_bad_at]}")
    if not quiet:
        _nw = len(_order_bad) + len(_sub_order_bad)
        print(f"  {OK if not _nw else WARN} 编号顺序问题 {_nw} 处（章号倒序／章内子编号非递增）")
        for _d in (_order_bad + _sub_order_bad)[:6]:
            print(f"       ⚠ {_d}")
    for _d in _order_bad + _sub_order_bad:
        warnings.append(_d + "　→ 建议按正文出现顺序重编号（结构一改就要同步改引用）")

    # ── 【14】实质与创意判据（2026-09-17 新增，回应 4A／贝恩／BCG 三视角的第 6–9 条）
    #    共同病灶：**「有检查」但拦不住空话** —— 标题在场就算通过、字数够就算写开。
    #    本关四组判据全部针对「实质」：
    #      14a 执行摘要门槛（决策者唯一会读的一页，原本零门槛）
    #      14b AI 腔扫描（`09` 明文禁形容词堆砌，但脚本一直没有词表）
    #      14c 场景章深度（原本只查标题存在，正文 0 字也过）
    #      14d Big Idea 可复述性（创意完全没有专属判据）
    if not quiet:
        print("\n【14】实质与创意判据（执行摘要／AI 腔／场景深度／Big Idea）")

    _secs = {}
    for _m in re.finditer(r"(?m)^##\s+(.+?)\s*$", body):
        _start = _m.end()
        _nxt = re.search(r"(?m)^##\s+", body[_start:])
        _secs[_m.group(1)] = body[_start:_start + (_nxt.start() if _nxt else len(body))]

    # 14a 执行摘要
    _abs = next((v for k, v in _secs.items() if "执行摘要" in k or "执行摘要" in k), "")
    _n_num = len(re.findall(r"\d[\d,.]*\s*(?:元|%|％|万|万|单|单|人|店|次|万|万)", _abs))
    _has_bl = bool(re.search(r"盈亏线|盈亏线|保本|打平", _abs))
    if _abs:
        _ok_a = _n_num >= 4 and _has_bl
        if not quiet:
            print(f"  {OK if _ok_a else NG} 执行摘要：{len(_abs)} 字、带单位数字 {_n_num} 个"
                  f"（需 ≥4）、含盈亏线/保本 {'是' if _has_bl else '否'}")
        if not _ok_a:
            hard_errors.append(
                f"执行摘要不达标（数字 {_n_num}/4，盈亏线 {'有' if _has_bl else '无'}）—— "
                "决策者常常只看这一页；它必须自带 ≥4 个可核验数字 ＋ 一句盈亏线。")
    else:
        warnings.append("找不到「执行摘要」区块，14a 未生效")

    # 14b AI 腔
    _smell = {}
    for _w in AI_SMELL_WORDS:
        _c = body.count(_w)
        if _c:
            _smell[_w] = _c
    _struct = []
    if len(re.findall(r"不是[^，。]{1,12}——?是", body)) >= 3:
        _struct.append("「不是…是…」句式 ≥3 次")
    if len(re.findall(r"[\u4e00-\u9fff]{4}[，、][\u4e00-\u9fff]{4}[，、][\u4e00-\u9fff]{4}", body)) >= 3:
        _struct.append("四字格连排 ≥3 处")
    if not quiet:
        print(f"  {OK if not _smell and not _struct else WARN} AI 腔："
              f"词 {len(_smell)} 种{'（' + '、'.join(list(_smell)[:6]) + '）' if _smell else ''}"
              f"、结构特征 {len(_struct)} 项")
    if _smell or _struct:
        warnings.append("AI 腔：词 " + "、".join(f"{k}×{v}" for k, v in list(_smell.items())[:6])
                        + ("；" + "；".join(_struct) if _struct else "")
                        + "　→ `09` 明文禁形容词堆砌，改成动作与数字")

    # 14c 场景章深度
    _scene_req = {
        "大赛": ["创意设计执行", "媒介排期表", "提案脚本", "评委问答预判"],
        "B端": ["生意拆解与机会量化", "财务测算与盈亏平衡", "组织与人力可行性", "商务条款"],
        "G端": ["政策依据与上位规划", "绩效目标与考核", "资金与保障", "汇报与评审"],
        "投标": ["商务响应偏离表", "需求理解", "实施与保障", "业绩与售后"],
    }
    _thin_ch = []
    for _title, _txt in _secs.items():
        for _sc, _req in _scene_req.items():
            if any(c in _title for c in _req):
                _nums = len(re.findall(r"\d[\d,.]*\s*(?:元|%|％|万|万|天|周|个月|个月|次|单|单)", _txt))
                _tbl = _txt.count("\n|")
                _fill = len(re.findall(r"【填】|\{FILL\}", _txt))
                if _nums < 3 or _tbl < 1 or _fill > 0:
                    _thin_ch.append(f"{_title[:18]}（数字 {_nums}/3、表格行 {_tbl}、残留 【填】 {_fill}）")
    if not quiet:
        print(f"  {OK if not _thin_ch else NG} 场景章深度：不达标 {len(_thin_ch)} 章")
        for _c in _thin_ch[:6]:
            print(f"       ✗ {_c}")
    if _thin_ch:
        hard_errors.append("场景章内容不达标（只有标题不算完整）：" + "；".join(_thin_ch[:5])
                           + "　→ 每章须 ≥3 个带单位数字、≥1 张表、无 【填】 残留")

    # 14d Big Idea（仅在出现「大赛／提案」字样时判）
    _bi = re.search(r"Big Idea[^\n]*[:：]\s*(.+)", body)
    if _bi:
        _s = re.sub(r"[\s【】]", "", _bi.group(1))[:80]
        _len_ok = 6 <= len(_s) <= 22
        _conc = any(w in _s for w in CONCRETE_ACTION_WORDS + CONCRETE_OBJECT_WORDS)
        _gen = [w for w in GENERIC_CATEGORY_WORDS if w in _s]
        _prob = []
        if not _len_ok:
            _prob.append(f"长度 {len(_s)} 字（需 6–22，超长即不可复述）")
        if not _conc:
            _prob.append("未绑定具体动作或具体物")
        if _gen:
            _prob.append("含品类通用词：" + "、".join(_gen))
        if not quiet:
            print(f"  {OK if not _prob else NG} Big Idea：{_s[:30]}…"
                  + (f"（{'；'.join(_prob)}）" if _prob else ""))
        if _prob:
            hard_errors.append("Big Idea 不达标：" + "；".join(_prob)
                               + "　→ 判据是「一句能被别人复述、且绑定了具体动作或物」。")
    elif not quiet:
        print(f"  {INFO} 未见 Big Idea（非大赛／提案场景可忽略）")

    # ── 【15】新增章节的实质校验（2026-09-17 随 R1 的 C 组一起加）
    #    原则同【14】：**标题在场不算数**，要看它有没有被真填、且填得够硬。
    if not quiet:
        print("\n【15】新增章节实质校验（利益相关者／Red Team／洞察／取舍／回指／渠道）")

    # 15a 利益相关者与阻力处理
    _stake = [v for k, v in _secs.items() if "利益相关者" in k]
    if _stake:
        _txt = _stake[0]
        _rows = [r for r in _txt.split("\n") if r.strip().startswith("|")][1:]
        _against = len(re.findall(r"反对", _txt))
        _ok = len(_rows) >= 3 and _against >= 1
        if not quiet:
            print(f"  {OK if _ok else NG} 利益相关者：{len(_rows)} 个角色行（需 ≥3）、"
                  f"出现「反对」{_against} 次（需 ≥1）")
        if not _ok:
            hard_errors.append(
                "利益相关者章不达标 —— 需 ≥3 个角色且**至少 1 个反对者**。"
                "全是「支持」等于这份方案没做过落地推演。")
    else:
        warnings.append("未见「利益相关者与阻力处理」章 —— 桌面档／B端／G端 交付必须补（见 12-范式库）")

    # 15b Red Team
    _rt = [v for k, v in _secs.items() if "最可能怎么死" in k]
    if _rt:
        _txt = _rt[0]
        _n_arg = len(re.findall(r"最强反方论点", _txt))
        _n_cond = len(re.findall(r"成立的条件", _txt))
        _n_date = len(re.findall(r"成立的条件[^\n]*\d", _txt))
        _ok = _n_arg >= 3 and _n_cond >= 3 and _n_date >= 3
        if not quiet:
            print(f"  {OK if _ok else NG} Red Team：论点 {_n_arg}/3、条件 {_n_cond}/3、"
                  f"含数字或日期的条件 {_n_date}/3")
        if not _ok:
            hard_errors.append("Red Team 不达标 —— 定长三条，且每条的「成立条件」必须含数字或日期。")
    else:
        warnings.append("未见「这个方案最可能怎么死」（Red Team）章 —— 建议补")

    # 15c 洞察萃取
    _ins = [v for k, v in _secs.items() if "洞察萃取" in k]
    if _ins:
        _txt = _ins[0]
        _ok = ("共鸣测试" in _txt) and bool(re.search(r"(人|用户|用户)", _txt))
        if not quiet:
            print(f"  {OK if _ok else NG} 洞察萃取：含共鸣测试 {'是' if '共鸣测试' in _txt else '否'}")
        if not _ok:
            hard_errors.append("洞察萃取不达标 —— 必须有共鸣测试（念给 3 个人，几人说「啊，我也是」）。")

    # 15d 主动放弃
    _con = [v for k, v in _secs.items() if "约束与风险底线" in k]
    if _con:
        _n_give = len(re.findall(r"放弃|不做|砍掉|砍哪", _con[0]))
        _ok = _n_give >= 2
        if not quiet:
            print(f"  {OK if _ok else NG} 主动放弃：出现 {_n_give} 次（需 ≥2）")
        if not _ok:
            hard_errors.append("「主动放弃了什么」不足 2 条 —— 只写约束不写放弃，等于没做取舍（80/20 的反面）。")

    # 15e 创意回指
    if re.search(r"Big Idea", body):
        _n_trace = len(re.findall(r"回指", body))
        _ok = _n_trace >= 1 and bool(re.search(r"打法\s*\{?【?填?】?\}?\s*\d*", body))
        if not quiet:
            print(f"  {OK if _ok else NG} 创意回指：「回指」出现 {_n_trace} 次")
        if not _ok:
            hard_errors.append("创意没有回指策略 —— 每个样稿必须写「回指：本条创意解决【打法 N】的第【X】步」。")

    # 15g 议题树与假设台账（BCG 判据：没有议题树就写正文＝不合格）
    #     ⚠️ 2026-09-17 把关范围收窄：原先的「无条件硬错误」会误伤**速览类快案**
    #        （实测 smoke_test 的标杆稿 —— 一份便利店开学季快案 —— 因没有议题树被判硬错误）。
    #        → 议题树是**完整版方案**的判据，不是速览稿的。改为：
    #          · 稿里用了「〇 · 议题树与假设台账」这章 → 必须写够（硬错误）
    #          · 稿是完整版（八篇骨架）却没用这章 → 硬错误（漏了 BCG 的题眼）
    #          · 稿是速览类（没有完整八篇） → 只提醒，不拦
    _has_issue_tree = "议题树与假设台账" in body
    _is_full_plan = all(x in body for x in ["现状分析", "策略", "定位与口径", "预算明细"])
    _h_all = re.findall(r"\bH(\d+)\b", body)
    _distinct = sorted(set("H" + n for n in _h_all))
    _refer = sorted(h for h in _distinct if body.count(h) >= 2)   # 定义＋被引≥1 次
    if _has_issue_tree:
        _ok_g = len(_distinct) >= 3 and len(_refer) >= 3
        if not quiet:
            print(f"  {OK if _ok_g else NG} 议题树：H 编号 {len(_distinct)} 条（需 ≥3）、"
                  f"被正文引用 ≥1 次的 {len(_refer)} 条（需 ≥3）")
        if not _ok_g:
            hard_errors.append(
                f"议题树与假设台账不达标 —— 需要 ≥3 条可证伪的 H，且每条在正文里至少被引用一次"
                f"（现在有 {len(_distinct)} 条、被引 {len(_refer)} 条）。"
                "写在台账里却不被回应，等于没做假设驱动。")
    elif _is_full_plan:
        if not quiet:
            print(f"  {NG} 完整版方案缺「〇 · 议题树与假设台账」")
        hard_errors.append(
            "完整版方案缺「〇 · 议题树与假设台账」—— BCG 判据：没有议题树就写正文＝不合格。")
    else:
        if not quiet:
            print(f"  {INFO} 未使用议题树结构（速览类快案可忽略）")

    # 15f 渠道不可移植元素
    _ch = [v for k, v in _secs.items() if "不同形态" in k]
    if _ch:
        _txt = _ch[0]
        _rows = [r for r in _txt.split("\n") if r.strip().startswith("|")][1:]
        _ok = len(_rows) >= 1 and "不可移植" in _txt
        if not quiet:
            print(f"  {OK if _ok else NG} 渠道形态表：{len(_rows)} 行、含「不可移植元素」列 "
                  f"{'是' if '不可移植' in _txt else '否'}")
        if not _ok:
            hard_errors.append("渠道只是「换名字」—— 5.1 表必须有「不可移植元素」列，且每渠道至少 1 个。")

    # ── 【16】合规红线与量化可验（2026-09-17 随 R2 一起加）
    #    ⚠️ 本关的很多要求属「**完整版方案才该有**」。今天已经**连续四次**因为
    #       新硬关无条件生效而误伤速览类快案（smoke_test 的标杆稿）：
    #         ① `8a 为什么这么做须含实质`  ② `15g 议题树`  ③ `16f 敏感性`  ④ `16g KPI 频率/责任人`
    #       所以不再逐次打补丁，改成一个显式助手 —— 新加的「完整版要求」一律走它。
    def _hard_if_full(msg):
        """完整版才判硬错误；速览类快案降为警告。（判据：_is_full_plan）"""
        if _is_full_plan:
            hard_errors.append(msg)
        else:
            warnings.append(msg + "（速览类快案可忽略；若本案其实是完整版请补）")

    if not quiet:
        print("\n【16】合规红线与量化可验（个人信息／文号／偏离值／可证伪／因果／敏感性）")

    # 16a 个人信息红线（R2-18）
    _pid = re.findall(r"\b1[3-9]\d{9}\b", body)
    _idc = re.findall(r"\b\d{17}[\dXx]\b", body)
    if _pid or _idc:
        if not quiet:
            print(f"  {NG} 疑似个人信息：手机号 {len(_pid)} 处、身份证号 {len(_idc)} 处")
        hard_errors.append(f"疑似出现个人信息（手机号 {len(_pid)}／身份证 {len(_idc)}）—— "
                           f"数据合规红线，交付前必须删除或脱敏。")
    elif not quiet:
        print(f"  {OK} 未见手机号／身份证号")

    # 16b G 端政策文号（R2-16）
    if re.search(r"政策依据|政策依据", body):
        _doc_no = re.findall(r"〔\s*20\d{2}\s*〕\s*第?\d+\s*号?号?|国发|国发|国办发|国办发", body)
        if not _doc_no:
            if not quiet:
                print(f"  {NG} G 端政策依据：未见任何公文文号（〔20XX〕第 N 号／国发 等）")
            hard_errors.append("政策依据章没有公文文号 —— 写「依据国家相关政策」等于没依据，"
                               "评审第一关即出局。需写到「文件名称＋文号＋具体条款」。")
        elif not quiet:
            print(f"  {OK} 政策文号：命中 {len(_doc_no)} 处")

    # 16c 投标偏离表响应值（R2-17）
    if re.search(r"商务响应偏离表|商务响应偏离表", body):
        _rows = [r for r in re.findall(r"(?m)^\|.*响应.*\|.*$|^\|.*响应.*\|.*$", body)]
        _resps = re.findall(r"(完全响应|完全响应|正偏离|正偏离|负偏离|负偏离)", body)
        if not _resps:
            if not quiet:
                print(f"  {NG} 投标偏离表：未见「完全响应／正偏离／负偏离」的响应判定")
            hard_errors.append("商务响应偏离表没写响应判定 —— 每条招标要求必须标"
                               "「完全响应／正偏离／负偏离」，负偏离还需给补救说明。")
        elif not quiet:
            print(f"  {OK} 投标偏离表：响应判定 {len(_resps)} 处"
                  f"（负偏离 {sum(1 for x in _resps if '负' in x or '负' in x)} 处）")

    # 16d 假设可证伪（R2-1）
    _htab = re.search(r"(?m)^\|\s*H#.*$", body)
    if _htab:
        _rows = [r for r in re.findall(r"(?m)^\|\s*H\d+.*$", body)]
        _weak = [r for r in _rows
                 if not re.search(r"若|如果|一旦|可验证|可验证|验证方式|验证方式|数据截止|数据截止", r)]
        if not quiet:
            print(f"  {OK if not _weak else NG} 假设可证伪：{len(_rows)} 行，其中 {len(_weak)} 行看不出证伪条件")
        if _weak:
            hard_errors.append(
                f"{len(_weak)} 条假设看不出「怎么被证伪」——写「用户喜欢新品」这种不可证伪的假设"
                f"不算假设驱动。每条须能写出「若拿到什么，就说明我错了」。")

    # 16e 相关当因果（R2-10）
    _causal_claims = []
    for _m in re.finditer(r"(带动|带动|带来|带来|提升|拉动|拉动)[^。]{0,15}?\d+(\.\d+)?\s*[%％]", body):
        _s = body[max(0, _m.start() - 20):_m.end() + 10]
        if not re.search(r"较|较|vs|VS|基期|对照|对照|前提|假设|假设|预估|预估", _s):
            _causal_claims.append(_s.replace("\n", " ")[:36])
    if _causal_claims:
        if not quiet:
            print(f"  {WARN} 疑似「相关当因果」{len(_causal_claims)} 处（无基期／对照／前提）")
            for _c in _causal_claims[:3]:
                print(f"       ⚠ {_c}…")
        warnings.append(f"疑似把相关当因果 {len(_causal_claims)} 处 —— 效果类数字须带"
                        f"「较／基期／对照／前提」，否则只是愿望：{'；'.join(_causal_claims[:2])}")
    elif not quiet:
        print(f"  {OK} 效果类数字未见裸因果句")

    # 16f 敏感性分析（R2-3）
    #    ⚠️ 2026-09-17 第三次踩同一个坑：新加的硬关又误伤了**速览类快案**
    #       （smoke_test 的标杆稿 —— 便利店开学季快案）。
    #       前两次分别是「议题树」（15g）与「为什么这么做须含实质」（8a）。
    #       → 固化成规律，不再逐次打补丁：
    #         **凡是「完整版才该有」的要求，一律先判 `_is_full_plan`；
    #           速览类快案只提醒、不判硬错误。**
    #         判据：完整版＝同时有「现状分析／策略／定位与口径／预算明细」四章。
    if re.search(r"盈亏线|盈亏线|保本", body):
        _sens = re.search(r"乐观[\s\S]{0,300}?悲观|乐观[\s\S]{0,300}?悲观", body)
        if _sens:
            # ⚠️ 2026-09-17（R5 投资人视角第 5 条）：原判据只是「乐观…悲观 两词在 300 字内共现」——
            #   把悲观档写成「−10%」也能全绿，那不是压力测试，是装饰。
            #   加一条：三档的数字必须互不相等（否则等于没分档）。
            _nums = re.findall(r"\d+(?:\.\d+)?", _sens.group(0))[:12]
            _distinct = len(set(_nums))
            if _distinct < 3:
                if not quiet:
                    print(f"  {NG} 敏感性：三档数字看不出差异（不同值仅 {_distinct} 个）")
                _hard_if_full("敏感性分析三档几乎相同 —— 把悲观档写成 −10% 不是压力测试。"
                              "悲观档的关键参数（价格/流量/投放成本）至少一项降幅 ≥30%。")
            elif not quiet:
                print(f"  {OK} 敏感性分析：三档齐、数字有区分（{_distinct} 个不同值）")
        else:
            if not quiet:
                print(f"  {'❌' if _is_full_plan else WARN} 有盈亏线但无三档敏感性"
                      + ("（完整版强制）" if _is_full_plan else "（速览类快案可忽略）"))
            _hard_if_full("有盈亏线却没有敏感性分析 —— 单点盈亏线是假精确；"
                          "关键结论须给乐观／基准／悲观三档。")
    elif not quiet:
        print(f"  {INFO} 未见盈亏线，16f 未生效")

    # 16g KPI 的「观测频率」与「谁来测」（R2-5）
    #    ⚠️ 没有频率与责任人的 KPI ＝ 没人会去看的指标。
    _kpi_hdr = re.search(r"(?m)^\|[^\n]*KPI[^\n]*\|\s*$", body)
    if _kpi_hdr:
        _h = _kpi_hdr.group(0)
        _has_freq = bool(re.search(r"频率|频率|每日|每周|每月|多久", _h))
        _has_owner = bool(re.search(r"谁|谁|负责|负责|盯|观测人|观测人", _h))
        if not quiet:
            print(f"  {OK if (_has_freq and _has_owner) else NG} KPI 表：频率列 "
                  f"{'有' if _has_freq else '缺'}、责任人列 {'有' if _has_owner else '缺'}")
        if not (_has_freq and _has_owner):
            _hard_if_full(
                "KPI 表缺「观测频率」或「谁来测」—— 没有频率与责任人的指标没人会去看，"
                "等于没有指标。（表头需含 频率/多久 与 谁/负责 两类列）")
    else:
        warnings.append("未找到 KPI 表头，16g 未生效")

    # 16h 数字三要素（来源／口径／时点）（R2-4）—— 先只警告，不拦
    _nums = re.findall(r"[^\n。；]{0,30}?\d+(?:\.\d+)?\s*(?:%|％|元|万元|万)", body)
    _nu = [x for x in _nums if not re.search(r"预算|分项|分项|行动|行动|合计|合计|【填】|占位", x)]
    if _nu:
        _ok_n = [x for x in _nu
                 if re.search(r"来源|来源|据《|据《|来自|来自|后台|后台|年报|年报|问卷|问卷|"
                              r"n\s*=|我方测算|我方测算|假设|假设|估算|口径|口径", x)]
        _rate = len(_ok_n) / len(_nu)
        if not quiet:
            print(f"  {OK if _rate >= 0.8 else WARN} 数字三要素（来源／口径／时点）："
                  f"{len(_ok_n)}/{len(_nu)} = {_rate:.0%}（建议 ≥80%）")
        if _rate < 0.8:
            warnings.append(
                f"数字三要素覆盖率 {_rate:.0%}（{len(_ok_n)}/{len(_nu)}）—— "
                f"裸数字（无来源的 %、金额）会被客户追问。建议补「来源／口径／时点」。")

    # ── 【17】承接与危机（2026-09-17 随 R5 一起加：私域／客服舆情两视角的共同要求）
    #    共同病灶：方案只写「做什么」，不写「出事时谁接」。
    if not quiet:
        print("\n【17】承接与危机（私域闭环／客服／超卖退款／舆情发声人）")

    # 17a 私域四环是否成链（加微→首单→复购→转介绍）
    if re.search(r"加微钩子|加微钩子|私域", body):
        _chain = {k: (k in body) for k in ("加微", "首单", "复购", "转介绍")}
        _miss = [k for k, v in _chain.items() if not v]
        if not quiet:
            print(f"  {OK if not _miss else WARN} 私域链路四环（加微→首单→复购→转介绍）："
                  f"缺 {len(_miss)} 环" + (f"：{'、'.join(_miss)}" if _miss else ""))
        if len(_miss) >= 2:
            _hard_if_full(f"私域链路缺 {len(_miss)} 环（{'、'.join(_miss)}）—— "
                          f"链头加微与链尾转介绍最容易漏；缺两环以上不成链。")
        # 24 小时起点（起点必须是「加好友后」，不是「购买后」）
        if "24 小时" in body or "24 小时" in body:
            if not re.search(r"(加好友|加微)[^\n]{0,20}24\s*小时|24\s*小时[^\n]{0,20}(加好友|加微)", body):
                warnings.append("私域有 24 小时动作，但没写清「起点是加好友后」——"
                                "起点写成「购买后」，新好友 24 小时就无人管。")

    # 17b 客户侧超卖与退款
    if re.search(r"库存|库存|超卖|超卖", body) or _is_full_plan:
        for _k, _msg in (("超卖", "超卖与履约兜底（承诺了优惠却发不出货 = 信任崩塌点）"),
                         ("退款", "退款与纠纷升级路径（一线会自己乱来）")):
            if not re.search(_k, body):
                _hard_if_full(f"缺「{_msg}」—— 出事了没有成文约定。")

    # 17c 舆情：发声人是否唯一且写了时限
    if re.search(r"舆情|舆情|对外发声|对外发声", body):
        _has_delay = bool(re.search(r"\d+\s*小时|\d+\s*小时|当天|当天", body))
        _has_spokes = bool(re.search(r"发声人|发声人|对外口径|对外口径|统一口径|统一」?口径", body))
        if not quiet:
            print(f"  {OK if (_has_delay and _has_spokes) else NG} 舆情：回应时限 "
                  f"{'有' if _has_delay else '缺'}、发声人／对外口径 {'有' if _has_spokes else '缺'}")
        if not (_has_delay and _has_spokes):
            hard_errors.append("舆情预案不完整 —— 必须写「几小时内回应」与「谁是唯一发声人」。"
                               "没写的后果：危机时一线各自回话，口径打架。")

    # ── 【18】版权与授权（2026-09-17 随 R6 法务视角加）
    #    为什么单独一关：全库「授权／版权」命中约 30 处，
    #    而**没有一处落在生成稿的必需字段里** —— 出事时甚么都拿不出来。
    if not quiet:
        print("\n【18】版权与授权（音乐／字体／肖像／UGC／非遗专利）")

    # 18a 音乐：不得用热门歌
    if re.search(r"BGM|背景音乐|背景音乐|配乐|配乐|音效", body):
        if not re.search(r"免费商用|免费商用|曲库|曲库|自行录制|自行录制|已授权|已授权", body):
            hard_errors.append(
                "方案提到 BGM／音效，却没写明**来源** —— 必须写「平台免费商用曲库／自行录制」。"
                "短视频 BGM 是音著协／唱片公司索赔最高频的场景。")
    # 18b 字体授权
    if re.search(r"字体|字体", body):
        if not re.search(r"授权类型|授权类型|系统自带|系统自带|已购|已购|免费商用|免费商用", body):
            warnings.append("方案提到字体，却未写授权类型（系统自带／已购／免费商用）——"
                            "方正／汉仪批量维权是营销物料最常见的索赔函来源。")
    # 18c 肖像权
    if re.search(r"模特|素人|达人出镜|达人出镜|拍摄|拍摄", body):
        if "肖像" not in body and "授权书" not in body and "授权书" not in body:
            hard_errors.append("方案涉及出镜拍摄（模特／素人／达人），但没写**肖像／声音授权书** —— "
                               "「免单换拍摄」不等于肖像授权。")
    # 18d 非遗／专利／认证须附证明文件
    if re.search(r"非遗|非遗|专利|专利|认证|认证", body):
        if not re.search(r"证书编号|证书编号|证明文件|证明文件|文件编号|文件编号|ZL\d|有效期", body):
            _hard_if_full("方案宣称「非遗／专利／认证」却**未附证明文件编号与有效期** —— "
                          "这是虚假宣传被举报的高发入口。")
    # 18e UGC 授权
    if re.search(r"UGC|用户投稿|用户投稿|征集|征集|打卡征集", body):
        if not re.search(r"授权|授权|同意品牌|商用范围|商用范围", body):
            warnings.append("方案有 UGC／征集类动作，但没写内容版权归属与商用范围 —— "
                            "二次商用会构成超范围使用。")

    # ── 结论
    print("\n" + "=" * 64)
    if hard_errors:
        print(f"{NG} 自检不通过（{len(hard_errors)} 项硬错误）：")
        for e in hard_errors:
            print(f"   · {e}")
        if warnings:
            print(f"\n{WARN} 另有 {len(warnings)} 项警告需人工确认：")
            for w in warnings:
                print(f"   · {w}")
        print("\n→ 修正硬错误后重跑。**不得宣告交付**（协议 3）。")
        emit_json(hard_errors, warnings, 1)
        sys.exit(1)

    print(f"{OK} 自检通过（硬错误 0 项）。")
    if warnings:
        print(f"{WARN} {len(warnings)} 项警告，交付前请人工确认：")
        for w in warnings:
            print(f"   · {w}")
    print("\n→ 请把 12 项《交付自检单》原样输出在交付回复中（协议 3）。")
    emit_json([], warnings, 0)
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
        print("   2) 若属环境问题（文件读不到／编码异常），改用 Markdown 协议手工比对 §六 清单，不要卡在这里；")
        print("   3) 同一项连续 2 次不过 → 停止重试，把问题摊给用户决定。")
        sys.exit(2)
