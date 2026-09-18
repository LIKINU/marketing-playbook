#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度校验 · depth_check.py  （marketing-playbook 协议 4 配套／质量基准线）

用途：selfcheck.py 只查「存在性」（章节有没有、自检单有没有），一份 2,500 字的
      空壳稿也能全绿通过。本脚本查「**深度**」—— 用罗森案逆向出的 83 项量化指标，
      识别「结构完整但内容很空」。

用法：
    python depth_check.py plan.md
    python depth_check.py plan.md --quiet      # 只输出结论

退出码：**0 = 一律（本脚本只诊断、不阻拦出稿，用户定调 2026-09-14）**；2 = 脚本自身出错
        （注意：即使有 ❌ 硬指标，仍回 0 —— 要不要加厚由用户决定，不由脚本判死）

判断分三级（与 selfcheck.py 一致）：
    ❌ 硬指标 → 退出码 1，必须补
    ⚠️ 警告   → 需人工确认（不影响退出码）
    ✅ 通过

阈值来源：所有数字取自 `references/07-质量范式-便利店开学季案.md`（以下简称「范式档」），
         每条阈值旁标注「§X.Y #N」即该文件第 X.Y 节第 N 项实测值，未经改写。
         凡标「推导」者，表示范式档未直接给出该数字，由相邻实测项保守反推。

--------------------------------------------------------------------------
自测记录（2026-09-14）
测试样本：任一份已生成的方案 Markdown（本 skill 自带的 `references/范例/` 可直接用来试跑）
          （样张可取自 `references/范例/便利店开学季战役-交付稿.md`；其八篇目录
          齐全、12 项自检单全 ✅，是典型「结构对但很空」的空壳稿 ——
          selfcheck.py 可全绿，本脚本应报多项 FAIL。）

实跑：python3 depth_check.py references/范例/便利店开学季战役-交付稿.md
  结果：❌ 硬指标未达标 12 项　⚠️ 警告 5 项　仅 2/8 维度达标　退出码 = 1（如预期 FAIL）

  【1】竞品扫描深度   ❌ 致命弱点 0 次（≥5）｜❌ 拆解环节 0 个（≥5）
                       ｜❌ 四段式四栏全缺｜❌ 次要对手 0 个（≥3）
  【2】风险四件套     ❌ 风险条目 0 条（≥3，整维度不存在）｜❌ 无兜底／预防性动作
  【3】行动清单六要素  ❌ 行动条数 5 条（≥15）｜❌ 无「今天」条目（≥3）
                       ｜✅ 每行含负责方+时间｜✅ 含数字 100%
  【4】KPI 深度       ❌ 预警线 0/4 = 0%（范式档要求 100%）｜⚠️ 行数 4（建议 6）
                       ｜⚠️ 基准值 1/4 = 25%｜✅ 观测方式 100%
  【5】物料清单       ❌ 物料件数 4 件（≥12）｜✅ 位置／内容／成本三列齐
  【6】禁用词表       ❌ 未分类（≥5 类）｜❌ 词条 7 条（≥40）
  【7】数字密度       ✅ 每千字具体数字 30.8 个（≥5.0）
                       ※ 这一维度没抓到空壳：该稿是「预算型空壳」，金额数字很多，
                         但竞品／风险／决策线全是空的。密度只能筛「全篇无数字」的稿，
                         不能单独作为空壳判据 —— 真正管事的是【1】【2】【4】【5】【6】。
  【8】空话检测       ✅ 无动作词 0 次（≤5）
→ 结论：好稿与空壳的差别不在「有没有数字」，而在【1】【2】【4】【5】【6】五处
  是否写到罗森案的颗粒度。自测通过（脚本如预期报 FAIL，退出码 1）。
--------------------------------------------------------------------------
误报修正（2026-09-14）—— 只放宽「识别模式」，阈值一律不动
背景：合并终稿把环节／风险／分类写在正文与表格里（**环节一｜…**、#### R1｜…、
      #### 类别一｜…），旧正则只认「#### 环节N」「风险N」「A 类」，故误判为不达标。
修正：① 环节 = 标题／正文小标／四段式表格三者取最大
      ② 四段式栏名允许变体（他怎么做／强点／致命弱点／我们怎么打）
      ③ 风险条目也认「R1」编号式标题，并排除「4.5 触达硬风险」这类小节名
      ④ 禁用词分类也认「类别一／第一类／类 A」
      ⑤ 最前置动作也认稿件自称的「今天」日期（8/29（今天））

自测（修正后）：
  python3 depth_check.py 合并-方案.md        → ✅ 通过，8/8 维度达标，退出码 0
  python3 depth_check.py /tmp/mp-test/plan.md → ❌ 12 项硬指标未达标，退出码 1（仍拦空壳）
--------------------------------------------------------------------------
重复度／上限／决策推理（2026-09-14 第二次修正）—— 对比诊断的产物
背景：一份严格对比诊断（原版 371 行 vs 重跑版 1,998 行）找出根本原因 ——
      **旧版只设「要素数量下限」、不设上限，且只管「不许砍要素」、不规定「不许重复」**。
      执行 AI 精确优化了可被计数的部分（物料 12→18、KPI 8→15、风险 3→7、行动 18→27），
      在无法计数的部分（判断、取舍、精炼、洞察）退回到最省力写法：终稿膨胀 8 倍，
      却出现「止损四步在 §7.3 与 §8.3 各写一遍」「大件预警表出现 3 次」
      「『缺什么，跟我说一声』出现 55 次」，而原版的内务样板角、家长休息区
      （停留＝客单价）、定价铁律 ≤1.15 倍全部检索 0 次。

修正：① 新增**【9】重复度**（硬错误维度）：逐字重复句／跨节逐字重复／跨节近逐字重复／
        口头禅 —— **这才是「臃肿」的真正判据**（重复是缺陷，长不是）；
      ② 各维度「≤M」仅为**参照值**，超出只给**中性提示**、**不设上限、不阻拦出稿** ——
        量级由**门禁第 13 项先问用户**（摘要版／标准版／完整版），不由脚本替用户决定；
      ③ 【2】风险：兜底除了「步数」还必须有**取舍推理**（为什么先做这个而不是先降价）。

自测（同一组阈值跑两个已知样本，2026-09-14 实测）：
  python3 depth_check.py 合并-方案.md → ❌【9】硬错误：逐字重复句 3 句、跨节近逐字重复 19 处；
        ⚠️ 口头禅「缺什么跟我说一声」×55；⚠️【2】兜底缺推理
  python3 depth_check.py （本机交付稿）.md → 【9】全绿（重复句 0、跨节 0、
        近重复 0、口头禅最高 3 次），如预期（原版干净）
