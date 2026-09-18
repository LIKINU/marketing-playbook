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
    # 2026-09-19 补（A 批 · 合规视角第 1 条）：知识库自己写着这些词被罚过 80 万，
    #   而硬错误词表里居然没有它们 ——「知识库知道、判据表没有」，最典型的例子。
    "最先进", "最专业", "最权威", "最有效", "最新科技", "最顶级",
    "世界级", "亚洲顶尖", "顶尖", "首屈一指", "无与伦比", "绝版", "王者", "霸主",
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

# 名次式／外语／带前缀的极限表述（2026-09-19 A 批 · 合规视角第 1 条）
#   为什么单列一张正则表：只列表是拦不住的 ——「全国第三名」「NO.1」「TOP1」
#   在语义上与「第一」等价，但**一个字面词都不命中**。
#   ⚠️ 每条都带**必须的前缀或限定**，避免误伤：「第一步」不是「第一名」、
#      单独的「领先」不是极限表述（「领先一步」是普通描述）、「首个试点」也不违规。
BANNED_HARD_RE = [
    r"第[一二三四五六七八九十\d]+名",                    # 全国第三名
    r"(?:全国|行业|全网|全球|世界|亚洲|中国|市场|品类|销量|排名)第一",
    r"(?:全国|行业|全网|全球|亚洲|中国)首[个家]",        # 全国首个／行业首家
    r"(?i)\bNO\.?\s*0?1\b", r"(?i)\bTOP\s*0?1\b",
    r"领先(?:品牌|地位|水平)",                          # 单独「领先」不拦
    r"独家(?:配方|首发|代理|版权)",
]

# 效果类承诺（2026-09-19 A 批 · 合规视角第 3 条）：`承诺词 + 15 字内 + 结果` 即拦。
#   ⚠️ 「无效退款」**故意不收** —— 它是合规的消费者承诺机制（用不好是运营问题，
#      不是广告违法），写成硬错误会把正经营销动作也拦下来。
BANNED_PROMISE_RE = [
    r"(?:保证|承诺|确保|百分百|100%|必然|一定)[^。；\n]{0,15}"
    r"(?:涨粉|增粉|翻\d*倍|回本|盈利|赚|过万|提升\s*\d+\s*[%％]|录取|过线|上岸|中签|成功)",
    r"(?:包过|包上岸|包就业|保offer|保录取|躺赚|月入过万|稳赚不赔)",
]

# 财务／统计语境白名单：命中则从扫描文本挖掉
# （例：「保本单量」是财务术语，不是金融产品的「保本」承诺 —— 不豁免会一直误报）
BANNED_WHITELIST_PATTERNS = [
    r"保本(单量|销量|点|线|值|门槛|测算|单数|分析)",
    r"回本(周期|单量|销量|点|时间|线)",
    # ⚠️ 2026-09-19（六体系核对 · 体系6 agent 报「空骨架自报 13 个违规词」）——实测四类误报，
    #   全部**不是真违规**，但会被判成硬错误（真稿交付前被拦下来）：
    #   ① **子串误命中**：`历史上最真实` 含 `史上最`；`为每层定唯一目标` 含 `唯一`
    #      （中文没有词边界，只能把**已知的合法长词**列进来抵消）；
    #   ② **框架词**：`最强反方论点` 是骨架自己的字段名（Red Team 那三条）；
    #   ③ **引用／否定**：`不诱导分享`、`不向个人号收款` —— 那是在**引述被禁止的做法**；
    #   ④ **规则说明**：`不写留存期限＝默认永久保存` —— 那是在**讲规则**。
    #   → ①② 用这里的白名单抵消；③ 由下面的「否定语境」规则处理；
    #     ④ 与 ③ 同类（含「禁」「不得」字样）也归否定语境。
    #   **判准：判据要拦的是「我们这么宣称」，不是「我们说别人不能这么宣称」。**
    r"历史上最真实",
    r"最佳真我",
    r"唯一目标",
    r"唯一要拿到的结果",
    r"唯一发声人",
    r"唯一对外发声口",
    r"最强反方论点",
    r"最强反方",
    r"永久保存",
]
# ⚠️ 规矩（给以后加章节的人）：**新增的字段名／表头若含禁词，把它加进上面这张表**。
#   字段名是「我们要填什么」，不是「我们宣称什么」——两者必须分开。