--------------------------------------------------------------------------
"""

import collections
import re
import sys

from _common import OK, NG, WARN, HINT, INFO   # noqa: E402  统一符号，不要在各自文件里重定义

# ==========================================================================
# 阈值表 —— 全部来自 范式档 §五「可被脚本校验的深度指标」
#
# ⚠️ 2026-09-14 修正（用户定调，最终版）：
#   **下限＝罗森案水平（要素齐全＋判断力）；上限不设限；量级由用户选择。**
#
#   背景：旧版只设下限、不管重复，于是执行 AI 精确优化了「可被计数」的部分
#   （物料 12→18、KPI 8→15、风险 3→7、行动 18→27），终稿从 371 行膨胀到 1,998 行，
#   而判断、取舍、精炼全部退化。
#
#   但**解法不是设上限**（那等于替用户决定他要多长）——
#   1. 真正该拦的是**重复**（同一件事说两遍是缺陷，长不是）→ 见【9】重复度，硬错误
#   2. 各项「≥N」是**下限**（罗森案水平），代码里的「≤M」仅为**参照值**：
#      数量超过时只给**中性提示**（「数量偏多，请确认符合用户要求的量级」），
#      **不判定「凑数」、不阻拦出稿** —— 要不要那么长，用户说了算。
#   3. 量级一律由**门禁第 13 项先问用户**（摘要版／标准版／完整版 + 有无字数限制）。
# ==========================================================================
T = {
    # 【1】竞品扫描深度
    "致命弱点": 5,        # 范式档 §5.1 #8（实测 5，「每环节 1 个」）
    "竞品环节数": 5,      # 范式档 §5.1 #9（实测 5 个环节）
    "次要对手数": 3,      # 范式档 §5.1 #11（实测 3 股次要力量）
    "总竞品数": 4,        # 范式档 §2.2.1 校验表（头号 + 3 = 实测 4）
    # 【2】风险四件套
    "风险条数": 3,        # 范式档 §5.1 #23（实测 3 条）
    "风险上限": 8,        # 推导（上限）：范式档实测 3 条；风险随项目规模成长，取 3 × 2.7 ≈ 8。
                          # 依据：罗森案重跑版 7 条，其中 R7 自认「最容易用印前自检
                          # 一次性防住」——自认不必单列却为了凑条数立了一张卡。
    "兜底系数": 3,        # 范式档 §5.1 #25（「兜底」≥ 风险数 × 3；实测 10）
    "兜底步数": 3,        # 范式档 §5.1 #28（每条兜底 ≥3 步；实测 4 步）
    "预防性动作": 2,      # 范式档 §5.1 #26（实测 2 处）
    # 【3】行动清单六要素
    "行动条数": 15,       # 范式档 §5.1 #71（实测 18 条）
    "行动上限": 35,       # 推导（上限）：范式档实测 18 条，取 18 × 1.9 ≈ 35。
                          # 依据：重跑版 27 条，其中约 12 条是 §2.4 节奏排期表的逐字重复
                          # （同一天的行动被按天抄一遍再进行动清单）。
    "行动含数字比": 0.80, # 推导：范式档 §5.1 #71–73（18 条几乎条条含数量/时刻）
    "今天条数": 3,        # 范式档 §5.1 #73（实测 5 条）
    # 【4】KPI 深度
    "KPI行数": 6,         # 范式档 §5.1 #34（实测 8 = 日常 6 + 报到日 2）
    "KPI上限": 15,        # 推导（上限）：范式档实测 8 行；取 8 × 1.9 ≈ 15。
                          # 依据：重跑版 15 行（已顶到本上限），且 KPI 表末尾自问
                          # 「为什么只有 15 行」——为达标而扩表后的自我辩解。
                          # KPI 的记录成本本身就是风险（原版只用 6 件工具、每天只看 8 个数）。
    "预警线比": 1.00,     # 范式档 §5.1 #34 / 模板 10（实测 8/8 = 100%）
    "基准值比": 0.80,     # 推导：范式档 §4.1 做法 #2（每个数字带时间点或触发条件）
    "观测方式比": 0.80,   # 推导：范式档 §5.1 #34（「怎么算」列实测 100%）
    # 【5】物料清单
    "物料件数": 12,       # 范式档 §5.1 #61（实测 12 件）
    "物料上限": 25,       # 推导（上限）：范式档实测 12 件（全部是对外物料），取 12 × 2 ≈ 25 ——
                          # 留「品类翻一倍」的空间，再多就是凑数。
                          # 依据：重跑版 18 件，其中 M17「清仓倒数」、M18「禁语自检表」
                          # 是贴给店员自己看的内部纸，被计入「对外物料」来达标。
    # 【6】禁用词表
    "禁用词类别数": 5,    # 范式档 §5.1 #14（实测 5 类 A–E）
    "禁用词类别上限": 8,  # 推导（上限）：范式档实测 5 类，放宽到 A–H（8 类）为止；
                          # 再多即为「为凑类别而切」。重跑版 6 类、每类硬凑 10 条。
    "禁用词条数": 40,     # 范式档 §5.1 #15（实测 59 条）
    "禁用词条数上限": 80, # 推导（上限）：范式档实测 59 条，取 59 × 1.35 ≈ 80。
                          # 依据：重跑版 60 条大量灌水 —— 类别一 #10「买不到别怪我」的
                          # 替代说法直接写「删除」；类别六把「环湖有 2,000 名新生」
                          # 这种事实口径校准塞进禁用词表充数。
    # 【7】数字密度
    "千字数字密度": 5.0,  # 推导：范式档 §5 未直接给；见 §4.1 做法 #1/#2 反推保守下限
    "千字密度警告": 8.0,  # 推导：同上，取建议值
    # 【8】空话检测
    "空话词": 5,          # 推导：范式档 §4.2 反面清单（「全文没有一个不可验收的指标」）
    "空话密度": 6,        # 推导：每千字「无动作词」上限（与千字数字密度对照；旧版硬编码 6）
    # 【9】重复度（2026-09-14 新增；校准样本见 check_repeats() 的注释）
    "重复句长度": 12,     # 推导：低于 12 字的片段多是表格栏名与惯用语，噪音大。
                          # 依据：原版最长的重复句刚好 12 字（「家长版学校发的您领了
                          # 剩下的我这儿配齐」×2）—— 这条门槛在原版上报 0。
    "重复句次数": 3,      # 硬错误门槛：同一句话出现 3 次，已不是「强调」而是「装订」
    "跨节重复行数": 5,    # 硬错误门槛：任意两节共用 ≥5 行逐字相同＝其中一节是复制粘贴
    "跨节近重复数": 5,    # 硬错误门槛（3–4 为警告）。推导：同一组阈值跑两个已知样本 ——
                          # 原版实测 0 处、重跑版实测 19 处，取 5 为断点（远离原版、贴近重跑版）
    "近重复片段长度": 24, # 推导：24 字以下的片段（栏名、惯用句）容易误报；
                          # 加上这道长度门槛后，原版的近逐字跨节重复 = 0
    "近重复键长": 14,     # 推导：14 字完全相同＝两句已无实质差异（中文本句平均 15–25 字）。
                          # 片段 ≥24 字时，取其「前 14 字」或「后 14 字」当键；
                          # 相同键落在不同章节 → 同一件事写了两遍
    "口头禅长度": 8,      # 推导：≥8 字的固定短语才可能是口头禅（5 字以下多为常用搭配）
    "口头禅次数": 15,     # 警告门槛。推导：原版实测最高 3 次、「重跑版 55 次」，
                          # 取 15 为安全断点（既不误报原版，也远低于重跑版）
}

# 空话／无动作词（范式档 §4.2：这类词是「没写具体动作」的信号）
# 模糊词表改从 _common 取（唯一真相）—— 2026-09-17：原先 depth_check 与
# selfcheck 各写一份，改一处忘一处就会出现两套判据。
from _common import VAGUE_WORDS   # noqa: E402

# 量词白名单 —— 用来识别「具体数字」（金额／比例／天数／数量）
UNIT = (r"(?:元|块|块|万元|万|%|％|天|周|周|日|月|年|单|单|人|篇|份|张|张|个|个|"
        r"次|小时|小时|分钟|分钟|秒|公里|米|㎡|倍|折|档|档|条|条|行|列|项|项|点|点|"
        r"杯|套|种|种|家|间|间|位|名|组|组|公里|KG|kg|L|ml|SKU)")

# --------------------------------------------------------------------------
# 识别模式表 —— 只放宽「怎么辨认」，不放宽任何阈值
# 每组都保留原本的写法，再补上稿件实际使用的变体。
# --------------------------------------------------------------------------
# 【竞品拆解环节】三种写法都认：① 标题含「环节」② 正文小标「**环节一｜…」③ 四段式表格
RE_ROUND_HEAD = re.compile(r"^#{2,6}[^\n]*(?:环节|环节)", re.M)
RE_ROUND_BODY = re.compile(r"^\s*(?:\*\*|[-*]\s*)?\s*(?:环节|环节)\s*[一二三四五六七八九十\d]+", re.M)
RE_ROUND_ROW = re.compile(r"^\s*\|\s*\*\*[^|\n]*?(?:怎么做|怎么做|做法)[^|\n]*?\*\*\s*\|", re.M)

# 【四段式四栏】栏名允许变体（他们的／他的、我们怎么打／我们的打法）
FOUR_LABELS = {
    "他们怎么做": r"他们怎么做|他们怎么做|他怎么做|他怎么做",
    "强点": r"强点|强点|强项|强项",
    "致命弱点": r"致命弱点|致命弱点|致命伤|致命伤|弱点|弱点",
    "我们的打法": r"我们的打法|我们的打法|我们怎么打|我们怎么打|我们的做法|我们的做法",
}

# 【风险条目编号】除了「风险N」也认「R1／R-1」式编号标题
RE_RISK_NO = re.compile(r"^R\s*[-–]?\s*\d{1,2}(?!\d)", re.I)

# 【禁用词分类】A 类／A类／类别一／第一类／类 A 都算一类（正规化为「一」或「A」）
RE_BANNED_CLASS = re.compile(
    r"类别\s*([一二三四五六七八九十\d]+)|第\s*([一二三四五六七八九十\d]+)\s*类|"
    r"类\s*([A-EＡ-Ｅ])|([A-EＡ-Ｅ])\s*类")

# 【最前置动作】稿件自称的「今天」日期：8/29（今天）／8/29 今天／今天（8/29）／今天是 8/29
RE_TODAY_DATE = re.compile(
    r"(?P<d1>\d{1,2}/\d{1,2})\s*[（(【]?\s*今天"
    r"|今天\s*(?:是)?\s*[（(【]?\s*(?P<d2>\d{1,2}/\d{1,2})")

# 【决策推理】（2026-09-14 新增）兜底里「取舍」的句式。为什么是这几种：
#   范式档 §五 对风险的质性要求是「兜底要说明为什么先做这个而不是直接降价」——
#   原版写的是「先改陈列，不要急着降价。降价是最贵的解法，先试免费的」，
#   这个「先 A 不 B」的句式就是判断力的痕迹，而不是格式。
#   只认句式、不认关键词，是为了避免把「降价」这种普通词语也算成推理。
RE_TRADEOFF = [
    r"为什么|为什么",                        # 为什么先做这个
    r"而不是|而非",                          # 而不是直接降价
    r"先[^。；\n]{0,25}(?:再|然后|然后|才)",  # 先 A 再 B（分步取舍）
    r"不(?:要)?(?:急著|急着)?(?:先)?降价|不(?:要)?(?:急著|急着)?(?:先)?降价",  # 先不降价
    r"可逆|不可逆",                          # 把不可逆的手段放最后
]

# --------------------------------------------------------------------------
# 【9】重复度用的正规化与切节工具
# --------------------------------------------------------------------------
RE_SENT_END = re.compile(r"[。！？；!?;]+")
RE_CJK_ONLY = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+$")
RE_APPENDIX = re.compile(r"附件|附录|附录")


def norm_cmp(s):
    """比对用正规化：只保留中英数字（去掉 Markdown 装饰、标点、空白）。

    于是「**止损四步**」＝「止损四步」、「，」＝「,」，全角半角差异都能对上。
    """
    return re.sub(r"[^\w]+", "", s, flags=re.UNICODE)


def frag_key(f, n):
    """取片段的前 n 字与后 n 字当比对键（前后都取，因为重复可能发生在句尾）。"""
    return [f[:n], f[-n:]]


def doc_sections(lines):
    """以标题切节 → [(title, start, end)]。

    只取该节「自己那一层的直接内容」（到下一行任何级别的标题为止）——
    否则父节会把子节整段包进来，父子节一比必然全中（那是假重复，不是真重复）。
    H1 视为文档标题，不切节。
    """
    heads = []
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{1,6})\s*(.+?)\s*$", ln)
        if m and len(m.group(1)) >= 2:
            heads.append((i, m.group(2)))
    out = []
    for k, (i, title) in enumerate(heads):
        j = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        out.append((title, i, j))
    return out


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------------------
# Markdown 解析小工具
# --------------------------------------------------------------------------
def find_region(lines, keywords):
    """回传 (start, end) 行号区间。先找标题；找不到再退化为正文关键词。"""
    n = len(lines)
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{1,6})\s*(.+?)\s*$", ln)
        if m and any(k in m.group(2) for k in keywords):
            level = len(m.group(1))
            j = i + 1
            while j < n:
                m2 = re.match(r"^(#{1,6})\s", lines[j])
                if m2 and len(m2.group(1)) <= level:
                    break
                j += 1
            return (i, j)
    for i, ln in enumerate(lines):
        if any(k in ln for k in keywords):
            j = i + 1
            while j < n and not re.match(r"^#{1,6}\s", lines[j]):
                j += 1
            return (i, j)
    return None


def region_text(lines, rng):
    return "\n".join(lines[rng[0]:rng[1]]) if rng else ""


def tables_in(lines, rng):
    """抽出区域内所有 Markdown 表格 → [{'header': [...], 'rows': [[...]]}]"""
    if not rng:
        return []
    start, end = rng
    blocks, i = [], start
    while i < end:
        if lines[i].strip().startswith("|") and lines[i].count("|") >= 2:
            blk = []
            while i < end and lines[i].strip().startswith("|"):
                blk.append(lines[i])
                i += 1
            blocks.append(blk)
        else:
            i += 1
    out = []
    for blk in blocks:
        rows = []
        for idx, raw in enumerate(blk):
            cells = [c.strip() for c in raw.strip().strip("|").split("|")]
            # 分隔行：整行只由 - : 空白组成，且至少有一个 "-"（容忍空单元格与对齐冒号）
            if idx == 1 and cells and all(re.fullmatch(r"[-:\s]*", c) for c in cells) \
                    and any("-" in c for c in cells):
                continue
            rows.append(cells)
        if rows:
            out.append({"header": rows[0], "rows": rows[1:]})
    return out


def col_index(header, kws):
    for i, c in enumerate(header):
        if any(k in c for k in kws):
            return i
    return -1


def cell(row, idx):
    return row[idx].strip() if 0 <= idx < len(row) else ""


def has_digit(s):
    return bool(re.search(r"\d", s))


def risk_blocks(lines):
    """找出所有风险条目区块 → [(title, text)]

    两种写法都认：
      ① 标题含「风险 N」「风险：」（原逻辑）
      ② 标题以编号开头，形如「### R1｜现金风险」「#### R2：…」（稿件实际写法）
    """
    n, out = len(lines), []
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{2,6})\s*(.+?)\s*$", ln)
        if not m:
            continue
        title = m.group(2)
        # 排除小节标题：形如「### 4.5 触达硬风险」「### 8.3 风险清单」
        # （否则「…硬风险」这种节名会被误认成一条风险，且必然缺四件套）
        if re.match(r"^\d+\.\d+[\s、.．]?", title):
            continue
        if not re.search(r"风险|风险", title) and not RE_RISK_NO.match(title):
            continue
        # 排除章节名（风控／风险与假设／风险偏好／风险总览…）
        if re.search(r"风控|风控|风险与|风险与|风险偏好|风险偏好|风险等级|风险等级|"
                     r"风险总览|风险总览|风险清单|风险清单", title):
            continue
        is_no = bool(RE_RISK_NO.match(title))
        is_kw = bool(re.search(r"(风险|风险)\s*(?:\d|[一二三四五六七八九十]|[:：]|条|条|$)", title))
        if not (is_no or is_kw):
            continue
        level, j = len(m.group(1)), i + 1
        while j < n:
            m2 = re.match(r"^(#{1,6})\s", lines[j])
            if m2 and len(m2.group(1)) <= level:
                break
            j += 1
        out.append((title, "\n".join(lines[i:j])))
    return out


def count_terms(sec_text):
    """数禁用词条数：抓引号／括号内、以顿号分隔的短词，另含表格单元格。"""
    terms = []
    for m in re.finditer(r"[「『“\"]([^」』”\"]{1,80})[」』”\"]", sec_text):
        for t in re.split(r"[、，,;；/／]+", m.group(1)):
            t = t.strip()
            if t and len(t) <= 12:
                terms.append(t)
    return list(dict.fromkeys(terms))


class Dim:
    """一个校验维度的输出容器。"""

    def __init__(self, no, name):
        self.no, self.name, self.items = no, name, []

    def ok(self, msg):
        self.items.append((OK, msg))

    def fail(self, msg):
        self.items.append((NG, msg))
        HARD.append(msg)

    def warn(self, msg):
        self.items.append((WARN, msg))
        WARNS.append(msg)

    def info(self, msg):
        self.items.append((INFO, msg))


HARD, WARNS = [], []


# ==========================================================================
# 各维度校验
# ==========================================================================
def count_rounds(lines, text):
    """数「竞品拆解环节」。

    稿件的实际写法常常不是「#### 环节N」型标题，所以三种都认，取最大：
      ① 标题含「环节」（原逻辑）
      ② 正文小标，形如「**环节一｜获客**」「**环节 1｜获客**」
      ③ 四段式表格列首，形如「| **他怎么做** | … |」（一张表只算 1 个环节，
         故只认四段中的第一段，不重复计「我们怎么打」那一列）
    """
    n_head = len(RE_ROUND_HEAD.findall(text))
    n_body = len(set(RE_ROUND_BODY.findall(text)))
    n_tbl = len(RE_ROUND_ROW.findall(text))
    return max(n_head, n_body, n_tbl)


def check_competitors(lines, text):
    d = Dim(1, "竞品扫描深度")

    weak = len(re.findall(r"致命弱点|致命弱点", text))
    d.ok(f"「致命弱点」出现 {weak} 次（阈值 ≥{T['致命弱点']}）") if weak >= T["致命弱点"] else \
        d.fail(f"「致命弱点」出现 {weak} 次（阈值 ≥{T['致命弱点']}；范式档要求每个拆解环节 1 个）")

    rounds = count_rounds(lines, text)
    if rounds == 0:
        d.fail("竞品拆解环节 0 个（阈值 ≥5）——未见「#### 环节N」式拆解，"
               "等于没做竞品扫描")
    elif rounds < T["竞品环节数"]:
        d.fail(f"竞品拆解环节 {rounds} 个（阈值 ≥{T['竞品环节数']}）")
    else:
        d.ok(f"竞品拆解环节 {rounds} 个（阈值 ≥{T['竞品环节数']}）")

    # 四段式完整度：他们怎么做／强点／致命弱点／我们的打法
    # （栏名允许变体：他怎么做／我们怎么打／我们的打法…，见 FOUR_LABELS）
    counts = {k: len(re.findall(v, text)) for k, v in FOUR_LABELS.items()}
    complete = min(counts.values())
    miss = [k for k, v in counts.items() if v == 0]
    if miss:
        d.fail(f"四段式缺栏：「{'、'.join(miss)}」（四段 = 他们怎么做／强点／致命弱点／我们的打法）")
    else:
        need = max(rounds, T["竞品环节数"])
        if complete >= need:
            d.ok(f"四段式完整 {complete} 组（= 环节数 × 4 的要求已满足）")
        else:
            d.fail(f"四段式完整仅 {complete} 组 < 环节数 {rounds}（范式档要求 = 环节数 × 4）")

    # 对手数量：威胁等级 / 「另外 N 股力量」表行数
    threat = len(re.findall(r"威胁等级|威胁等级", text))
    rng = find_region(lines, ["股力量", "另外", "竞品扫描", "竞品扫描", "竞争格局", "竞争格局"])
    tbl_rows = 0
    if rng:
        for tb in tables_in(lines, rng):
            if col_index(tb["header"], ["威胁", "威胁"]) >= 0:
                tbl_rows = max(tbl_rows, len(tb["rows"]))
    minor = max(threat, tbl_rows)
    if minor >= T["次要对手数"]:
        d.ok(f"次要对手 {minor} 个（阈值 ≥{T['次要对手数']}）")
    else:
        d.fail(f"次要对手 {minor} 个（阈值 ≥{T['次要对手数']}）——对手盘没展开")

    head = bool(re.search(r"头号对手|头号对手|全链条拆解|全链条拆解", text))
    total = minor + (1 if head else 0)
    if head:
        d.info("已标明头号对手（全链条拆解）")
    else:
        d.warn("未标明「头号对手」——范式档要求先立头号对手，再列次要力量")
    if total < T["总竞品数"]:
        d.warn(f"竞品总数 {total} 个（范式档 §2.2.1 建议 ≥{T['总竞品数']}：头号 + 3 股力量）")
    return d


def check_risks(lines, text):
    d = Dim(2, "风险四件套")
    blocks = risk_blocks(lines)
    if not blocks:
        d.fail("风险条目 0 条（阈值 ≥3）——整份方案找不到「### 风险 N」段落，"
               "风险维度完全不存在")
        if "兜底" not in text and "预防" not in text and "预防" not in text:
            d.fail("未见任何「兜底／预防性动作」字样")
        return d

    n_risk = len(blocks)
    if n_risk >= T["风险条数"]:
        d.ok(f"风险条目 {n_risk} 条（阈值 ≥{T['风险条数']}）")
    else:
        d.fail(f"风险条目 {n_risk} 条（阈值 ≥{T['风险条数']}）")

    # 上限：超出即警告「数量偏多 —— 请确认是否符合用户要求的量级（**本项不设上限**）」（2026-09-14 新增，依据见 T 表注释）
    if n_risk > T["风险上限"]:
        d.warn(f"风险 {n_risk} 条 > 上限 {T['风险上限']} 条 —— 数量偏多 —— 请确认是否符合用户要求的量级（**本项不设上限**）；"
               "自认「用一个前置动作就能防住」的不必单独立卡")

    # 一票否决 V2：每条风险必须有「预警信号」且含数字
    no_signal, no_digit, min_steps = [], [], []
    for title, body in blocks:
        m_no = RE_RISK_NO.match(title)
        short = m_no.group(0).strip() if m_no else \
            (re.split(r"[（(：:\s]", title.replace("风险", "").replace("风险", "").strip())[0] or title)
        m = re.search(r"预警信号|预警信号", body)
        if not m:
            no_signal.append(short)
            continue
        # 预警信号区间 = 「预警信号」到「兜底／预防性动作」之间
        tail = body[m.end():]
        cut = re.search(r"兜底|预防性动作|预防性动作", tail)
        seg = tail[:cut.start()] if cut else tail[:800]
        if not has_digit(seg):
            no_digit.append(short)
        # 兜底步数：数 ①②③ 或「第N步」，两者取大（避免重复计数）
        zb = re.search(r"兜底", body)
        zseg = body[zb.start():] if zb else ""
        c1 = len(re.findall(r"[①②③④⑤⑥⑦⑧⑨]", zseg))
        c2 = len(re.findall(r"第[一二三四五六七八九]步", zseg))
        min_steps.append(max(c1, c2))

    if no_signal:
        d.fail(f"风险缺「预警信号」：{'、'.join(no_signal)}（一票否决 V2，范式档 §5.2）")
    else:
        d.ok(f"每条风险均含「预警信号」（{n_risk}/{n_risk}）")
    if no_digit:
        d.fail(f"风险「预警信号」缺数字：{'、'.join(no_digit)}"
               f"（预警信号必须是可量化指标，范式档 §4.3）")
    elif not no_signal:
        d.ok("预警信号均含量化数字")

    zb_total = len(re.findall(r"兜底", text))
    need = n_risk * T["兜底系数"]
    if zb_total >= need:
        d.ok(f"「兜底」出现 {zb_total} 次（阈值 ≥{need}＝风险数×{T['兜底系数']}）")
    else:
        d.fail(f"「兜底」出现 {zb_total} 次（阈值 ≥{need}＝风险数×{T['兜底系数']}）"
               "——兜底写得太薄")

    if min_steps:
        s = min(min_steps)
        if s >= T["兜底步数"]:
            d.ok(f"每条兜底 ≥{s} 步（范式要求 ≥{T['兜底步数']} 步，且「按触发顺序不要跳步」）")
        else:
            d.fail(f"有风险的兜底只有 {s} 步（阈值 ≥{T['兜底步数']} 步，需 ①②③ 分步）")

    # 决策推理（2026-09-14 新增）：兜底不能只是「动作堆叠」，必须写明取舍。
    # 旧判据只数「兜底」出现次数与步数 —— 那是字数代理，套话稿一样过关（重跑版即如此：
    # 四件套齐全，但 R1 的「不降价，先换位置」没有因果、R6 的「话术最便宜」是通用常识、
    # R7 的最坏兜底在「零物料预算」前提等于什么都没说）。
    # 范式档 §五 的质性要求：要写清「为什么先做这个而不是直接降价」。
    no_why = []
    for title, body in blocks:
        m_no = RE_RISK_NO.match(title)
        short = m_no.group(0).strip() if m_no else \
            (re.split(r"[（(：:\s]", title.replace("风险", "").replace("风险", "").strip())[0] or title)
        zb = re.search(r"兜底", body)
        zseg = body[zb.end():] if zb else body
        if not any(re.search(p, zseg) for p in RE_TRADEOFF):
            no_why.append(short)
    if no_why:
        d.warn(f"兜底缺「决策推理（为什么先做这个，而不是一发现卖不动就降价）」："
               f"{'、'.join(no_why)}（{len(no_why)}/{n_risk} 条）—— "
               "只列动作、不写取舍的兜底＝套话（范式档：先试免费的，再花钱的）")
    else:
        d.ok(f"每条兜底都写明了取舍理由（{n_risk}/{n_risk} 条）")

    prev = len(re.findall(r"预防性动作|预防性动作", text))
    if prev >= T["预防性动作"]:
        d.ok(f"「预防性动作」出现 {prev} 次（阈值 ≥{T['预防性动作']}）")
    elif prev:
        d.warn(f"「预防性动作」只有 {prev} 次（阈值 ≥{T['预防性动作']}，建议每条高优风险 1 条）")
    else:
        d.fail("未见「预防性动作」——范式档：预防比兜底更重要，没有等于只救火不防火")
    if prev and prev < n_risk:
        d.warn(f"「预防性动作」{prev} 条 < 风险 {n_risk} 条，未覆盖全部风险")

    # 每条风险含 ≥1 具体数字
    nod = [t for t, b in blocks if not re.search(rf"\d+(?:\.\d+)?\s*{UNIT}", b)]
    if nod:
        d.warn(f"风险段内无「具体数字」：{'、'.join(nod)}（范式档 §5.1 #27 要求 100%）")
    else:
        d.ok("每条风险均含具体数字（金额／比例／天数）")
    return d


def pick_action_table(lines, all_tables):
    rng = find_region(lines, ["行动清单", "行动清单", "行动计划", "行动计划", "执行与风控", "执行与风控"])
    cands = tables_in(lines, rng) if rng else []
    best = None
    for tb in cands:
        if col_index(tb["header"], ["时间", "时间", "什么时候", "什么时候", "排期", "截止"]) >= 0:
            if best is None or len(tb["rows"]) > len(best["rows"]):
                best = tb
    if best is None and rng:
        best = max(cands, key=lambda t: len(t["rows"])) if cands else None
    return best, rng


def count_today_by_date(rows, text, i_when):
    """用稿件自称的「今天」日期，数行动清单里的最前置动作。

    例：稿件写「**8/29（今天）就开始**」，则时间栏为 8/29 的行即为「今天」条目。
    日期必须直接标注「今天」（8/29（今天）／今天 8/29），或由文首「整理日期」推定；
    找不到自称日期时回 0（维持原判断：无最前置动作）。
    """
    toks = set()
    for m in RE_TODAY_DATE.finditer(text):
        toks.add(m.group("d1") or m.group("d2"))
    m = re.search(r"整理日期[:：]\s*\d{4}-(\d{2})-(\d{2})", text)
    if m:
        toks.add(f"{int(m.group(1))}/{int(m.group(2))}")
    if not toks:
        return 0
    hit = 0
    for r in rows:
        seg = cell(r, i_when) if i_when >= 0 else " ".join(r)
        if any(re.search(re.escape(t) + r"(?![\d/])", seg) for t in toks):
            hit += 1
    return hit


def check_actions(lines, all_tables):
    d = Dim(3, "行动清单六要素")
    tb, rng = pick_action_table(lines, all_tables)
    if tb is None:
        d.fail("找不到行动清单表格——行动维度完全不存在（范式档 §5.1 #71）")
        return d

    rows = tb["rows"]
    n = len(rows)
    if n >= T["行动条数"]:
        d.ok(f"行动条数 {n} 条（阈值 ≥{T['行动条数']}）")
    else:
        d.fail(f"行动条数 {n} 条（阈值 ≥{T['行动条数']}）——清单太短，动作没拆开")

    # 上限：超出即警告「数量偏多 —— 请确认是否符合用户要求的量级（**本项不设上限**）」（2026-09-14 新增，依据见 T 表注释）
    if n > T["行动上限"]:
        d.warn(f"行动 {n} 条 > 上限 {T['行动上限']} 条 —— 数量偏多 —— 请确认是否符合用户要求的量级（**本项不设上限**）；"
               "最常见的手法是把节奏排期表按天再抄一遍（同一件事说两次，见【9】）")

    i_who = col_index(tb["header"], ["负责", "负责", "谁做", "谁做", "执行人", "执行人", "责任人", "责任人"])
    i_when = col_index(tb["header"], ["时间", "时间", "什么时候", "什么时候", "排期", "截止"])
    i_cost = col_index(tb["header"], ["花多少", "预算", "预算", "费用", "费用", "成本", "金额", "金额"])
    i_chk = col_index(tb["header"], ["验收", "验收", "判定", "成果", "指标", "指标"])

    if i_who < 0:
        d.fail("行动清单缺「负责方／谁做」列（一票否决 V1，范式档 §5.2）")
    if i_when < 0:
        d.fail("行动清单缺「时间」列（一票否决 V1，范式档 §5.2）")
    if i_who >= 0 and i_when >= 0:
        bad = [str(k + 1) for k, r in enumerate(rows) if not cell(r, i_who) or not cell(r, i_when)]
        if bad:
            d.fail(f"第 {','.join(bad[:8])} 行缺「负责方」或「时间」（一票否决 V1，要求 100%）")
        else:
            d.ok(f"每行均含「负责方 + 时间」（{n}/{n} = 100%）")
    if i_cost < 0:
        d.warn("行动清单缺「花多少／预算」列（建议补上）")
    if i_chk < 0:
        d.warn("行动清单缺「怎么验收」列（建议补上）")
    # ── 2026-09-19（A 批 · 执行视角第 2 条）：骨架给了 10 列，这里以前只硬校验 2 列。
    #    「谁做、什么时候」之外，「出了事谁替、谁验收、超权限找谁批」同样是一票否决级的
    #    —— 缺了这三列，方案到一线就变成「没人接、没人验、批不了」。
    for _idx, _nm, _why in ((col_index(tb["header"], ["替补"]), "替补人",
                             "负责方请假或离职时没人接"),
                            (col_index(tb["header"], ["验收人", "谁验收"]), "验收人",
                             "谁验收不写＝没人验收"),
                            (col_index(tb["header"], ["决策权限", "谁能批"]), "决策权限",
                             "超出预算找谁批，一线只能停摆")):
        if _idx < 0:
            d.warn(f"行动清单缺「{_nm}」列 —— {_why}（骨架已给位，建议补上）")
        else:
            _empty = [str(k + 1) for k, r in enumerate(rows) if not cell(r, _idx)]
            if len(_empty) / max(len(rows), 1) > 0.1:
                d.fail(f"第 {','.join(_empty[:8])} 行「{_nm}」为空（要求 ≥90% 非空）—— {_why}")
            else:
                d.ok(f"行动清单「{_nm}」非空率 {1 - len(_empty) / len(rows):.0%}")

    with_num = [r for r in rows if any(has_digit(c) for c in r)]
    ratio = len(with_num) / n if n else 0
    if ratio >= T["行动含数字比"]:
        d.ok(f"含具体数字的行动行 {len(with_num)}/{n} = {ratio:.0%}（阈值 ≥{T['行动含数字比']:.0%}）")
    elif ratio >= 0.4:
        d.warn(f"含具体数字的行动行 {len(with_num)}/{n} = {ratio:.0%}"
               f"（建议 ≥{T['行动含数字比']:.0%}，范式档 §4.1 #3）")
    else:
        d.fail(f"含具体数字的行动行仅 {ratio:.0%}（阈值 ≥40%）——动作没有量")

    # 「最前置动作」的识别：稿件常写绝对日期（8/29）而非「今天」二字，
    # 故以稿件自称的「今天」日期换算。阈值不变，只是别把已达标的判成缺。
    rows_text = "\n".join(" ".join(r) for r in rows)
    today = len(re.findall(r"今天|立刻|马上|马上|立即", rows_text))
    if not today:
        today = count_today_by_date(rows, "\n".join(lines), i_when)
    if today >= T["今天条数"]:
        d.ok(f"「今天／立刻」条目 {today} 条（阈值 ≥{T['今天条数']}）")
    elif today:
        d.warn(f"「今天／立刻」条目只有 {today} 条（阈值 ≥{T['今天条数']}，范式档 §5.1 #73）")
    else:
        d.fail("行动清单无「今天／立刻」条目——没有最前置动作（范式档 §5.1 #73）")
    return d


def check_kpi(lines, all_tables):
    d = Dim(4, "KPI 深度")
    rng = find_region(lines, ["KPI", "指标", "指标", "追踪", "追踪", "监测", "监测"])
    tbls = tables_in(lines, rng) if rng else []
    tb = None
    for t in tbls:
        if col_index(t["header"], ["指标", "指标", "KPI", "目标", "目标"]) >= 0:
            if tb is None or len(t["rows"]) > len(tb["rows"]):
                tb = t
    if tb is None and tbls:
        tb = max(tbls, key=lambda t: len(t["rows"]))
    if tb is None:
        d.fail("找不到 KPI 表格——KPI 维度完全不存在（范式档 §5.1 #34）")
        return d

    rows, n = tb["rows"], len(tb["rows"])
    if n >= T["KPI行数"]:
        d.ok(f"KPI 行数 {n}（阈值 ≥{T['KPI行数']}，范式档实测 8）")
    else:
        d.warn(f"KPI 行数 {n}（建议 ≥{T['KPI行数']}，范式档实测 8 = 日常 6 + 报到日 2）")

    # 上限：超出即警告「数量偏多 —— 请确认是否符合用户要求的量级（**本项不设上限**）」（2026-09-14 新增，依据见 T 表注释）
    if n > T["KPI上限"]:
        d.warn(f"KPI {n} 行 > 上限 {T['KPI上限']} 行 —— 数量偏多 —— 请确认是否符合用户要求的量级（**本项不设上限**）；"
               "KPI 的记录成本本身就是风险，先问「这一行没人看会不会少一个决策」")

    # 一票关注点：预警线／决策线（范式档：没有第三列的 KPI 表等于没写）
    i_alarm = col_index(tb["header"], ["预警", "预警", "兜底", "决策线", "决策线", "立刻", "即时", "告警"])
    if i_alarm >= 0:
        cov = sum(1 for r in rows if cell(r, i_alarm))
    else:
        # 注意：不可把「→」算进来 —— 目标栏的「42 → 80」是基准值，不是预警线
        cov = sum(1 for r in rows
                  if re.search(r"预警|预警|决策线|决策线|立刻|告警|连续\s*\d|连续\s*\d", " ".join(r)))
    ratio = cov / n if n else 0
    if ratio >= T["预警线比"]:
        d.ok(f"每行含「预警线 → 立刻做什么」（{cov}/{n} = {ratio:.0%}）")
    elif ratio == 0:
        d.fail("KPI 表无「预警线／决策线」栏（0/%d）——范式档 §5.1 #34："
               "没有第三列（预警线 → 立刻做什么）的 KPI 表等于没写" % n)
    else:
        d.fail(f"「预警线」覆盖 {cov}/{n} = {ratio:.0%}（范式档要求 100%，"
               "缺的那几行只是数字、不是决策）")

    i_base = col_index(tb["header"], ["目标", "目标", "基准", "基准", "现况", "现况", "值"])
    if i_base >= 0:
        base_cov = sum(1 for r in rows if re.search(r"→|->|从|从", cell(r, i_base)))
    else:
        base_cov = sum(1 for r in rows if re.search(r"→|->|从\s*[\d.]+\s*到|从\s*[\d.]+\s*到", " ".join(r)))
    br = base_cov / n if n else 0
    if br >= T["基准值比"]:
        d.ok(f"含基准值对比（X → Y）的 KPI {base_cov}/{n} = {br:.0%}（阈值 ≥{T['基准值比']:.0%}）")
    elif br == 0:
        d.fail("KPI 无基准值对比（无「X → Y」或「从 X 到 Y」）——只有目标没有起点，无法判断进步")
    else:
        d.warn(f"基准值对比仅 {base_cov}/{n} = {br:.0%}（建议 ≥{T['基准值比']:.0%}）")

    i_obs = col_index(tb["header"], ["怎么", "怎么", "来源", "来源", "观测", "观测", "记", "记",
                                     "统计", "统计", "导出", "导出", "数据源", "数据源"])
    if i_obs >= 0:
        obs_cov = sum(1 for r in rows if cell(r, i_obs))
    else:
        obs_cov = len(rows) if re.search(r"后台|后台|导出|导出|系统|系统|盘点|盘点|收银|收银|日志|日志|每日|周报|周报", region_text(lines, rng)) else 0
    orr = obs_cov / n if n else 0
    if orr >= T["观测方式比"]:
        d.ok(f"含观测方式（怎么记／后台／每日导出）{obs_cov}/{n} = {orr:.0%}（阈值 ≥{T['观测方式比']:.0%}）")
    elif orr == 0:
        d.fail("KPI 无观测方式（怎么记／后台／每日导出）——指标不可测")
    else:
        d.warn(f"观测方式覆盖 {obs_cov}/{n} = {orr:.0%}（建议 ≥{T['观测方式比']:.0%}）")
    return d


def check_materials(lines, all_tables):
    d = Dim(5, "物料清单")
    rng = find_region(lines, ["物料", "文案", "物料清单", "物料清单"])
    tbls = tables_in(lines, rng) if rng else []
    tb = None
    for t in tbls:
        if col_index(t["header"], ["物料", "品项", "品项", "项目", "项目", "名称", "名称"]) >= 0:
            if tb is None or len(t["rows"]) > len(tb["rows"]):
                tb = t
    if tb is None and tbls:
        tb = max(tbls, key=lambda t: len(t["rows"]))
    if tb is None:
        d.fail("找不到物料清单表格——物料维度完全不存在（范式档 §5.1 #61）")
        return d

    rows, n = tb["rows"], len(tb["rows"])
    if n >= T["物料件数"]:
        d.ok(f"物料件数 {n} 件（阈值 ≥{T['物料件数']}）")
    else:
        d.fail(f"物料件数 {n} 件（阈值 ≥{T['物料件数']}）——物料没列全")

    # 上限：超出即警告「数量偏多 —— 请确认是否符合用户要求的量级（**本项不设上限**）」（2026-09-14 新增，依据见 T 表注释）
    if n > T["物料上限"]:
        d.warn(f"物料 {n} 件 > 上限 {T['物料上限']} 件 —— 数量偏多 —— 请确认是否符合用户要求的量级（**本项不设上限**）；"
               "只数「顾客／学生会看到的件数」，店员自看的内部纸（自检表、清仓倒数牌）不算物料")

    for label, kws, level in [
        ("放哪／位置", ["位置", "放哪", "贴", "摆", "摆", "地点", "地点", "动线", "动线", "渠道"], "hard"),
        ("写什么／内容", ["内容", "内容", "文案", "规格", "规格", "话术", "话术", "做什么", "做什么"], "hard"),
        ("成本／元", ["成本", "元", "预算", "预算", "价格", "价格", "费用", "费用", "单价", "单价"], "warn"),
    ]:
        idx = col_index(tb["header"], kws)
        if idx < 0:
            (d.fail if level == "hard" else d.warn)(f"物料表缺「{label}」列（每件物料的三要素之一）")
        else:
            cov = sum(1 for r in rows if cell(r, idx))
            if cov / n >= 0.8:
                d.ok(f"含「{label}」的物料 {cov}/{n} = {cov/n:.0%}")
            else:
                d.warn(f"含「{label}」的物料仅 {cov}/{n} = {cov/n:.0%}（建议 ≥80%）")
    return d


def check_banned(lines, text):
    d = Dim(6, "禁用词表")
    rng = find_region(lines, ["禁用词", "禁用词", "红线词", "红线词", "不能说", "不能说"])
    if not rng:
        d.fail("未见禁用词表（禁用词维度完全不存在）——范式档 §5.1 #14/#15")
        return d
    sec = region_text(lines, rng)

    # 分类的识别：A 类／A类（原逻辑）＋ 类别一／第一类／类 A（稿件实际写法）
    classes = {next(g for g in m.groups() if g) for m in RE_BANNED_CLASS.finditer(sec)}
    nc = len(classes)
    if nc >= T["禁用词类别数"]:
        d.ok(f"禁用词分类 {nc} 类（阈值 ≥{T['禁用词类别数']}，范式档 A–E 各类标后果）")
    elif nc:
        d.fail(f"禁用词只分 {nc} 类（阈值 ≥{T['禁用词类别数']}）——未按触发后果分类")
    else:
        d.fail("禁用词未分类（阈值 ≥5 类 A–E）——只列词不标后果")

    terms = count_terms(sec)
    nt = len(terms)
    if nt >= T["禁用词条数"]:
        d.ok(f"禁用词条数 {nt} 条（阈值 ≥{T['禁用词条数']}，范式档实测 59）")
    else:
        d.fail(f"禁用词条数 {nt} 条（阈值 ≥{T['禁用词条数']}，范式档实测 59）"
               + (f"——仅：{'、'.join(terms[:6])}" if terms else ""))

    if "后果" in sec or "触发" in sec or "触发" in sec:
        d.ok("各类禁用词标注了触发后果（范式档要求：不只列词）")
    else:
        d.warn("禁用词未标注「触发什么后果」（范式档：每类必须标后果）")

    # 上限：超出即警告「数量偏多 —— 请确认是否符合用户要求的量级（**本项不设上限**）」（2026-09-14 新增，依据见 T 表注释）
    if nc > T["禁用词类别上限"]:
        d.warn(f"禁用词分类 {nc} 类 > 上限 {T['禁用词类别上限']} 类 —— 类别偏多 —— 请确认是否符合用户要求的量级")
    if nt > T["禁用词条数上限"]:
        d.warn(f"禁用词条数 {nt} 条 > 上限 {T['禁用词条数上限']} 条 —— 疑似为凑条数而扩充；"
               "以「删除／完全禁用」当替代说法、或把事实口径校准（如「环湖有 2,000 名新生」）"
               "塞进这张表，都不是禁用词")
    return d


def check_density(text):
    d = Dim(7, "数字密度")
    body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)
    chars = len(re.sub(r"\s", "", body))
    n_unit = len(re.findall(rf"\d+(?:\.\d+)?\s*{UNIT}", body))
    n_all = len(re.findall(r"\d+", body))
    lines_n = len([l for l in text.splitlines() if l.strip()])
    d.info(f"篇幅：{lines_n} 行 / {chars:,} 非空白字符")

    if chars == 0:
        d.fail("文档为空")
        return d
    dens = n_unit / (chars / 1000)
    d.info(f"具体数字（带单位）{n_unit} 个，全部数字 {n_all} 个")
    if dens >= T["千字密度警告"]:
        d.ok(f"每千字具体数字 {dens:.1f} 个（阈值 ≥{T['千字数字密度']:.1f}，建议 ≥{T['千字密度警告']:.1f}）")
    elif dens >= T["千字数字密度"]:
        d.warn(f"每千字具体数字 {dens:.1f} 个（阈值 ≥{T['千字数字密度']:.1f}，"
               f"建议 ≥{T['千字密度警告']:.1f}）——内容偏空")
    else:
        d.fail(f"每千字具体数字仅 {dens:.1f} 个（阈值 ≥{T['千字数字密度']:.1f}）"
               "——全文缺乏可核对的事实与金额")

    if n_unit == 0:
        d.fail("全文找不到任何「具体数字 + 单位」（元／%／天／单…）——这是空话稿的典型特征")
    return d


def check_vague(text):
    d = Dim(8, "空话检测")
    body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)
    chars = len(re.sub(r"\s", "", body)) or 1
    hits = []
    for w in VAGUE_WORDS:
        c = len(re.findall(re.escape(w), body))
        if c:
            hits.append((w, c))
    total = sum(c for _, c in hits)
    top = "、".join(f"{w}×{c}" for w, c in sorted(hits, key=lambda x: -x[1])[:8])

    if total <= T["空话词"]:
        d.ok(f"「加强/提升/优化/赋能/打造」等无动作词出现 {total} 次（建议 ≤{T['空话词']}）")
    else:
        d.warn(f"「加强/提升/优化/赋能/打造」等无动作词出现 {total} 次"
               f"（建议 ≤{T['空话词']}）——这些词往往意味著「没写具体动作」"
               + (f"｜高频：{top}" if top else ""))
    dens = total / (chars / 1000)
    if dens > T["空话密度"]:
        d.warn(f"无动作词密度 {dens:.1f} 个/千字（建议 ≤{T['空话密度']}）——空话比例偏高")
    return d


def check_repeats(lines, text):
    """【9】重复度 —— 抓「同一件事说两遍」与「为凑数而膨胀」。

    这一维度是 2026-09-14 对比诊断（原版 371 行 vs 重跑版 1,998 行）的产物：
    旧版 8 个维度全部是**计数下限**，于是执行 AI 精确优化了「可被脚本数出来」的部分
    （物料 12→18、KPI 8→15、风险 3→7、行动 18→27），而终稿从 371 行膨胀到 1,998 行，
    同时出现「止损四步在 §7.3 与 §8.3 各写一遍」「大件预警表出现 3 次」
    「『缺什么，跟我说一声』出现 55 次」。**数得出来的都超额，数不出来的（判断、取舍、
    精炼）全部退化。** 所以「有没有说第二遍」必须自己也变成可校验的。

    四个判据（前三个是硬错误，第四个是警告）：
      ① 逐字重复句：同一句（≥12 字）在全文出现 ≥3 次
      ② 跨节重复行：任意两节共用 ≥5 行逐字相同（§7 与 §8 各写一份止损四步即属此类）
      ③ 跨节近重复：≥24 字的句片段，前 14 字或后 14 字完全相同却分属 ≥2 节
         （同一判断改写后分放两章 —— 这比重复字句更常见、也更能骗过肉眼）
      ④ 口头禅：某固定短语（≥8 字）出现 ≥15 次（把同一句话反复垫字数的信号）

    校准（同一组阈值跑两个已知样本，2026-09-14 实测）：
      原版   （本机交付稿）.md（371 行）→ ①0 句 ②0 对 ③0 处
                                                            ④最高 3 次 → 本维度全绿
      重跑版 合并-方案.md（1,998 行）→ ①3 句 ②0 对 ③19 处 ④55 次 → ❌
    """
    d = Dim(9, "重复度")

    # ① 逐字重复句
    cnt = collections.Counter()
    for ln in lines:
        for part in RE_SENT_END.split(ln):
            n = norm_cmp(part)
            if len(n) >= T["重复句长度"]:
                cnt[n] += 1
    dup = sorted(((k, v) for k, v in cnt.items() if v >= T["重复句次数"]),
                 key=lambda x: (-x[1], x[0]))
    if dup:
        d.fail(f"逐字重复句 {len(dup)} 句（≥{T['重复句长度']} 字、出现 ≥{T['重复句次数']} 次）："
               + "；".join(f"「{k[:18]}」×{v}" for k, v in dup[:6])
               + ("…" if len(dup) > 6 else "")
               + " —— 同一件事只准说一遍：重复处删到只剩一处，其他用「见 §X」")
    else:
        d.ok(f"无逐字重复句（没有 ≥{T['重复句长度']} 字的句子出现 ≥{T['重复句次数']} 次）")

    secs = doc_sections(lines)
    if len(secs) < 2:
        d.info("章节标题少于 2 个，跳过跨节重复比对")
    else:
        # ② 跨节重复行（逐字）
        line_sets = []
        for title, a, b in secs:
            s = set()
            for ln in lines[a + 1:b]:
                n = norm_cmp(ln)
                if len(n) >= 10:
                    s.add(n)
            line_sets.append((title, s))
        pairs = []
        for i in range(len(line_sets)):
            for j in range(i + 1, len(line_sets)):
                common = line_sets[i][1] & line_sets[j][1]
                if len(common) >= T["跨节重复行数"]:
                    pairs.append((len(common), line_sets[i][0], line_sets[j][0]))
        pairs.sort(reverse=True)
        if pairs:
            d.fail(f"跨节逐字重复 {len(pairs)} 对（同一行在两节各出现一次，门槛 "
                   f"≥{T['跨节重复行数']} 行）："
                   + "；".join(f"「{a[:14]}」↔「{b[:14]}」共 {n} 行" for n, a, b in pairs[:4])
                   + " —— 其中一节是复制粘贴，留一处即可")
        else:
            d.ok(f"无跨节逐字重复（没有两节共用 ≥{T['跨节重复行数']} 行）")

        # ③ 跨节近重复（前 14 字或后 14 字相同）
        #    附件／附录是客户原始资料的合法容器（SKILL §三 附件 C），不列入比对；
        #    正文各节之间一律列入。
        owner, sample, seen = collections.defaultdict(set), {}, set()
        for title, a, b in secs:
            if RE_APPENDIX.search(title):
                continue
            for ln in lines[a + 1:b]:
                for part in RE_SENT_END.split(ln):
                    f = norm_cmp(part)
                    if len(f) < T["近重复片段长度"] or f in seen:
                        continue
                    seen.add(f)
                    for k in frag_key(f, T["近重复键长"]):
                        owner[k].add(title)
                        sample.setdefault(k, f)
        near = sorted(((k, v) for k, v in owner.items() if len(v) >= 2),
                      key=lambda x: -len(x[1]))
        if len(near) >= T["跨节近重复数"]:
            d.fail(f"跨节近逐字重复 {len(near)} 处（≥{T['近重复片段长度']} 字的句子，"
                   f"前 {T['近重复键长']} 字或后 {T['近重复键长']} 字完全相同却分属两节；"
                   f"门槛 ≥{T['跨节近重复数']}）："
                   + "；".join(f"「{sample[k][:18]}」跨 {len(v)} 节" for k, v in near[:4])
                   + " —— 同一个判断只写一次，其余章节用交叉引用")
        elif near:
            d.warn(f"跨节近逐字重复 {len(near)} 处（门槛 ≥{T['跨节近重复数']} 才报硬错误）："
                   + "；".join(f"「{sample[k][:18]}」跨 {len(v)} 节" for k, v in near[:4]))
        else:
            d.ok("无跨节近逐字重复（没有 ≥24 字的句子在两节各写一遍）")

    # ④ 口头禅
    stream = norm_cmp(text)
    g = collections.Counter()
    n_g = T["口头禅长度"]
    for i in range(len(stream) - n_g + 1):
        gram = stream[i:i + n_g]
        if RE_CJK_ONLY.match(gram):
            g[gram] += 1
    hot = sorted(((k, v) for k, v in g.items() if v >= T["口头禅次数"]),
                 key=lambda x: (-x[1], x[0]))
    if hot:
        d.warn(f"疑似口头禅 {len(hot)} 个（≥{n_g} 字的固定短语出现 ≥{T['口头禅次数']} 次）："
               + "、".join(f"「{k}」×{v}" for k, v in hot[:5])
               + " —— 这是「把同一句话反复垫字数」的信号：一次说清，其余用交叉引用")
    else:
        top = g.most_common(1)
        d.ok(f"无口头禅（最常出现的 {n_g} 字短语是「{top[0][0]}」×{top[0][1]} 次，"
             f"未达 {T['口头禅次数']} 次）")
    return d


# ==========================================================================
def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("用法: python depth_check.py <plan.md> [--quiet] [--strict]")
        print("  默认只诊断、不阻拦出稿（退出码一律 0，除非脚本自身出错=2）")
        print("  --strict：**仅对三项量化硬指标**（KPI 预警线 0%／风险条目 0／数字密度过低）")
        print("            返回退出码 1 —— 其余维度维持「只提示」。出稿前那一次建议挂上。")
        sys.exit(0)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    quiet = "--quiet" in sys.argv
    strict = "--strict" in sys.argv
    if not args:
        print("用法: python depth_check.py <plan.md> [--quiet]")
        sys.exit(1)
    path = args[0]

    try:
        text = read_text(path)
    except Exception as e:
        print(f"{NG} 无法读取方案档：{e}")
        sys.exit(1)

    lines = text.splitlines()
    all_tables = tables_in(lines, (0, len(lines)))
    HARD.clear(); WARNS.clear()   # 防重入污染（同一进程跑多次时）

    dims = [
        check_competitors(lines, text),
        check_risks(lines, text),
        check_actions(lines, all_tables),
        check_kpi(lines, all_tables),
        check_materials(lines, all_tables),
        check_banned(lines, text),
        check_density(text),
        check_vague(text),
        check_repeats(lines, text),
    ]

    if not quiet:
        print("=" * 64)
        print(f"深度校验 · {path}")
        print("=" * 64)

    passed = 0
    for d in dims:
        has_fail = any(s == NG for s, _ in d.items)
        if not quiet:
            print(f"\n【{d.no}】{d.name}")
            for s, m in d.items:
                print(f"  {s} {m}")
        if not has_fail:
            passed += 1

    print("\n" + "=" * 64)
    if HARD:
        # ── 用户定调（2026-09-14）：**只提示、不阻拦** ──
        #    理由：① 严格数量门槛会逼出「资料汇编」，而精炼的罗森案原版自己都过不了；
        #          ② 方案长短与要素多少应由**用户选择**（门禁第 13 项先问），不由脚本判定。
        #    所以此处一律打印诊断报告并 **exit 0**，改不改由用户决定。
        print(f"{INFO} 诊断报告：{len(HARD)} 项「要素偏薄／可再加厚」——**仅供参考，不阻拦出稿**")
        for e in HARD:
            print(f"   · {e}")
        if WARNS:
            print(f"\n{WARN} {len(WARNS)} 项提示")
            for w in WARNS:
                print(f"   · {w}")
        print("\n→ 要不要按以上提示加厚，**由你（或用户）决定**：")
        print("   本检查默认不设门槛、不阻拦出稿；罗森案原版（精炼版）同样会有这些提示。")
        print(f"   （本次 {passed}/{len(dims)} 个维度达标）")
        # ⚠️ 2026-09-17（R2 数据科学视角第 11 条）：depth_check 原本「退出码一律 0」，
        #    于是「KPI 无预警线」「风险 0 条」这类**量化硬伤可以带着 ❌ 交付**，
        #    校验沦为参考意见。--strict 只对三项量化硬指标拦，其余仍只提示。
        if strict and HARD:
            print(f"{NG} --strict：{len(HARD)} 项量化硬指标未达标 —— 拒绝交付。")
            for x in HARD[:6]:
                print(f"   · {x}")
            sys.exit(1)
        sys.exit(0)

    print(f"{OK} 深度校验通过（{passed}/{len(dims)} 个维度达标，硬指标 0 项未达标）。")
    if WARNS:
        print(f"{WARN} {len(WARNS)} 项警告，交付前请人工确认：")
        for w in WARNS:
            print(f"   · {w}")
    print("\n→ 阈值来源：references/07-质量范式-便利店开学季案.md §五（罗森案 9 份产出实测）。")
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
        print("   2) 若属环境问题（文件读不到／编码异常），改用人工比对 §五 的 83 项指标，不要卡在这里；")
        print("   3) 同一项连续 2 次不过 → 停止重试，把问题摊给用户决定。")
        sys.exit(2)