# 「否定/引用语境」标记：某个违规词**在本文里的每一次出现**都紧跟在这些字后面 →
#   它是在被引述、不是在被使用 → 不计为违规。
NEG_CTX = ("不", "禁", "不得", "不能", "勿", "避免", "杜绝", "反对", "拒绝", "严禁")
NEG_WINDOW = 8


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
    # ⚠️ 2026-09-19（六体系核对 · 体系6 agent 报「空骨架自报 13 个违规词」）——
    #   ±1 行的豁免**盖不住两整类**，实测都会把真稿误伤成硬错误：
    #   ① **禁语表整块**：3.2 的禁用词表、3.5 的「本行业禁语」里**必须原样写出违规说法**
    #      （不然一线不知道什么不能说），而 ±1 行只护住表头附近 → 表体里的违规词照样被判。
    #   ② **表头行**：表头是「字段名」不是「对外的宣称」。实测
    #      `| 阶段 | 起止 | 主推渠道 | 该段预算 | 该段唯一要拿到的结果 |` 会把 `唯一` 判成违规。
    #   → 处置：**表头/分隔行整行排除**；**整张表块**只要表头或紧邻上一行含禁用类标记，则全块排除。
    #   **判准：判据要拦的是「我们这么宣称」，不是「我们说别人不能这么宣称」。**
    _i = 0
    while _i < len(lines):
        if lines[_i].strip().startswith("|"):
            _j = _i
            while _j < len(lines) and lines[_j].strip().startswith("|"):
                _j += 1
            safe_idx.add(_i)                                   # 表头行（字段名）
            for _k in range(_i, _j):
                if "---" in lines[_k]:
                    safe_idx.add(_k)                           # 分隔行
            _i = _j
            continue
        _i += 1

    _BAN_MARK = ("禁用", "禁止", "不能说", "红线", "不得", "违规后果", "违规", "违法")
    _i = 0
    while _i < len(lines):
        if lines[_i].strip().startswith("|"):
            _j = _i
            while _j < len(lines) and lines[_j].strip().startswith("|"):
                _j += 1
            _hdr = lines[_i]
            _prev = ""
            for _k in range(_i - 1, -1, -1):
                if lines[_k].strip():
                    _prev = lines[_k]
                    break
            if any(m in _hdr or m in _prev for m in _BAN_MARK):
                for _k in range(_i, _j):
                    safe_idx.add(_k)
            _i = _j
            continue
        _i += 1
    scan_text = "\n".join(ln for i, ln in enumerate(lines) if i not in safe_idx)
    # 套用财务／统计语境白名单（避免「保本单量」这类术语误报）
    for pat in BANNED_WHITELIST_PATTERNS:
        scan_text = re.sub(pat, "", scan_text)
    found = sorted({b for b in banned if b and b in scan_text})
    hard_found = sorted({b for b in BANNED_HARD if b and b in scan_text})

    # ③ 否定/引用语境：某词**每一次**出现都在「不／禁／不得／不能…」之后 → 是在引述，不是在使用。
    def _all_quoted(_w):
        for _m in re.finditer(re.escape(_w), scan_text):
            _pre = scan_text[max(0, _m.start() - NEG_WINDOW):_m.start()]
            if not any(_n in _pre for _n in NEG_CTX):
                return False
        return True

    found = [w for w in found if not _all_quoted(w)]
    hard_found = [w for w in hard_found if not _all_quoted(w)]
    # 正则类（名次式／外语／效果承诺）—— 与词表同等对待，都是硬错误
    for _pat in BANNED_HARD_RE + BANNED_PROMISE_RE:
        for _m in re.finditer(_pat, scan_text):
            hard_found.append(re.sub(r"[*\s]+", "", _m.group(0)))
    hard_found = sorted(set(hard_found))
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

    # ⚠️ 2026-09-19（回基线复测时发现）：`_secs` **只切 `^## `（二级标题）**，
    #   而骨架里 64/88 个标题是 `### `（三级）—— 于是「按标题名找 `###` 节」的判据
    #   **永远取不到值**：`if _sec:` 不成立 → 后面的判据整段**静默跳过**。
    #   实测死掉的三处：15b Red Team（`### 8.7`）、15d 主动放弃（`### 1.5`）、
    #   15f 渠道形态（`### 5.1`）。**它们不是判错了，是从来没跑过。**
    # → 凡按标题名取 `###` 节，一律走这个助手（`^#{2,3}`），并**必须写 else 分支报出来**。
    def _sec_any(*keys):
        for _m in re.finditer(r"(?ms)^#{2,3}\s+([^\n]*)\n(.*?)(?=^#{2,3}\s|\Z)", body):
            if any(k in _m.group(1) for k in keys):
                return _m.group(1) + "\n" + _m.group(2)
        return ""

    def _secs_all(*keys):
        r"""**所有**命中节（不是第一个）。
        ⚠️ 2026-09-19：`_sec_any("A","B")` 只回**第一个**命中 —— 若 A 在 B 之前，
        A 被选中、**B 根本没被看**（实测：主动放弃查了 1.3 就再也没看 1.5，
        于是 1.5 里明明写着两条「放弃」却被判「0 次」）。多目标一律用这个。"""
        return [_m.group(1) + "\n" + _m.group(2)
                for _m in re.finditer(r"(?ms)^#{2,3}\s+([^\n]*)\n(.*?)(?=^#{2,3}\s|\Z)", body)
                if any(k in _m.group(1) for k in keys)]

    # ⚠️ 2026-09-19：`_is_full_plan` 与 `_hard_if_full` **必须在所有判据之前定义** ——
    #   原先它们躺在 15g／【16】开头（行号靠后），而 15d／15f 在它们**之前**执行；
    #   一旦给早段的 else 分支加上 `_hard_if_full(...)`，就会 `NameError`（脚本当场崩）。
    #   （本仓库的规矩：错误路径从没被跑过，写的时候看不出来。）
    _is_full_plan = all(x in body for x in ["现状分析", "策略", "定位与口径", "预算明细"])

    def _hard_if_full(msg):
        """完整版才判硬错误；速览类快案降为警告。（判据：_is_full_plan）"""
        if _is_full_plan:
            hard_errors.append(msg)
        else:
            warnings.append(msg + "（速览类快案可忽略；若本案其实是完整版请补）")

    # 表格小工具（15f／【28】共用）—— 同样必须在所有判据之前定义。
    def _cells(line):
        return [c.strip() for c in line.strip().strip("|").split("|")]

    def _tbl(sec):
        rows = [r for r in sec.split("\n") if r.strip().startswith("|")]
        if len(rows) < 2:
            return [], []
        return _cells(rows[0]), [_cells(r) for r in rows[1:] if "---" not in r]

    def _col(hdr, *keys):
        for _i, _c in enumerate(hdr):
            if any(k in _c for k in keys):
                return _i
        return -1

    def _cell(row, i):
        return row[i].strip() if 0 <= i < len(row) else ""

    def _zh(s):
        return len(re.findall(r"[\u4e00-\u9fff]", s))

    # 「空/占位」判定（15f 之外、22a 与【31】共用）——
    # ⚠️ 2026-09-19 **第三次**栽在同一处：助手定义晚于调用点 → 22a 一调 `_is_ph` 就
    #    `UnboundLocalError`（脚本 rc=2，而不是判错）。**本仓库已三次（_hard_if_full／_tbl／_is_ph）。**
    #    → 凡是**多个关卡共用**的助手，一律放在这里，不要写进某一关的内部。
    _PH = re.compile(r"^(?:占位|待补|待定|待确认|TBD|Todo|N/?A)$", re.I)

    def _is_ph(s):
        s = (s or "").strip()
        if "【填】" in s:
            return True
        _t2 = re.sub(r"[*\s]", "", s)
        return (not _t2) or bool(_PH.match(_t2))

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

    # 14d Big Idea（**2026-09-19 升级：非速览档都要求**，不再「非大赛可忽略」）
    #
    # ⚠️ 为什么升级：原先创意链**只挂大赛档**，所以这里写「非大赛／提案场景可忽略」。
    #    `composer` 现在把「五·〇 · 创意主张」补进了 `COMMON_HEADS`（非速览档全有），
    #    **判据必须跟着走** —— 否则又变回「骨架给了位、脚本查不到」（本仓库的坑 5）。
    #    速览档走 `build_lite`，根本不含这章，靠 `_is_full_hint` 自动豁免。
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
        # 2026-09-19 新增（agency-4a 第 4 条）：两个**可判定测试**必须写出来 ——
        #   复述测试证明「记得住」，换名测试证明「是这家的」（换掉品牌名就失效）。
        #   只有长度／含具体词这两条是**文本启发式**，证明不了「真有人能复述」。
        if "复述测试" not in body:
            _prob.append("缺「复述测试」行（念给 3 个没看过方案的人，几人能原样复述）")
        else:
            _m = re.search(r"复述测试[^\n]*?(\d+)\s*人", body)
            if not _m or int(_m.group(1)) < 2:
                _prob.append("复述测试人数 <2 或没写数字（≥2/3 才算过）")
        if "换名测试" not in body:
            _prob.append("缺「换名测试」行（把品牌名换成「X」后本句应不成立）")
        elif not re.search(r"换名测试[^\n]*?不成立", body):
            _prob.append("换名测试未写结论「不成立」—— 还成立＝这只是句谁都能用的行业口号")
        if not quiet:
            print(f"  {OK if not _prob else NG} Big Idea：{_s[:30]}…"
                  + (f"（{'；'.join(_prob)}）" if _prob else ""))
        if _prob:
            hard_errors.append("Big Idea 不达标：" + "；".join(_prob)
                               + "　→ 判据是「一句能被别人复述、绑定了具体动作或物、换掉品牌名就失效」。")
    elif _is_full_hint(text):
        hard_errors.append("完整版方案**未见 Big Idea / 创意主张** —— 创意决策层缺失，"
                           "从定位直接跳到物料表。缺它＝创意没法被评估（速览类快案不适用本关）。")
    elif not quiet:
        print(f"  {INFO} 未见 Big Idea（速览类快案不适用本关）")

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
    # ⚠️ 2026-09-19：原先用 `_secs` 找 `### 8.7` → **从不触发**（见 `_sec_any` 的说明）。
    _rt_txt = _sec_any("最可能怎么死")
    _rt = [_rt_txt] if _rt_txt else []
    if _rt:
        _txt = _rt[0]
        _n_arg = len(re.findall(r"最强反方论点", _txt))
        _n_cond = len(re.findall(r"成立的条件", _txt))
        _n_date = len(re.findall(r"成立的条件[^\n]*\d", _txt))
        _ok = _n_arg >= 3 and _n_cond >= 3 and _n_date >= 3
        # ⚠️ 2026-09-19（回基线复测时发现）：骨架里写着「三条必须**互不相同**（两两相似会被判复读）」
        #   —— 但那句**承诺没有判据兑现**（本条原先只数条数与数字）。**骨架承诺的东西必须真被判**，
        #   否则就是把「会被检查」写进交付稿骗填稿的人。这里补上复读检测：
        #   三条论点两两做 bigram Jaccard，任一对 ≥0.5 即判「同一句话换了个说法」。
        def _bigrams(s):
            s = re.sub(r"[\s，。、；：（）()「」【】\*_#\-—…0-9A-Za-z]", "", s)
            return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else set()
        _args = [re.sub(r"^[-\s*]*", "", x.strip())[:200]
                 for x in re.findall(r"最强反方论点[：:]\s*([^\n]+)", _txt)]
        _dup = []
        for _i in range(len(_args)):
            for _j in range(_i + 1, len(_args)):
                _a, _b = _bigrams(_args[_i]), _bigrams(_args[_j])
                if _a and _b:
                    _jac = len(_a & _b) / len(_a | _b)
                    if _jac >= 0.5:
                        _dup.append((_i + 1, _j + 1, _jac))
        if not quiet:
            print(f"  {OK if _ok and not _dup else NG} Red Team：论点 {_n_arg}/3、条件 {_n_cond}/3、"
                  f"含数字或日期的条件 {_n_date}/3"
                  + (f"、**复读 {len(_dup)} 对**" if _dup else "、三条互不相同"))
        if not _ok:
            hard_errors.append("Red Team 不达标 —— 定长三条，且每条的「成立条件」必须含数字或日期。")
        for _i, _j, _jac in _dup[:3]:
            hard_errors.append(
                f"Red Team 第 {_i} 条与第 {_j} 条是同一句话换说法（相似度 {_jac:.0%} ≥50%）—— "
                f"骨架里写着「三条必须互不相同（两两相似会被判复读）」，而**提三次同一个反对意见"
                f"不叫压力测试**。换成三个不同方向的死法（客户不买／竞品跟进／执行不了）。")
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
    # ⚠️ 2026-09-19：原先用 `_secs` 找 `### 1.5 约束与风险底线` → **从不触发**，
    #   而且**连提醒都没有**（没有 else 分支）—— 比判错更危险的一种状态。
    _con = _secs_all("约束与风险底线", "已排除的假设")
    if _con:
        _n_give = len(re.findall(r"放弃|不做|砍掉|砍哪", "\n".join(_con)))
        _ok = _n_give >= 2
        if not quiet:
            print(f"  {OK if _ok else NG} 主动放弃：出现 {_n_give} 次（需 ≥2）")
        if not _ok:
            hard_errors.append("「主动放弃了什么」不足 2 条 —— 只写约束不写放弃，等于没做取舍（80/20 的反面）。")
    else:
        if not quiet:
            print(f"  {NG} 主动放弃：**未找到 1.5 约束与风险底线**（骨架会给，缺了就是被删了）")
        _hard_if_full("缺「1.5 约束与风险底线（含主动放弃）」—— **只写约束不写放弃，等于没做取舍**："
                      "一份不写「放弃了什么」的方案，无法证明资源被放在了回报最高的地方。")

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
    # `_is_full_plan` 已上移（见 `_sec_any` 之后），此处不再重复赋值 —— 同一件事只留一个表达式。
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
    # ⚠️ 2026-09-19：原先用 `_secs` 找 `### 5.1 不同形态` → **从不触发**（同 15b／15d）。
    _ch_txt = _sec_any("不同形态")
    _ch = [_ch_txt] if _ch_txt else []
    if _ch:
        _txt = _ch[0]
        _rows = [r for r in _txt.split("\n") if r.strip().startswith("|")][1:]
        _ok = len(_rows) >= 1 and "不可移植" in _txt
        if not quiet:
            print(f"  {OK if _ok else NG} 渠道形态表：{len(_rows)} 行、含「不可移植元素」列 "
                  f"{'是' if '不可移植' in _txt else '否'}")
        if not _ok:
            hard_errors.append("渠道只是「换名字」—— 5.1 表必须有「不可移植元素」列，且每渠道至少 1 个。")
        # 2026-09-19（C 批 · 体系2 #9「渠道原生真重写」）：光有「不可移植元素」列还不够 ——
        #   原先只要这四字出现即过。补两条能判「够不够格」的：
        #     ① 开头列 ≥8 实字，且**不得以描述词开头**（视觉／风格／调性／氛围／高级感…）；
        #     ② 两个渠道的「形态＋开头」bigram 相似度 >0.8 ＝ 同一段内容换个渠道名。
        _h, _rows = _tbl(_txt)
        _i_head = _col(_h, "开头")
        _i_form = _col(_h, "形态")
        _i_ch = _col(_h, "渠道")
        _DESC = r"^(视觉|风格|调性|氛围|高级感|年轻化|有质感|画面|整体|感觉|调性上)"
        _thin, _desc = [], []
        _pairs = []
        for _r in _rows:
            _hd = _cell(_r, _i_head)
            if 0 < _zh(_hd) < 8:
                _thin.append((_cell(_r, _i_ch), _hd))
            elif re.match(_DESC, _hd):
                _desc.append((_cell(_r, _i_ch), _hd))
            _pairs.append((_cell(_r, _i_ch), _cell(_r, _i_form) + "　" + _hd))
        _dup = []
        for _i in range(len(_pairs)):
            for _j in range(_i + 1, len(_pairs)):
                _a, _b = _pairs[_i][1], _pairs[_j][1]
                _sa = {_a[k:k + 2] for k in range(len(_a) - 1)}
                _sb = {_b[k:k + 2] for k in range(len(_b) - 1)}
                if _sa and _sb:
                    _jac = len(_sa & _sb) / len(_sa | _sb)
                    if _jac > 0.8:
                        _dup.append((_pairs[_i][0], _pairs[_j][0], _jac))
        if not quiet:
            print(f"  {OK if not (_thin or _desc or _dup) else NG} 渠道原生：开头过短 {len(_thin)} 行、"
                  f"以描述词开头 {len(_desc)} 行、跨渠道雷同 {len(_dup)} 对")
        if _thin:
            hard_errors.append(
                "渠道原生：有渠道的「开头 3 秒／首屏」不足 8 实字（" +
                "、".join(f"{c or '?'}" for c, _ in _thin[:3]) +
                "）—— **前 3 秒是唯一一次开口的机会**，一句话说不清＝这条内容没有开头。")
        if _desc:
            hard_errors.append(
                "渠道原生：有渠道的开头以**描述词**起手（" +
                "、".join(f"{c or '?'}「{h[:14]}」" for c, h in _desc[:3]) +
                "）—— 「视觉上／风格上／有质感」是**评价**不是台词；第一句要是能直接念出来的话。")
        for _c1, _c2, _jac in _dup[:3]:
            hard_errors.append(
                f"渠道原生：{_c1 or '?'} 与 {_c2 or '?'} 的「形态＋开头」相似度 {_jac:.0%}（>80%）"
                f"—— 这就是**同一段内容换个渠道名**。判据：把这条内容放到别的渠道会失效（不可移植元素），"
                f"才算渠道原生。")
    else:
        if not quiet:
            print(f"  {NG} 渠道形态表：**未找到 5.1 同一母题·各渠道的不同形态**（骨架会给，缺了就是被删了）")
        _hard_if_full("缺「5.1 同一母题 · 各渠道的不同形态」—— **渠道原生**的判据是"
                      "「每个渠道至少一个不可移植元素」（放到别的渠道就失效的那个东西）；"
                      "缺这一节＝同一段内容换个渠道名。")

    # ── 【16】合规红线与量化可验（2026-09-17 随 R2 一起加）
    #    ⚠️ 本关的很多要求属「**完整版方案才该有**」。今天已经**连续四次**因为
    #       新硬关无条件生效而误伤速览类快案（smoke_test 的标杆稿）：
    #         ① `8a 为什么这么做须含实质`  ② `15g 议题树`  ③ `16f 敏感性`  ④ `16g KPI 频率/责任人`
    #       所以不再逐次打补丁，改成一个显式助手 —— 新加的「完整版要求」一律走它。
    #   （⚠️ 2026-09-19：`_is_full_plan` 与 `_hard_if_full` 已**上移到 `_sec_any` 之后** ——
    #     15d／15f 在它们之前执行，留在原处会让早段的调用 `NameError`。）

    # 15i 样稿实质（2026-09-19 · agency-4a 第 5 条）
    #
    # ⚠️ 原先样稿**只在 大赛档／提案档**要求；标准档的文案篇止于「物料清单：{填}」，
    #    交付物里只有概念描述、没有一句能通读的原文。4A 的判据是
    #    「**创意必须能做成样稿**；只有概念没有样稿＝没做完」。
    #    所以这里查的不是「有没有 5.2 这一节」，而是**每一张样稿是不是真文本** ——
    #    「有这一节」和「这一节里有东西」是两回事（正是本仓库的坑，见【15】开头）。
    # ⚠️ 不能靠 `_secs` 取这一段 —— 它只切 `^## `（二级标题），而 5.2 是 `### `，
    #    会落在「五 · 落地文案与物料」的正文里，取不到（实测：判据静默不触发）。
    _cp = re.findall(r"(?ms)^#{2,3}\s*5\.2\s*核心概念样稿.*?(?=^#{2,3}\s|\Z)", body)
    if _cp:
        _txt = _cp[0]
        _drafts = re.findall(r"(?m)^-\s*\*\*.+?\*\*.*?[：:]\s*(.+)$", _txt)
        _bad = []
        for _d in _drafts:
            _c = re.sub(r"[\s【】]", "", _d)
            if not _c:
                _bad.append("有一张样稿还是空的")
                continue
            # ⚠️ 这两条必须是**独立判据**，不能写成 elif 链：
            #    最初写成 elif，结果「以视觉开头」的长描述只报「太短」，真正的问题被挡住。
            if re.match(r"^(视觉|风格|调性|氛围|画面|配色)", _c):
                _bad.append("以「视觉／风格／调性／氛围」开头 —— 那是**描述**，不是样稿")
            # ⚠️ 门槛 30，不是 80 也不是 50：**海报主文案天然就 20–40 字**
            #    （实测：80 误杀 48 字的合格海报，50 仍偏严）。
            #    真正的判据是上一条「是不是描述」；长度只用来挡「一句口号冒充样稿」。
            if len(_c) < 30:
                _bad.append(f"样稿只有 {len(_c)} 实字（需 ≥30 —— 一句话口号不算样稿，口播／详情页要成段）")
        if not _drafts:
            _bad.append("没找到任何一张样稿（四类至少写一类：海报／短视频口播／详情页第七屏／私域首触）")
        if not quiet:
            print(f"  {OK if not _bad else NG} 核心概念样稿：{len(_drafts)} 张"
                  + (f"｜{'；'.join(_bad[:3])}" if _bad else "｜均为真文本 ✅"))
        for _b in _bad[:3]:
            _hard_if_full(f"核心概念样稿不达标：{_b} —— 真样稿＝**能通读的文案全文**（≥80 实字），"
                          f"不是「视觉风格：年轻有活力」这类描述。")

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

    # 19) 条件章节（2026-09-19）：能力改成「按客户特征触发」后，跟着长出来的判据
    #
    # ⚠️ 为什么必须有这一关：这些章节是「**把能力从档位解耦**」这个结构改动的产物
    #    （原先连锁三张表只挂「标准」档 → 做连锁的 B 端客户拿不到稽核表；
    #     `grep 直播|排品` 全仓零命中）。
    #    但**只加章节、不加判据 ＝ 又回到「骨架给了位、脚本查不到」**（ 坑 5）——
    #    所以章节与判据必须**同时**长出来。这是本轮修「根因 1」的示范做法。
    # 判据只在**该章节存在时**生效：不存在说明客户没这个特征，不是错。
    def _sec19(*keys):
        """按标题关键词取**整节文本**（`##` 与 `###` 都算，取到下一个标题为止）。

        ⚠️ **不能用 `_secs`** —— 它只切 `^## `，而稽核表（11.4.1）／培训表（11.4.2）
        是 `###` 子节：它们会被并进父节「十一·四 · 总部与门店的权责」的文本里，
        按标题关键词**永远命中不了** → 判据写了却**静默不生效**。
        2026-09-19 实测：19a／19e 对真骨架从不触发（只在合成用例里看起来是好的）。
        这是本仓库第二次踩同一个坑（第一次是 15i 的核心概念样稿）。
        顺带修好另一个问题：按节切干净后，权责表的行数不再把稽核表／培训表的行算进来。
        """
        for _m in re.finditer(r"(?ms)^#{2,3}\s+([^\n]*)\n(.*?)(?=^#{2,3}\s|\Z)", body):
            if any(k in _m.group(1) for k in keys):
                return _m.group(1) + "\n" + _m.group(2)
        return ""

    # 19a 稽核表：必须写「谁查」「查完报给谁」
    _a19 = _sec19("稽核表")
    if _a19:
        _miss19 = [c for c in ("谁查", "报给谁") if c not in _a19]
        if not quiet:
            print(f"  {OK if not _miss19 else NG} 稽核表：{'谁查／报给谁 两列齐' if not _miss19 else '缺 ' + '／'.join(_miss19)}")
        if _miss19:
            _hard_if_full(f"稽核表缺「{'／'.join(_miss19)}」—— **没人查＝没人做**，"
                          f"这是总部方案到门店变形的主因。")
    # 19b 直播排品：三种角色齐全 ＋ 逼单合规禁用动作
    _b19 = _sec19("排品")
    if _b19:
        _roles19 = [r for r in ("引流款", "利润款", "福利款") if r not in _b19]
        _ok19 = not _roles19 and "禁用动作" in _b19
        if not quiet:
            print(f"  {OK if _ok19 else NG} 直播排品：三种角色"
                  f"{'齐' if not _roles19 else '缺 ' + '、'.join(_roles19)}｜"
                  f"逼单禁用动作 {'有' if '禁用动作' in _b19 else '无'}")
        if _roles19:
            _hard_if_full(f"直播排品缺角色：{'、'.join(_roles19)} —— 只有引流款不赚钱、"
                          f"只有利润款不进人，三种角色各 ≥1 行。")
        elif "禁用动作" not in _b19:
            _hard_if_full("直播排品缺「逼单合规禁用动作」—— 憋单与逼单有合规边界，"
                          "必须写具体禁止行为（如不承诺全网最低、不诱导未成年人下单）。")
    # 19c 本地生活：核销成本必须算出来
    _c19 = _sec19("本地生活", "到店链路")
    if _c19:
        if not quiet:
            print(f"  {OK if '核销成本' in _c19 else NG} 本地生活到店链路："
                  f"核销成本 {'已测算' if '核销成本' in _c19 else '缺'}")
        if "核销成本" not in _c19:
            _hard_if_full("本地生活到店链路**没算核销成本**（套餐让利＋平台佣金＋履约成本）——"
                          "不算这笔，团购就是卖得越多亏得越多。")

    # 20) A 批新增判据（2026-09-19）：广告可识别性 + 绿漂举证
    #
    # ⚠️ 这两条的共同点：**知识库里有、判据表里没有**（根因 4）。
    #    「知识库知道 ≠ 交稿时会拦」—— 必须落成机械判据才算数。
    # 20a 广告可识别性（《广告法》第十四条：广告应具可识别性）
    #     凡有达人／素人／探店／测评投放，必须写明「广告标识」——
    #     不标就是伪装成素人笔记，平台与监管两头都罚。
    if re.search(r"达人|KOL|素人|探店|测评", body):
        # ⚠️ 判据要能容下**真实写法**：实测「加『广告』标签」这种把标签名加引号隔开的写法，
        #    精确匹配 `广告标签` 会漏 → 误伤一份写明标识的稿子。
        #    → 先认几种明确写法，再退一步认「既有『广告』又有『标签』」。
        _marked = bool(re.search(r"广告标识|#广告|标明广告|广告字样|标注广告", body)) \
            or ("广告" in body and "标签" in body)
        if not _marked:
            if not quiet:
                print(f"  {NG} 广告可识别性：有达人／素人投放，但全文未见「广告标识」")
            _hard_if_full("有达人／素人／探店投放却**未写广告标识** —— 《广告法》第十四条要求"
                          "广告应具可识别性，不标即「伪装成素人笔记」，平台与监管两头都罚。"
                          "写法：统一加平台「广告」标签或正文 `#广告`。")
        elif not quiet:
            print(f"  {OK} 广告可识别性：已写明广告标识")
    # 20b 绿漂举证（ESG／可持续宣称）
    #     凡「环保／低碳／可回收／碳中和／可降解／零添加」这类宣称，必须附认证或测算范围；
    #     否则就是「漂绿」，现在是被重点查的一类。
    _green = re.findall(r"环保|低碳|可回收|碳中和|零碳|可降解|零添加|绿色包装", body)
    if _green:
        if not re.search(r"认证|检测报告|证书编号|依据|测算范围|回收率", body):
            if not quiet:
                print(f"  {NG} 绿色宣称举证：出现「{'／'.join(sorted(set(_green)))}」但无认证／测算依据")
            _hard_if_full(f"绿色宣称缺举证：出现「{'／'.join(sorted(set(_green)))}」"
                          f"但全文没有认证、检测报告、证书编号或测算范围 —— 这类「漂绿」"
                          f"正在被重点查，要么附依据、要么删掉该宣称。")
        elif not quiet:
            print(f"  {OK} 绿色宣称举证：已附依据")

    # 19d 权责表 ≥8 行（A 批 · 执行视角第 14 条）
    #     GUIDE 要求「必须统一／可本地调」两栏各 ≥8 条，而骨架原先只给 4 行、且**没有判据**。
    _qz = _sec19("权责", "总部与门店")
    if _qz:
        _rows19 = [r for r in _qz.split("\n") if r.strip().startswith("|")][2:]
        _n19 = len([r for r in _rows19 if "【填】" in r or r.count("|") >= 3])
        _ok19 = _n19 >= 8
        if not quiet:
            print(f"  {OK if _ok19 else NG} 权责表：{_n19} 行（需 ≥8）")
        if not _ok19:
            _hard_if_full(f"权责表只有 {_n19} 行（需 ≥8）—— 「必须统一／可本地调」列太少，"
                          f"门店只能自行发挥；抽一家店要能**逐条打勾**，才算可复制。")
    # 19e 培训表：必须有「谁培训」与「不合格处置」
    _px = _sec19("培训与物料")
    if _px:
        _miss19e = [k for k in ("谁培训", "不合格处置") if k not in _px]
        if not quiet:
            print(f"  {OK if not _miss19e else NG} 培训表：{'含讲师与不合格处置' if not _miss19e else '缺 ' + '／'.join(_miss19e)}")
        if _miss19e:
            _hard_if_full(f"培训表缺「{'／'.join(_miss19e)}」—— 「培训过了」这句话没人能验证："
                          f"要写清谁讲、以及考核不过的人**当天怎么补、二次不过怎么处理**。")
    # 19f 利益相关者：让步边界与转向条件（A 批 · 执行视角第 10 条）
    #     基线把这条打 1.0 分；骨架已有该章与基本列，缺的是「我们最多让什么步」与
    #     「他满足什么条件就会支持」—— 没有这两列，处理动作就只是「去谈」。
    _st19 = _sec19("利益相关者")
    if _st19:
        _miss19f = [k for k in ("让步", "转向") if k not in _st19]
        if not quiet:
            print(f"  {OK if not _miss19f else NG} 利益相关者：{'含让步边界与转向条件' if not _miss19f else '缺 ' + '／'.join(_miss19f)}")
        if _miss19f:
            _hard_if_full(f"利益相关者表缺「{'／'.join(_miss19f)}」—— 只写「处理动作」不够："
                          f"要写清**我们最多让什么步、底线在哪、他满足什么条件就会支持**。")

    # 21) A 批第三批：平台实操 + 投资人参数（2026-09-19）
    #
    # ⚠️ 这一批全部是「骨架刚补了列/表」的判据 —— 判据与骨架必须同时长出来，
    #    否则又回到「骨架给了位、脚本查不到」（本仓库的坑 5，我已经踩过两次）。
    def _has(*keys):
        """bod 里这几样都在才算齐。用 body 而不是节提取 —— 这几张表的标题层级不一。"""
        return all(k in body for k in keys)

    # 21a 短视频钩子类型（平台视角第 1 条）
    if "开头 3 秒或首屏" in body:
        if "钩子类型" not in body:
            _hard_if_full("渠道表缺「钩子类型」列 —— 五种钩子（结果前置／冲突提问／反常识／"
                          "利益直给／身份喊话）必须选一类来写，写「突出产品卖点」＝没选。")
        elif not re.search(r"结果前置|冲突提问|反常识|利益直给|身份喊话", body):
            _hard_if_full("「钩子类型」列填的不是五类之一 —— 必须从枚举里选。")
        elif not quiet:
            print(f"  {OK} 短视频钩子：含钩子类型列且用了枚举值")
    # 21b 平台健康阈值参考（平台视角第 2 条）
    if re.search(r"抖音|小红书|视频号", body):
        if "经验参考值" not in body and "平台健康阈值" not in body:
            _hard_if_full("缺「平台健康阈值参考」—— 每个平台该看哪个数、低于多少要动手，"
                          "必须给经验值（写「经验值」而不是承诺，否则变成效果保证）。")
        elif not quiet:
            print(f"  {OK} 平台健康阈值：已给经验参考值")
    # 21c 达人结算方式与效果绑定（平台视角第 5 条）
    if re.search(r"达人|KOL|素人", body):
        if not re.search(r"结算方式|纯佣|坑位费|保量", body):
            _hard_if_full("达人合同要点缺「结算方式与效果绑定」—— 纯佣／坑位费／保量＋未达标扣减"
                          "不写清，付了钱没交付说不明白。")
        elif not quiet:
            print(f"  {OK} 达人结算：已写结算方式与效果绑定")
    # 21d 素材切片切点（平台视角第 12 条）
    if "母素材复用" in body or "复用去向" in body:
        if "切点" not in body:
            _hard_if_full("内容产能表缺「切片切点」—— 只说「切 3 条」不说「从哪切」，"
                          "执行的人只能从头到尾硬切。要写到具体内容点（如「00:12 翻车瞬间」）。")
        elif not quiet:
            print(f"  {OK} 素材切点：已写具体切点")
    # 21e 企微/个微选择判据（平台视角第 6 条）
    if re.search(r"加微|私域|承接载体", body):
        if "载体怎么选" not in body and "客户资产归属" not in body:
            _hard_if_full("私域承接载体缺选择判据 —— 「选一并说明理由」等于自己拍脑袋；"
                          "要给四条判据：客户资产归属／群发能力／封号风险／离职迁移成本。")
        elif not quiet:
            print(f"  {OK} 承接载体：已给四条判据")
    # 21f 敏感性必须压「最长板」—— 复购/留存（投资人视角第 11 条）
    if "敏感性分析" in body:
        if not re.search(r"复购次数|留存年限|留存率|复购率", body):
            _hard_if_full("敏感性分析只压客单/转化/投放 —— **留存与复购是最脆的**，"
                          "悲观档必须至少压其中一个，否则等于没做压力测试。")
        elif not quiet:
            print(f"  {OK} 敏感性参数：含复购/留存")

    # 22) A 批第四批：投资人 5 条 + 执行 3 条（2026-09-19）
    #
    # ⚠️ 与【21】同理：都是「骨架刚补了列/表」的判据。骨架位本轮已做齐全性总检。
    # 22a 0.1 因子表的「数据来源」列非空率（投资人视角第 5 条）
    #
    # ⚠️ 2026-09-19 修（六体系逐行核对 · 体系3 #5 挖出「**分母错**」）：
    #   原实现把 0.1 节里**所有** `|` 开头行拼起来、只 `[2:]` 砍掉头两行（表头＋分隔）——
    #   而 0.1 节里有**两张表**（五分支问题树 4 列 ＋ 四因子拆解 6 列），
    #   于是另一张表的表头/分隔行与 5 行分支行全被当成「缺数据来源的行」→
    #   恒为 6/11 = 55% < 90% → **完整版方案永远报硬错误**（判据自己成了噪声源）。
    #   → 改成**逐表切块**，只在**真的有「来源」列的那张表**上算非空率，并按**列下标**取格子。
    _f01 = re.findall(r"(?ms)^#{2,3}\s*0\.1[^\n]*\n(.*?)(?=^#{2,3}\s|\Z)", body)
    if _f01:
        _blks, _cur = [], []
        for _ln in _f01[0].split("\n"):
            if _ln.strip().startswith("|"):
                _cur.append(_ln.strip())
            elif _cur:
                _blks.append(_cur)
                _cur = []
        if _cur:
            _blks.append(_cur)
        _done22a = False
        for _blk in _blks:
            _hdr = _blk[0]
            _i_src = _col(_cells(_hdr), "数据来源", "来源")
            if _i_src < 0:
                continue
            _rows = [r for r in _blk[1:] if "---" not in r]
            if not _rows:
                continue
            _filled = [r for r in _rows if not _is_ph(_cell(_cells(r), _i_src))]
            _rate = len(_filled) / len(_rows)
            _done22a = True
            if not quiet:
                print(f"  {OK if _rate >= 0.9 else NG} 0.1 因子表：带「数据来源（口径／时点）」的行 "
                      f"{_rate:.0%}（需 ≥90%，本表 {len(_rows)} 行）")
            if _rate < 0.9:
                _hard_if_full("0.1 因子表的「数据来源（口径／时点）」列缺失或大量留空 —— "
                              "裸数字客户无法追溯，会被追问「这个 42% 哪来的」。")
        if not _done22a:
            if not quiet:
                print(f"  {NG} 0.1 因子表：**没有「数据来源」列**（骨架会给，缺了就是被删了）")
            _hard_if_full("0.1 因子表缺「数据来源（口径／时点）」列 —— 每个因子的数字都要能追到出处。")
    # 22b 目标营收 vs 四因子乘积（投资人视角第 4 条）
    _rev = re.search(r"目标营收[^\n]{0,20}?([\d,]+(?:\.\d+)?)\s*(万|亿)?", body)
    if _f01 and _rev:
        _nums = {}
        for _k in ("流量", "转化率", "客单价", "复购"):
            _m = re.search(_k + r"[^\n|]*\|[^\n|]*\|", _f01[0])
            _r = [r for r in _f01[0].split("\n") if r.strip().startswith("|") and _k in r]
            if _r:
                _cells = [c.strip() for c in _r[0].split("|")]
                _v = [c for c in _cells if re.fullmatch(r"[\d.,%％]+", c)]
                if _v:
                    _nums[_k] = float(_v[-1].replace(",", "").rstrip("%％"))
        if len(_nums) == 4:
            _prod = _nums["流量"] * (_nums["转化率"] / 100 if _nums["转化率"] > 1 else _nums["转化率"]) \
                * _nums["客单价"] * _nums["复购"]
            if not quiet:
                print(f"  {INFO} 目标营收 {_rev.group(1)} vs 四因子乘积 {_prod:,.0f}（人工核对）")
        elif not quiet:
            # ⚠️ 这里**必须出声**：解析不到就不报，等于这一关从未生效
            #    （本仓库刚刚因为「找不到目标就静默跳过」吃过一次亏）。
            print(f"  {WARN} 目标营收×四因子勾稽：**无法复算**（只解析到 {len(_nums)}/4 个因子）—— 请人工核对")
    # 22c 8.2 人力负荷表（执行视角第 6 条）
    _hr = re.findall(r"(?ms)^#{2,3}\s*8\.2[^\n]*\n(.*?)(?=^#{2,3}\s|\Z)", body)
    if _hr:
        _miss = [k for k in ("是否超载", "补法") if k not in _hr[0]]
        if not quiet:
            print(f"  {OK if not _miss else NG} 人力负荷表：{'含超载判定与补法' if not _miss else '缺 ' + '／'.join(_miss)}")
        if _miss:
            _hard_if_full(f"人力负荷表缺「{'／'.join(_miss)}」—— 只说「人手不够」不够："
                          f"要逐岗位算负荷（天／月），超载的给出**加人／外包／上工具**三选一与成本。")
    # 22d 预算伸缩（投资人视角第 12 条）
    if re.search(r"执行人力与资源伸缩|删减顺序", body):
        _miss = [k for k in ("−50%", "+100%") if k not in body]
        if not quiet:
            print(f"  {OK if not _miss else NG} 预算伸缩：{'砍半与加倍都写了' if not _miss else '缺 ' + '／'.join(_miss)}")
        if _miss:
            _hard_if_full("缺「预算 −50% 先砍哪条／+100% 先加哪条」—— 决策者一定会问这两个问题；"
                          "只给一个固定预算的方案，遇到砍预算就整份作废。")
    # 22e 首单 ROI（投资人视角第 14 条）
    if "单位经济与回本" in body:
        if "首单 ROI" not in body:
            _hard_if_full("单位经济缺「首单 ROI」—— **首单亏是常态**，但要写明亏多少、"
                          "以及最长容忍回本月数，只给生命周期口径不够。")
        elif not quiet:
            print(f"  {OK} 单位经济：含首单 ROI 双口径")
    # 22f 分渠道单位经济（投资人视角第 9 条）
    _c14 = re.findall(r"(?ms)^#{2,3}\s*14\.2[^\n]*\n(.*?)(?=^#{2,3}\s|\Z)", body)
    if _c14:
        _rows = [r for r in _c14[0].split("\n") if r.strip().startswith("|")][2:]
        _rows = [r for r in _rows if len([c for c in r.split("|") if c.strip()]) >= 3]
        if not quiet:
            print(f"  {OK if len(_rows) >= 2 else NG} 分渠道单位经济：{len(_rows)} 个渠道（需 ≥2）")
        if len(_rows) < 2:
            _hard_if_full(f"分渠道单位经济只有 {len(_rows)} 个渠道（需 ≥2）—— "
                          f"**混着算会把高质渠道的钱补贴给低质渠道**。")
    else:
        # ⚠️ else 也必须出声（2026-09-19 的教训）：这一段骨架一定会给，
        #   所以「找不到」本身就是问题。写法上刻意不留「找不到就跳过」的静默分支 ——
        #   16g 就是因为骨架没给表而静默了几个月，没人去看那句「未生效」。
        if not quiet:
            print(f"  {NG} 分渠道单位经济：**未找到 14.2 这一节**（骨架会给，缺了就是被删了）")
        _hard_if_full("缺「14.2 分渠道单位经济」—— 知识库明说「一定要分渠道算 LTV，"
                      "不同渠道用户质量差异巨大」，只给合计值会把高质渠道的钱补贴给低质渠道。")
    # 22g 加盟商试点（执行视角第 3 条）
    if "14.1 对门店" in body or "对门店／加盟商的账" in body:
        _miss = [k for k in ("试点选择标准", "首批家数") if k not in body]
        if not quiet:
            print(f"  {OK if not _miss else NG} 加盟商试点：{'含试点与首批' if not _miss else '缺 ' + '／'.join(_miss)}")
        if _miss:
            _hard_if_full("加盟商的账缺「试点选择标准／首批家数」—— 只算账不够，"
                          "要回答「**先让哪 10 家动、给它们什么额外好处、用它们的数据说服剩下的人**」。")
    # 22h 跨部门接口与冲突升级（执行视角第 7 条）
    if "行动清单" in body:
        _miss = [k for k in ("依赖方", "冲突升级") if k not in body]
        if not quiet:
            print(f"  {OK if not _miss else NG} 跨部门接口：{'含依赖方与升级路径' if not _miss else '缺 ' + '／'.join(_miss)}")
        if _miss:
            _hard_if_full(f"行动清单缺「{'／'.join(_miss)}」—— 每个要别人配合的动作，"
                          f"都要写清「从谁那里拿什么、几号给我、他不给我找谁拍板」。")

    # 23) B 批：结构性改骨架后的判据（2026-09-19）
    #
    # ⚠️ 这一批是**新章节**（不是补列），所以判据要覆盖「节在不在 + 节里有没有东西」两层。
    #    ⚠️ 按已知坑：节提取一律用「标题正则」（## 与 ### 都认），不用只切 ## 的 `_secs`。
    def _sec23(*keys):
        for _m in re.finditer(r"(?ms)^#{2,3}\s+([^\n]*)\n(.*?)(?=^#{2,3}\s|\Z)", body):
            if any(k in _m.group(1) for k in keys):
                return _m.group(1) + "\n" + _m.group(2)
        return ""

    # 23a 问题树：五分支 + 至少排除 3 支（战略咨询第 3 条）
    _pt = _sec23("0.1 MECE")
    if _pt:
        # ⚠️ 只数**五个分支行**，不能数整节的所有行 ——
        #   0.1 这一节里还有「主攻分支的量化拆解」那张**四因子表**，
        #   按整节数会把 5 支 + 4 因子 + 表头算成 11 行（实测踩过）。
        _BRANCH = ("需求端", "竞争端", "自身产品", "渠道与触达", "组织与执行")
        _rows = [r for r in _pt.split("\n")
                 if r.strip().startswith("|") and any(b in r.split("|")[1] for b in _BRANCH)]
        _excl = [r for r in _rows if re.search(r"已排除|排除", r)]
        _ok = len(_rows) >= 5 and len(_excl) >= 3
        if not quiet:
            print(f"  {OK if _ok else NG} 0.1 问题树：{len(_rows)} 个分支、其中 {len(_excl)} 支标了排除（需 ≥5 支、≥3 支排除）")
        if not _ok:
            _hard_if_full(f"0.1 问题树只有 {len(_rows)} 支、其中 {len(_excl)} 支标了排除 —— "
                          f"**不写排除依据＝这份诊断没做过穷尽**。只写「问题就是流量不够」而不排除其他四支，"
                          f"等于跳过了诊断（BCG 的判据正是「先证明没漏掉一整块」）。")
    else:
        if not quiet:
            print(f"  {NG} 0.1 问题树：**未找到这一节**（骨架会给，缺了就是被删了）")
    # 23b 市场盘子双算（战略咨询第 4 条 / 投资人第 3 条）
    _mk = _sec23("市场盘子")
    if _mk:
        _miss = [k for k in ("自上而下", "自下而上") if k not in _mk]
        if not quiet:
            print(f"  {OK if not _miss else NG} 市场盘子：{'双算齐' if not _miss else '缺 ' + '／'.join(_miss)}")
        if _miss:
            _hard_if_full(f"市场盘子缺「{'／'.join(_miss)}」—— **只给一个数＝不可验证**："
                          f"自上而下答「盘子多大」、自下而上答「你够得着多少」，两者差一个数量级说明假设有问题。")
    else:
        if not quiet:
            print(f"  {NG} 市场盘子：**未找到这一节**（骨架会给，缺了就是被删了）")
    # 23c 战略选项对比：≥3 行 + 恰好 1 行采纳（战略咨询第 1 条）
    _so = _sec23("战略选项对比")
    if _so:
        _rows = [r for r in _so.split("\n") if r.strip().startswith("|")][2:]
        _rows = [r for r in _rows if r.replace("|", "").strip()]
        _pick = [r for r in _rows if re.search(r"✅|采纳|是\s*\|?\s*$", r)]
        _ok = len(_rows) >= 3 and len(_pick) == 1
        if not quiet:
            print(f"  {OK if _ok else NG} 战略选项：{len(_rows)} 行、采纳 {len(_pick)} 行（需 ≥3 行、恰好 1 行采纳）")
        if not _ok:
            _hard_if_full(f"战略选项对比：{len(_rows)} 行、采纳 {len(_pick)} 行 —— "
                          f"需要 **≥3 条互斥路线**且**恰好一行标「采纳」**。"
                          f"只给一个方案＝无法证明「没选的那条为什么更差」。")
    else:
        if not quiet:
            print(f"  {NG} 战略选项对比：**未找到这一节**（骨架会给，缺了就是被删了）")
    # 23d 增量归因：基线 vs 净增量（战略咨询第 2 条 / 投资人第 7 条）
    _miss23 = [k for k in ("基线", "净增量") if k not in body]
    if not quiet:
        print(f"  {OK if not _miss23 else NG} 增量归因：{'含基线与净增量' if not _miss23 else '缺 ' + '／'.join(_miss23)}")
    if _miss23:
        _hard_if_full(f"缺「{'／'.join(_miss23)}」—— 预期回报只给一个绝对值**不可证伪**："
                      f"客户无法判断哪部分是方案挣的。要拆成「基线（不做也会自然涨）＋ 净增量（本方案带来）」，"
                      f"并在 7.2 写清增量口径（对照组／去年同期／前后对比）。")

    # 24) B 批第二批：现金流 / 个保法 / 里程碑 / 签批（2026-09-19）
    def _sec24(*keys):
        for _m in re.finditer(r"(?ms)^#{2,3}\s+([^\n]*)\n(.*?)(?=^#{2,3}\s|\Z)", body):
            if any(k in _m.group(1) for k in keys):
                return _m.group(1) + "\n" + _m.group(2)
        return ""

    # 24a 现金流时序与资金缺口（投资人视角第 6 条）
    _cf = _sec24("现金流与垫资")
    if _cf:
        # ⚠️ 列名只查**表头行**，不能查整节 —— 说明文字里也写着这些词，
        #   查整节会让「列被删了、注释还在」的稿子照样通过（实测踩过）。
        _hdr = next((r for r in _cf.split("\n") if r.strip().startswith("|")), "")
        _miss = [k for k in ("累计净流",) if k not in _hdr]
        _miss += [k for k in ("最大资金缺口", "缺口持续") if k not in _cf]
        if not quiet:
            print(f"  {OK if not _miss else NG} 现金流：{'含缺口与持续周数' if not _miss else '缺 ' + '／'.join(_miss)}")
        if _miss:
            _hard_if_full(f"现金流缺「{'／'.join(_miss)}」—— 只写「最大现金亏损」是**总量、没有时序**："
                          f"同样亏 20 万，「前两周垫」与「第三个月才垫」是两门生意。"
                          f"要给按周净流、`最大缺口＝min(累计净流)`、缺口持续几周。")
    else:
        if not quiet:
            print(f"  {NG} 现金流与垫资：**未找到这一节**（骨架会给，缺了就是被删了）")
    # 24b 个人信息与隐私合规（合规视角第 4 条）
    _pv = _sec24("个人信息与隐私")
    if _pv:
        # 同上：这三个都是**列名**，只查表头行
        _hdr = next((r for r in _pv.split("\n") if r.strip().startswith("|")), "")
        _miss = [k for k in ("合法性基础", "最小必要", "留存期限") if k not in _hdr]
        if not quiet:
            print(f"  {OK if not _miss else NG} 个保法台账：{'五要素齐' if not _miss else '缺 ' + '／'.join(_miss)}")
        if _miss:
            _hard_if_full(f"个人信息台账缺「{'／'.join(_miss)}」—— 收集手机号／加微／建群／人脸／定位时，"
                          f"合法性基础、最小必要、留存期限是刚性要求。"
                          f"**不写留存期限＝默认永久保存**，这是最常被查的一条。")
    else:
        if not quiet:
            print(f"  {NG} 个人信息与隐私：**未找到这一节**（骨架会给，缺了就是被删了）")
    # 24c 推进里程碑 30/60/90（执行视角第 4 条）
    _ms = _sec24("推进里程碑")
    if _ms:
        _rows = [r for r in _ms.split("\n") if r.strip().startswith("|")][2:]
        _rows = [r for r in _rows if r.replace("|", "").strip()]
        _ok = len(_rows) >= 3
        if not quiet:
            print(f"  {OK if _ok else NG} 推进里程碑：{len(_rows)} 段（需 30／60／90 共 3 段）")
        if not _ok:
            _hard_if_full(f"推进里程碑只有 {len(_rows)} 段 —— 跨月客户必须有 30／60／90 三段，"
                          f"且每段绑一个**交付物**和一个**量化信号**；「持续推进」不是里程碑。")
    else:
        if not quiet:
            print(f"  {NG} 推进里程碑：**未找到这一节**（骨架会给，缺了就是被删了）")
    # 24d 交付物签批（合规视角第 15 条）—— 基线第 10 条卡在 4.5/5 的直接原因
    _miss24d = [k for k in ("版本", "编制", "审核", "变更记录") if k not in body]
    if not quiet:
        print(f"  {OK if not _miss24d else NG} 交付物签批：{'版本·编制·审核·变更记录齐' if not _miss24d else '缺 ' + '／'.join(_miss24d)}")
    if _miss24d:
        _hard_if_full(f"交付物缺「{'／'.join(_miss24d)}」—— 机械治理做到了 4.5／5，差的正是**「人」这一层**："
                      f"谁编的、谁审的、谁签的、改了哪几版。封面要有「版本·编制·审核签批·日期」，"
                      f"正文要有「变更记录（日期／改了什么／为什么／谁批的）」。")

    # 25) B 批第三批：概念测试 / 媒介策划 / 备货库存 / 素材台账（2026-09-19）
    #     ⚠️ 列名一律查**表头行**（上一批的教训：查整节会漏掉「列被删了、注释还在」）
    def _sec25(*keys):
        for _m in re.finditer(r"(?ms)^#{2,3}\s+([^\n]*)\n(.*?)(?=^#{2,3}\s|\Z)", body):
            if any(k in _m.group(1) for k in keys):
                return _m.group(1) + "\n" + _m.group(2)
        return ""

    def _hdr_of(sec):
        return next((r for r in sec.split("\n") if r.strip().startswith("|")), "")

    # 25a 概念测试三要素（4A 工序第 6 条）
    _ct = _sec25("概念测试")
    if _ct:
        _miss = [k for k in ("测试对象", "问什么", "合格线") if k not in _hdr_of(_ct)]
        if not quiet:
            print(f"  {OK if not _miss else NG} 概念测试：{'三要素齐' if not _miss else '缺 ' + '／'.join(_miss)}")
        if _miss:
            _hard_if_full(f"概念测试缺「{'／'.join(_miss)}」—— 三要素缺一不可：**对象**（是谁、多少人）、"
                          f"**问什么**（原样复述／二选一偏好）、**合格线**（含百分比）。"
                          f"只写「做了共鸣测试」不算做过测试。")
    else:
        if not quiet:
            print(f"  {NG} 概念测试：**未找到这一节**（骨架会给，缺了就是被删了）")
    # 25b 媒介组合与预算分配（4A 工序第 8 条）
    _md = _sec25("媒介组合与预算分配")
    if _md:
        _miss = [k for k in ("预算占比", "预期触达", "频次") if k not in _hdr_of(_md)]
        if "三段排期" not in _md:
            _miss.append("三段排期")
        if not quiet:
            print(f"  {OK if not _miss else NG} 媒介策划：{'占比/触达/频次/三段排期齐' if not _miss else '缺 ' + '／'.join(_miss)}")
        if _miss:
            _hard_if_full(f"媒介策划缺「{'／'.join(_miss)}」—— 没有预算占比的渠道计划**等于没有媒介计划**；"
                          f"跨渠道触达不能简单相加（要给去重口径）；预热／引爆／承接三段各绑一个结果。")
        else:
            # 占比合计必须 = 100%
            _pcts = [float(x) for x in re.findall(r"\|\s*(\d+(?:\.\d+)?)\s*%", _md)]
            _rowsum = sum(_pcts) if _pcts else 0
            if _pcts and abs(_rowsum - 100) > 1:
                if not quiet:
                    print(f"  {WARN} 媒介预算占比逐行相加 = {_rowsum:.0f}%（≠100%）—— 请核对")
                _hard_if_full(f"媒介预算占比逐行相加 = {_rowsum:.0f}%（**须 = 100%**）—— "
                              f"占比不加总到 100，说明有渠道的预算没写全。")
    else:
        if not quiet:
            print(f"  {NG} 媒介组合与预算分配：**未找到这一节**（骨架会给，缺了就是被删了）")
    # 25c 备货与库存（执行视角第 5 条）
    _st = _sec25("备货与库存")
    if _st:
        _miss = [k for k in ("安全库存线", "临期") if k not in _hdr_of(_st) and k not in _st]
        if not quiet:
            print(f"  {OK if not _miss else NG} 备货与库存：{'含安全线与临期处理' if not _miss else '缺 ' + '／'.join(_miss)}")
        if _miss:
            _hard_if_full(f"备货与库存缺「{'／'.join(_miss)}」—— **先算能卖多少再承诺卖多少**："
                          f"承诺量 > 现有库存 + 前置期内可补量 ＝ 注定超卖；临期／尾货不给路，毛利会被吃掉。")
    else:
        if not quiet:
            print(f"  {NG} 备货与库存：**未找到这一节**（骨架会给，缺了就是被删了）")
    # 25d 素材资产台账（4A 工序第 11 条）
    _da = _sec25("素材资产台账")
    if _da:
        _miss = [k for k in ("授权起止", "到期替换动作") if k not in _hdr_of(_da)]
        if not quiet:
            print(f"  {OK if not _miss else NG} 素材台账：{'含授权起止与到期动作' if not _miss else '缺 ' + '／'.join(_miss)}")
        if _miss:
            _hard_if_full(f"素材台账缺「{'／'.join(_miss)}」—— 字体／音乐／肖像／付费图库都有期限，"
                          f"**到期还在用＝侵权**，而且通常是客户被投诉了才知道。")
    else:
        if not quiet:
            print(f"  {NG} 素材资产台账：**未找到这一节**（骨架会给，缺了就是被删了）")

    # 26) B 批：危机三件 —— 口径唯一性 / 达人塌房切割追偿 / 评论区值守（2026-09-19）
    #     三件的共同点：**它们不是「多一些风险条目」，而是危机里最先坏掉的那三样东西** ——
    #     谁在说话、切了之后素材从哪来、差评在评论区挂着没人回。
    # 26a 唯一发声人与口径审批（8.6.1）
    _vo = _sec25("舆情升级与对外发声")
    if _vo:
        _need = {"唯一对外发声口": "唯一对外发声口", "口径审批": "口径审批人"}
        _miss = [k for k, v in _need.items() if v not in _vo]
        _silence = any(k in _vo for k in ("全员静默", "不得代表品牌"))
        if not _silence:
            _miss.append("全员静默范围")
        if not quiet:
            print(f"  {OK if not _miss else NG} 发声口径："
                  f"{'唯一发声口＋审批人＋静默范围齐' if not _miss else '缺 ' + '／'.join(_miss)}")
        if _miss:
            _hard_if_full(f"发声口径缺「{'／'.join(_miss)}」—— 舆情事故的**二次伤害几乎都来自「不止一个人在说话」**："
                          f"一线、加盟商、外包客服、合作达人的个人号抢先代表品牌发声，或者回复出去了才发现口径没人审。"
                          f"这一节要写死三件事：品牌名下**只有 1 个署名发声口**、对外每一句**谁签字**、"
                          f"以及**这些人不得代表品牌发声**（含不得在评论区争论）。")
    else:
        if not quiet:
            print(f"  {NG} 舆情升级与对外发声：**未找到这一节**（骨架会给，缺了就是被删了）")
    # 26b 达人塌房：切割与追偿（8.9.1）
    _cr = _sec25("达人塌房")
    if _cr:
        _miss = [k for k in ("时限", "留什么证") if k not in _hdr_of(_cr)]
        if "定性" not in _cr:
            _miss.append("定性阶段")
        if "追偿" not in _cr:
            _miss.append("追偿")
        if not quiet:
            print(f"  {OK if not _miss else NG} 达人塌房："
                  f"{'定性与追偿＋留证列齐' if not _miss else '缺 ' + '／'.join(_miss)}")
        if _miss:
            _hard_if_full(f"达人塌房缺「{'／'.join(_miss)}」—— 合同表里那一列管的是**数据造假**，"
                          f"达人**塌房**是另一条链：**只认官方通报／平台处罚／本人承认**（未定性不切割、也不背书）、"
                          f"定性后 2 小时内全部位下架、**每一步留什么证**（不带时间戳的截图追偿时不算证据）、"
                          f"以及依合同哪一条追回已付费用。**不切割＝品牌连坐；切得快但留不下证＝钱追不回来。**")
    else:
        if not quiet:
            print(f"  {NG} 达人塌房：**未找到这一节**（骨架会给，缺了就是被删了）")
    # 26c 评论区与私信值守（8.3.5）
    _cm = _sec25("评论区与私信值守")
    if _cm:
        _miss = [k for k in ("值守人", "首响时限") if k not in _hdr_of(_cm)]
        if not any(k in _cm for k in ("必须删", "举报")):
            _miss.append("必须删／举报清单")
        if not quiet:
            print(f"  {OK if not _miss else NG} 评论区值守："
                  f"{'值守人＋首响＋删举报清单齐' if not _miss else '缺 ' + '／'.join(_miss)}")
        if _miss:
            _hard_if_full(f"评论区值守缺「{'／'.join(_miss)}」—— 投放把评论冲上来、没人接，"
                          f"等于**花钱买了一个没人管的差评墙**。要写清谁值守（几班）、多久内回、"
                          f"什么必须回、**什么必须删或举报**（人身攻击／竞品刷屏／涉政涉黄）、"
                          f"以及同类问题 ≥3 条时按舆情升级处理。")
    else:
        if not quiet:
            print(f"  {NG} 评论区与私信值守：**未找到这一节**（骨架会给，缺了就是被删了）")

    # 27) B 批：治理节奏与变更控制（2026-09-19）
    #     8.13 变更记录是**日志**（改了什么），8.14 是**规则**（怎么提、谁批、几天答复、什么算范围外）。
    #     两者缺一不可：只有日志没有规则，等于「事后都记着，事中没人拦」。
    _gov = _sec25("变更控制与范围边界")
    if _gov:
        _miss = [k for k in ("谁批", "答复时限", "工作量归属") if k not in _hdr_of(_gov)]
        # 范围边界与争议升级是挡范围蔓延的两条，缺了就等于「什么都做」
        # ⚠️ **不能只查「这一节里有没有这几个字」** —— 「范围边界」四个字就写在标题
        #    `### 8.14 变更控制与范围边界` 里，查整节**永远通过**（判据空转）。
        #    必须锚到**那两条 bullet 的形态**：行首 `- **范围边界**`。
        _gov_body = _gov.split("\n", 1)[1] if "\n" in _gov else ""
        if not re.search(r"(?m)^\s*-\s*\*\*范围边界\*\*", _gov_body):
            _miss.append("范围边界")
        if not re.search(r"(?m)^\s*-\s*\*\*争议升级\*\*", _gov_body):
            _miss.append("争议升级")
        # 评审节奏：≥2 行、且**带日期**（不带时间的「初稿评审」等于没有节奏）
        _rv = _gov.split("评审节奏", 1)[-1] if "评审节奏" in _gov else ""
        _rv_rows = [r for r in _rv.split("\n")
                    if r.strip().startswith("|") and "---" not in r and "节点" not in r]
        if len(_rv_rows) < 2:
            _miss.append("评审节奏≥2 行")
        elif not any(re.search(r"\d", r) for r in _rv_rows):
            _miss.append("评审节奏要带日期")
        if not quiet:
            print(f"  {OK if not _miss else NG} 变更治理："
                  f"{'变更流程＋评审节奏＋范围边界齐' if not _miss else '缺 ' + '／'.join(_miss)}")
        if _miss:
            _hard_if_full(f"变更治理缺「{'／'.join(_miss)}」—— **方案签完不是结束，是变更开始**："
                          f"要写清变更**谁批／几天内答复／影响哪几节／算范围内还是新增工作量**（不写工作量归属，"
                          f"客户随口加一个渠道就会变成默默做三个月）；还要写**评审节奏**（带日期）与"
                          f"**范围边界**（本方案不做什么）、**争议升级**（谁裁、几个工作日出结论）。")
    else:
        if not quiet:
            print(f"  {NG} 变更控制与范围边界：**未找到这一节**（骨架会给，缺了就是被删了）")

    # 28) C 批第一批：六条「把已给位的列接上判定」（2026-09-19）
    #     ⚠️ 这一批**不建新章节**（除 3.4 送审与两处列），只补判据 —— 因为本仓库最大的病是
    #        「骨架给了位、判据没接上」，而补判据的 ROI 远高于再加章节。
    #     ⚠️ 表格小工具已上移（见 `_zh` 之后）—— 15f 在它之前执行，留在原处会 `NameError`。

    # 28a So-What 全篇覆盖率（体系1 #10）
    #     ⚠️ 校准过才敢定阈值：真标杆稿（便利店案）**92%**、未填骨架 **65%** → 门槛 70%。
    #     ⚠️ 判据只认「段」不认「句」：骨架靠表格承载信息，逐句判会把表格全判成不合格。
    _ACT = (r"投|上线|发布|改|换|砍|加投|删|测试|排期|拍|招|培训|发券|签约|定档|复盘|巡检|对账|"
            r"埋点|关停|止损|降价|提价|赠|邀约|回访|落地|执行|写|设计|建|锁|核算|核对|"
            r"备货|补货|排品|上架|下架|分配到")
    _UNIT = (r"\d[\d,.]*\s*(元|万元|万|%|％|单|人|天|周|月|次|条|店|份|张|秒|分钟|小时|个|家|档|岁|km|公里)")
    _ps, _cur = [], []
    for _ln in body.split("\n"):
        _s = _ln.strip()
        if (not _s) or _s.startswith("#") or _s.startswith("|") or _s.startswith(">"):
            if _cur:
                _ps.append(" ".join(_cur))
                _cur = []
            continue
        _cur.append(_s)
    if _cur:
        _ps.append(" ".join(_cur))
    _judg = [x for x in _ps if _zh(x) >= 20]
    _okj = [x for x in _judg if re.search(_ACT, x) or re.search(_UNIT, x)]
    _cov = len(_okj) / max(len(_judg), 1)
    if len(_judg) >= 5:          # 段数太少（速览类）不判 —— 样本不足
        _ok28a = _cov >= 0.70
        if not quiet:
            print(f"  {OK if _ok28a else NG} So-What 覆盖率：{len(_okj)}/{len(_judg)} 段 = {_cov:.0%}"
                  f"（需 ≥70%）")
        if not _ok28a:
            _hard_if_full(
                f"So-What 覆盖率 {_cov:.0%}（低于 70%）—— 有 {len(_judg) - len(_okj)} 段"
                f"**只下了判断、没接动作或数字**「所以呢」没答。逐段补：这句判断落到谁、"
                f"做什么、看哪个数。**判据：判断句的下一句要能接得上「所以我们做 X」。**")

    # 28b 制作可行性（8.8，体系2 #2）—— 骨架七列原本**一条判据都没有**
    _pf = _sec_any("制作可行性")
    if _pf:
        _h, _rows = _tbl(_pf)
        _need = ["物料", "形态", "制作方", "前置期", "硬条件", "最晚定稿日", "难度"]
        _miss = [k for k in _need if not any(k in c for c in _h)]
        _i_lead = _col(_h, "前置期")
        _i_hard = _col(_h, "硬条件")
        _bad_lead = [_r for _r in _rows if _i_lead >= 0 and not re.search(r"\d", _cell(_r, _i_lead))]
        _bad_qual = []
        for _r in _rows:
            _hc = _cell(_r, _i_hard) if _i_hard >= 0 else ""
            # ⚠️ 「无需资质」也是合法答案（不是所有物料都要证）—— 实测这一句会误触发，
            #    所以先放过显式否定的写法，再要求「点了资质就得写资质名」。
            if re.search(r"无需|不需要|不涉及|无资质|不适用", _hc):
                continue
            if re.search(r"资质|审批|备案|许可|卫健|食药", _hc) and not re.search(
                    r"证|备案|许可|批准|号", _hc):
                _bad_qual.append(_hc[:40])
        _miss += (["前置期须含天数"] if _bad_lead else []) + (["资质类硬条件须写资质名"] if _bad_qual else [])
        if not quiet:
            print(f"  {OK if not _miss else NG} 制作可行性：{'七列＋前置期数字＋资质名齐' if not _miss else '缺 ' + '／'.join(_miss)}")
        if _miss:
            _hard_if_full(
                f"制作可行性缺「{'／'.join(_miss)}」—— **做得出来才算方案**：7 列齐（物料／形态／制作方／"
                f"**前置期**／硬条件／最晚定稿日／难度）；前置期**必须是有天数的数字**"
                f"（写「需提前准备」＝没算）；硬条件一旦涉及资质／审批，必须**写出资质名**"
                f"（食品经营许可／医疗广告审查证明／演出许可），否则档期一定崩。")
    else:
        if not quiet:
            print(f"  {NG} 制作可行性：**未找到 8.8**（骨架会给，缺了就是被删了）")
        _hard_if_full("缺「8.8 制作可行性与档期」—— 没有这一节，方案里所有物料都只是「想做的」，"
                      "不是「做得出的」：前置期、资质、审批一样都没算。")

    # 28c 洞察萃取「用的是哪一招」（体系2 #7）
    _ins = _sec_any("洞察萃取")
    if _ins:
        _tricks = [t for t in ("找矛盾", "文化张力", "品类惯例反面") if t in _ins]
        if not quiet:
            print(f"  {OK if _tricks else NG} 洞察萃取：用的是哪一招 "
                  f"{'／'.join(_tricks) if _tricks else '**未标注**'}")
        if not _tricks:
            _hard_if_full(
                "洞察萃取没写「用的是哪一招」—— 三招：**找矛盾**（用户一边说 A 一边做非 A）／"
                "**文化张力**（社会期待与真实欲望打架）／**品类惯例反面**（全行业都这么做，"
                "所以反着来）。不写招数，洞察就退化成「观察的形容词版」，没法复现也没法反驳。")
    else:
        if not quiet:
            print(f"  {NG} 洞察萃取：**未找到二·九**（骨架会给，缺了就是被删了）")

    # 28d KPI 归因方式（体系2 #12）
    _kp = _sec_any("KPI 表")
    if _kp:
        _h, _rows = _tbl(_kp)
        _i_attr = _col(_h, "归因")
        _miss = [] if _i_attr >= 0 else ["归因方式列"]
        _bad_attr = 0
        if _i_attr >= 0:
            for _r in _rows:
                _v = _cell(_r, _i_attr)
                if not re.search(r"专属|码|分渠道|对照组|前后对照|基线", _v):
                    _bad_attr += 1
            if _bad_attr:
                _miss.append(f"{_bad_attr} 行归因没四选一")
        if not quiet:
            print(f"  {OK if not _miss else NG} KPI 归因方式：{'四选一齐全' if not _miss else '缺 ' + '／'.join(_miss)}")
        if _miss:
            _hard_if_full(
                f"KPI 缺「{'／'.join(_miss)}」—— **观测方式 ≠ 归因方式**：观测是「看哪些数」，"
                f"归因是「凭什么说是这次投放带来的」。四选一：**专属码／专属链接**（线上线下分流）、"
                f"**分渠道埋点**、**对照组**（不投放的区域或人群）、**前后对照＋基线扣除**。"
                f"没有归因列，活动期的自然增长会被算成方案的功劳。")
    else:
        if not quiet:
            print(f"  {NG} KPI 归因方式：**未找到 6.1**（骨架会给，缺了就是被删了）")

    # 28e 发布前合规送审（3.4，体系2 #10）—— 3.2 只说「什么话不能说」，没说「谁在什么时候拦下来」
    _rv = _sec_any("合规送审")
    if _rv:
        _h, _rows = _tbl(_rv)
        _i_who, _i_days = _col(_h, "谁审"), _col(_h, "提前")
        _miss = [k for k, i in (("谁审（写岗位）", _i_who), ("提前几天送", _i_days)) if i < 0]
        if _i_who >= 0 and any(re.search(r"团队|大家一起|全组|共同", _cell(_r, _i_who)) for _r in _rows):
            _miss.append("「谁审」写了团队")
        if _i_days >= 0 and any(
                not re.search(r"\d|[一二三四五六七八九十两]+\s*(?:个)?(?:工作日|天|周|月|日)", _cell(_r, _i_days))
                for _r in _rows):
            _miss.append("提前天数不是数量")
        if not quiet:
            print(f"  {OK if not _miss else NG} 合规送审：{'谁审（岗位）＋提前天数齐' if not _miss else '缺 ' + '／'.join(_miss)}")
        if _miss:
            _hard_if_full(
                f"发布前合规送审缺「{'／'.join(_miss)}」—— 「谁审」**必须写岗位**（法务岗／平台运营岗／外部律所），"
                f"写「团队」「大家一起」＝**没有人负责**；「提前几天」**必须写数字**（法务要时间、平台审核要时间、"
                f"资质备案更慢）。物料是当天做当天发的，所以送审只能靠提前，不能靠加急。")
    else:
        if not quiet:
            print(f"  {NG} 发布前合规送审：**未找到 3.4**（骨架会给，缺了就是被删了）")

    # 29) C 批第二批：补三个「缺位」（2026-09-19）
    # 29a 决策人问答预判（体系1 #6）—— 原先只有大赛／G端有，标准／B端／投标过会却没有预判
    _qa = _sec_any("决策人问答预判")
    if _qa:
        _h, _rows = _tbl(_qa)
        _i_ans = _col(_h, "答法")
        _i_cat = _col(_h, "类")
        _misss = [] if len(_rows) >= 5 else [f"只有 {len(_rows)} 行（需 ≥5）"]
        _cats = {_cell(_r, _i_cat) for _r in _rows} if _i_cat >= 0 else set()
        _lack = [c for c in ("效果", "风险", "资源", "取舍") if not any(c in x for x in _cats)]
        if _lack:
            _misss.append("缺类别 " + "／".join(_lack))
        _nodigit = [_r for _r in _rows if _i_ans >= 0 and not re.search(r"\d", _cell(_r, _i_ans))]
        if _nodigit:
            _misss.append(f"{len(_nodigit)} 行答法没数字")
        if not quiet:
            print(f"  {OK if not _misss else NG} 决策人问答预判："
                  f"{'≥5 行＋四类齐＋答法带数字' if not _misss else '缺 ' + '／'.join(_misss)}")
        if _misss:
            _hard_if_full(
                f"决策人问答预判缺「{'／'.join(_misss)}」—— 会上只会问**效果／风险／资源／取舍**四类，"
                f"每类至少预演一条，答法要**≤3 句且含数字**（会上没人听长句）。"
                f"**答不上来的问题，就是方案最薄的地方。**")
    else:
        # 8.15 是**按档位条件生成**的（大赛／G端 各有自己的问答章）—— 缺失不算错，只提示。
        if not quiet:
            print(f"  {INFO} 决策人问答预判：本档未生成（大赛／G端 用各自原有的问答章）")
    # 29b 一页 creative brief（体系2 #3）—— 骨架原先从「洞察」直接跳到「定位」
    _cb = _sec_any("创意简报")
    if _cb:
        _six = ["SMP", "target", "barrier", "RTB", "mandatories", "success"]
        _misss = [k for k in _six if not re.search(k, _cb, re.I)]
        _n_smp = len(re.findall(r"(?m)^\s*-\s*\*\*SMP", _cb))
        if _n_smp > 1:
            _misss.append(f"SMP 写了 {_n_smp} 条（只能 1 条）")
        # ⚠️ 2026-09-19：初版只查「六个字段名在不在」—— 而**骨架自己的标签里就写着这六个词**
        #   （`- **SMP（单一营销命题）**：{FILL}`）→ 于是**未填的骨架也照样通过**（判据空转）。
        #   → 必须查**标签背后有没有内容**：每条 ≥6 实字，且 success 要带数字。
        # ⚠️ 2026-09-19 再踩一次：`\s*` **会吃掉换行** —— 写成 `[：:]\s*(.*)$` 时，
        #   空字段会**把下一行的内容抓过来当自己的**（`barrier` 留空 → 抓到 RTB 那一行），
        #   于是「留空」照样通过。**判断「本行有没有内容」一律用 `[ \t]*`，不要用 `\s*`。**
        _empty = []
        for _k in _six:
            _m = re.search(r"(?m)^[ \t]*-[ \t]*\*\*" + _k + r"[^\n]*?\*\*[：:][ \t]*(.*)$",
                           _cb, re.I)
            if _m and _zh(_m.group(1)) < 6:
                _empty.append(_k)
        if _empty:
            _misss.append("字段没内容：" + "／".join(_empty))
        _succ = re.search(r"(?mi)^[ \t]*-[ \t]*\*\*success[^\n]*?\*\*[：:][ \t]*(.*)$", _cb)
        if _succ and not re.search(r"\d", _succ.group(1)):
            _misss.append("success 没数字")
        if not quiet:
            print(f"  {OK if not _misss else NG} 创意简报："
                  f"{'六字段齐＋有内容＋SMP 唯一' if not _misss else '缺 ' + '／'.join(_misss)}")
        if _misss:
            _hard_if_full(
                f"创意简报缺「{'／'.join(_misss)}」—— 六字段：**SMP**（单一营销命题，"
                f"**只能一条**）／**target**（此刻的他，不是人群画像）／**barrier**（他不买的真实理由）／"
                f"**RTB**／**mandatories**（口径·禁用词·必带元素·时长）／**success**（含数字）。"
                f"SMP 写两条＝没有主张。")
    else:
        if not quiet:
            print(f"  {NG} 创意简报：**未找到二·十**（骨架会给，缺了就是被删了）")
        _hard_if_full("缺「二·十 · 创意简报（一页）」—— 没有这一页，写创意的人只能自己发挥："
                      "对谁说、他不买的理由、凭什么信、哪些必须遵守，一条都没有落纸。")
    # 29c 结案移交与后续 90 天（体系1 #8）—— 全仓原先零「移交／交接」字段
    _hd = _sec_any("结案移交")
    if _hd:
        _misss = []
        if not re.search(r"账号|后台|投放账户|权限", _hd):
            _misss.append("账号与权限怎么转")
        if "未结" not in _hd:
            _misss.append("未结事项")
        if not re.search(r"信号|触发", _hd):
            _misss.append("90 天什么信号算要改")
        if "回流" not in _hd:
            _misss.append("复盘回流")
        if not quiet:
            print(f"  {OK if not _misss else NG} 结案移交："
                  f"{'账号权限＋未结事项＋信号＋回流齐' if not _misss else '缺 ' + '／'.join(_misss)}")
        if _misss:
            _hard_if_full(
                f"结案移交缺「{'／'.join(_misss)}」—— **交付不是终点，交接完才算**："
                f"文件在哪、版本怎么认、**账号与权限转给谁**（平台后台／投放账户／私域工具／素材库）、"
                f"未结事项（还在跑的活动、未付的款、未签的合同）；后续 90 天要写**谁在看、看哪几个数、"
                f"什么信号算「要改」**，以及哪些结论要回流到知识库。不写，方案交付即失联。")
    else:
        if not quiet:
            print(f"  {NG} 结案移交：**未找到 8.16**（骨架会给，缺了就是被删了）")
        _hard_if_full("缺「8.16 结案移交与后续 90 天」—— 交付后谁接手、账号权限怎么转、"
                      "90 天看什么，全都没有；客户内部接不住，方案就停在纸上。")

    # 30) C 批第三批：受监管行业的资质与宣称边界（体系6 #2 · 2026-09-19）
    #     内容由 composer 按行业动态注入（`scripts/industry_rules.py`，12 类受监管行业）。
    #     ⚠️ 这一关**判不了「行业判得对不对」**（那要靠门禁的「客户行业」），
    #        它判的是「结构够不够格」＋「漏了要能提醒」。
    _ir = _sec_any("行业资质与宣称边界")
    # 交付稿里的强行业信号（用于「没挂这一节但看起来是受监管行业」的提醒）
    _SIG = (r"医美|医疗机构执业|医疗广告审查|保健食品|保健功能|食品经营许可|食品生产许可|"
            r"办学许可|民办学校|化妆品备案|国妆|特殊化妆品|基金销售|金融许可|理财|"
            r"预售许可|商品房预售|商业特许经营|特许经营备案|农药登记|种子生产经营|"
            r"互联网药品信息服务|药品经营许可|医疗器械经营")
    if _ir:
        _h_ir, _rows_ir = _tbl(_ir)
        _misss = []
        for _k in ("资质名称", "持有", "证书编号"):
            if not any(_k in c for c in _h_ir):
                _misss.append(f"资质表缺「{_k}」列")
        _i_ban = _col(_h_ir, "禁止", "禁用")
        _ban_sec = ""
        _mm = re.search(r"(?ms)\*\*②[^\n]*\n(.*?)(?=\*\*③|\Z)", _ir)
        if _mm:
            _ban_sec = _mm.group(1)
        _bans_rows = [r for r in _ban_sec.split("\n")
                      if r.strip().startswith("|") and "---" not in r and "禁止" not in r]
        if len(_bans_rows) < 3:
            _misss.append(f"禁语表只有 {len(_bans_rows)} 行（需 ≥3）")
        if "替换说法" not in _ir:
            _misss.append("禁语没写「替换说法」")
        if not re.search(r"识别为受监管行业[:：]\s*\S", _ir):
            _misss.append("没写识别成哪个行业")
        if "依据" not in _ir:
            _misss.append("没写依据（法规／平台规则）")
        if not quiet:
            print(f"  {OK if not _misss else NG} 行业资质与边界："
                  f"{'资质五列＋≥3 条禁语＋行业名＋依据齐' if not _misss else '缺 ' + '／'.join(_misss)}")
        if _misss:
            _hard_if_full(
                f"受监管行业的「3.5 行业资质与宣称边界」不达标：{'／'.join(_misss)} —— "
                f"3.2 那张表是**全行业通用**的禁用词，受监管行业还要**本行业专门规定**："
                f"资质清单要写「我方持有？」与「证书编号／有效期」（**没证的现在就得知道**），"
                f"禁语要写**替换说法**（只写「不能说什么」＝一线不知道能说什么），"
                f"并写明识别成哪个行业与依据（法规＋平台规则，平台侧通常更严）。")
    else:
        _hit = re.search(_SIG, body)
        if _hit:
            if not quiet:
                print(f"  {WARN} 行业资质与边界：交付稿出现受监管信号「{_hit.group(0)}」"
                      f"但**没有 3.5 这一节**")
            _hard_if_full(
                f"交付稿出现受监管信号「{_hit.group(0)}」，却没有「3.5 行业资质与宣称边界」—— "
                f"`composer` 只在识别到受监管行业时才注入这一节（12 类，见 `industry_rules.py`）；"
                f"请在《任务规则表》里补**「客户行业」**（显式声明优先于关键词计数）再重跑组装。")
        elif not quiet:
            print(f"  {INFO} 行业资质与边界：非受监管行业，本档未生成（走通用禁用词表）")

    # 31) 内容空洞检测（2026-09-19 · 六体系逐行核对挖出的最大一类病）
    #
    # 【为什么要有这一关】
    # 派 6 个独立校验员逐行核对 78 行对标维度，结果：**已落 21 / 部分 49 / 未落 8**。
    # 而 49 条「部分」里绝大多数不是没做，而是**判据空转** —— 反例测试的做法是
    # 「把某章节的**内容删空、只留表头/标签**，再跑 selfcheck」，结果照样 ✅：
    #   · 「核销成本」判 `'核销成本' in 节`，而**表头就叫「核销成本合计」**；
    #   · 「唯一对外发声口」判字符串在不在，而**骨架标签就写着这四个字**；
    #   · 「授权起止」「安全库存线」「合法性基础」同理 —— **被自证的词就印在标签里**。
    # 关键认识：**这不是 49 个独立缺陷，是一个共同漏洞** —— 判据查「结构有没有」，不查
    # 「表头背后有没有东西」。与其逐关改 49 处（改完还得逐个再验），不如**一次堵住这一大类**。
    #
    # 【判据】整篇交付稿范围内：
    #   ① 任何 markdown 表**数据行数为 0**（只有表头）→ 空表；
    #   ② 任何数据行**所有单元格都是空/占位**（`-`／`—`／【填】／占位／待补／TBD）→ 空行；
    #   ③ 任何 `- **标签**：内容` 形式的字段，**内容实字 <2**（或就是占位符）→ 空字段。
    #   ⛔ 不适用的章节**要写「不适用」**（≥2 实字即通过），不要留空 —— 留空与「忘了写」不可区分。
    #   ⚠️ 校准过的两处「不算空」（否则会误伤真稿，实测真标杆稿被误报 8 处）：
    #      · `—`／`-`／`无` **算「明确地没有」**，不算空（本仓库的填写指引就写「『无／没有』是合法答案」）；
    #        只有**真的什么都没有**与**占位符（【填】／占位／待补／TBD）**才算空。
    #      · `- **标签**：` 后面**内容换行写在下一行**（嵌套 bullet／表）是合法格式 —— 必须往下看一行。
    #   `_is_ph`／`_PH` 的定义已**上移到公共助手区**（`_zh` 之后）—— 22a 也要用它。

    _lines31 = body.split("\n")
    _in_fence = False
    _hollow_tbl, _hollow_row = [], []
    _i = 0
    _n_tbl = 0
    while _i < len(_lines31):
        _s = _lines31[_i].strip()
        if _s.startswith("```"):
            _in_fence = not _in_fence
            _i += 1
            continue
        if _in_fence or not _s.startswith("|"):
            _i += 1
            continue
        # 收集一张连续的表
        _blk = []
        while _i < len(_lines31) and _lines31[_i].strip().startswith("|"):
            _blk.append(_lines31[_i].strip())
            _i += 1
        _n_tbl += 1
        _hdr = _blk[0] if _blk else ""
        _data = [r for r in _blk[1:] if "---" not in r]
        _name = _cells(_hdr)[0][:14] if _cells(_hdr) else "（无表头）"
        if not _data:
            _hollow_tbl.append(_name)
            continue
        for _r in _data:
            _c = list(_cells(_r))
            if _c and all(_is_ph(x) for x in _c):
                _hollow_row.append(_name)
                break

    _hollow_fld = []
    for _idx, _ln in enumerate(_lines31):
        _s = _ln.strip()
        if _s.startswith("|") or _s.startswith(">") or _s.startswith("#"):
            continue
        _m = re.match(r"^[ \t]*-[ \t]*\*\*[^*]{2,40}\*\*[^\n]*?[：:][ \t]*(.*)$", _ln)
        if not _m or _zh(_m.group(1)) >= 2:
            continue
        # 往下看一行：内容换行写在下一行（嵌套 bullet／表）是合法格式
        _nxt = ""
        for _j in range(_idx + 1, len(_lines31)):
            if _lines31[_j].strip():
                _nxt = _lines31[_j].strip()
                break
        if _nxt.startswith(("-", "*", "|", ">")) or _lines31[_idx + 1].startswith((" ", "\t")):
            continue
        _lb = re.match(r"^[ \t]*-[ \t]*\*\*([^*]{2,40})\*\*", _ln)
        _hollow_fld.append((_lb.group(1) if _lb else "?")[:18])

    _n_hollow = len(_hollow_tbl) + len(_hollow_row) + len(_hollow_fld)
    if not quiet:
        print(f"  {OK if _n_hollow == 0 else NG} 内容空洞：{_n_tbl} 张表里 "
              f"**空表 {len(_hollow_tbl)}**、**空行表 {len(_hollow_row)}**、"
              f"**空字段 {len(_hollow_fld)}**")
    if _n_hollow:
        _hard_if_full(
            f"交付稿有 {_n_hollow} 处「只有壳、没有内容」："
            f"空表 {len(_hollow_tbl)}（{'、'.join(_hollow_tbl[:4])}）／"
            f"有表头但整行皆空 {len(_hollow_row)}（{'、'.join(sorted(set(_hollow_row))[:4])}）／"
            f"字段标签后无内容 {len(_hollow_fld)}（{'、'.join(_hollow_fld[:4])}）。"
            f"**表头不是内容**：判据查的是「表头背后有没有东西」，而旧版很多关只判「表头在不在」，"
            f"于是**把内容删空只留表头也能通过**。**不适用的章节要写「不适用」**（≥2 实字即过），"
            f"留空与「忘了写」不可区分。")

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
