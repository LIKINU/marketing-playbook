#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 `references/06-本土数字营销与MCN.md` 并入 cases 库 · relocate_06.py

为什么（2026-09-17，用户指令）：
    「050607 为甚么没放在 cases 库里 而且要跟 cases 库的格式一样」
    用户裁定：**06 进 cases；05/07 只统一标题**（后者由 top_titles.py 处理）。

06 为什么原本不在 cases：
    它是「机构＋操盘手＋平台模型」的调研报告，用 `# A. / ## A1.` 分块，
    与 cases 库的 `行业概览／门禁清单／深度拆解／对接实测清单／查不到的部分／相关`
    六槽结构不同。但内容本身是好的（每卡六段：定位／商业模式／操盘手法／失败归因／
    可复用套路／反面教训），**不为了搬家把内容砍掉**——只重排结构。

做什么：
    1. 29 个 `## X#.` 区块 → cases 卡片 `### 3.N 标题`（3.1–3.29，按档内实际顺序重编）
    2. 四组用粗体组标示：甲 本土营销集团／乙 MCN／丙 新消费操盘／丁 平台模型
       （用粗体而非 `## `，因为 cases 的 `## ` 是六个固定槽位）
    3. 卡内原本的 `### ` 小节降一级为 `#### `
    4. 补上原本缺的槽位：一、行业概览／二、门禁清单／四、对接实测清单／六、相关
    5. 原本五节「查不到的部分」降为 `### `，收进 `## 五、查不到的部分`
    6. 加一条 `> ⚠️ 用法红线`（本档含机构财务足迹，不得写进交付物）
    7. 删原档、全库更新引用

硬不变式（任一不过就不写入）：
    1. 原文的**非标题行逐行全数出现在新文**（卡片正文零损失）
    2. 新档恰好 6 个 `## `，且全落在 46–51 的槽位白名单内
    3. 卡片数 = 30

用法：
    python scripts/relocate_06.py            # 体检（不写入）
    python scripts/relocate_06.py --fix
退出码：0 = 成功；1 = 不变式失败；2 = 脚本出错
"""

import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
REF = os.path.join(ROOT, "references")
CASES = os.path.join(REF, "cases")

SRC = os.path.join(REF, "06-本土数字营销与MCN.md")
DST = os.path.join(CASES, "51-本土数字营销与MCN.md")

# ── 卡片标题对照（原 `## X#. …` → 新标题；股票代码不进标题，正文里有）
TITLES = {
    "A1": "省广集团", "A2": "利欧数字", "A3": "引力传媒", "A4": "天下秀 IMS",
    "A5": "微播易 / 火星文化", "A6": "分众传媒",
    "B1": "无忧传媒", "B2": "遥望科技", "B3": "蜂群文化", "B4": "Papitube",
    "C1": "元气森林", "C2": "花西子（重点复盘）", "C3": "钟薛高（从「雪糕刺客」到破产）",
    "C4": "Ubras", "C5": "王小卤", "C6": "王饱饱",
    "C7": "完美日记 / 逸仙电商（简略版）", "C8": "三顿半（简略版）",
    "C9": "新消费品牌的集体退潮（2021–2024）合辑",
    "A7": "平台官方方法论：小红书种草 / 抖音 FACT+",
    "D1": "阿里：AIPL → DEEPLINK", "D2": "天猫：FAST 与 GROW",
    "D3": "京东：4A → JD GOAL", "D4": "抖音／巨量引擎：O-5A 与巨量云图",
    "D5": "腾讯广告：5R", "D6": "其他平台的模型（B 站 MATES / 知乎 DEEP / 快手）",
    "D7": "所有模型的横向对比与共同局限", "D8": "可直接复用的套路", "D9": "反面教训",
}

# ── 卡片顺序（= 输出顺序，也就是 3.1–3.29 的编号顺序）
#    原档的物理顺序是 A1…A6,A7,B1…B4,C1…C9,D1…D9 —— A7（平台官方方法论）
#    夹在 A6 和 B1 之间。为了让「甲/乙/丙/丁」四组连续、序号不跳，
#    这里按区块重排：A7 移到丁组开头（详见 transform）。
ORDER = ["A1", "A2", "A3", "A4", "A5", "A6",
         "B1", "B2", "B3", "B4",
         "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9",
         "A7", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9"]
IDX = {k: i + 1 for i, k in enumerate(ORDER)}

GROUPS = [
    ("A1", "**甲、本土数字营销与媒介集团**（要买量、要媒介代理时读）"),
    ("B1", "**乙、MCN 机构**（要投达人、要建内容矩阵时读）"),
    ("C1", "**丙、新消费品牌操盘复盘**（看别人怎么翻车，比看成功案例有用）"),
    ("A7", "**丁、各平台消费者资产模型**（平台官方方法论：只能照做，不能改）"),
]

CHABU = ["公司财务与业务数据缺失", "关键数字存在矛盾", "模型细节未能核实",
         "MCN 分成比例的具体数字", "其他未展开的部分"]

H1 = "# 本土数字营销与 MCN · 机构案例集"

REDLINE = ("> ⚠️ **用法红线**：本档比其他机构档多一层「机构财务足迹」（营收结构／毛利／应收帐款）。"
           "**那是给你判断「这家乙方能不能接你的单」用的，不是案例内容**——"
           "严禁把机构自身的营收、利润、员工数写进对客户的交付物（见 `cases/README.md` §六）。")

OVERVIEW = """## 一、行业概览

- **收费模式三种，对应三种完全不同的公司**：① 媒介代理赚**返点差价**（媒体给代理的返点通常 3%–15%，代理让渡一部分给广告主，自留 1%–5%）【行业认知】；② 内容与创意按项目收费；③ 达人／MCN 端抽成（行业访谈常见 10%–30%，**无单一权威口径，只能当谈判参考，不能写进合同模板**）。**接案第一件事是问清「这笔钱是服务费还是过帐」。**
- **上市与非上市是两个资料世界**：媒介代理集团多为上市公司（财报可查）；MCN 与创意热店几乎全部未上市，**规模、营收、达人数全靠自报**，引用前必须先降级。
- **毛利极薄是结构事实，不是经营不善**：省广 2025 年集团整体毛利率 **5.85%**、数字营销板块仅 **4.14%**、出海业务 **1.62%**（大陆 7.90%）——**总额法把媒体流水全额入帐，收入奇大、毛利奇薄**，任何风吹草动都吃掉利润。
- **MCN 的本质是流量批发，收入高度集中**：头部达人贡献大部分营收，**达人一走或塌房，乙方收入与甲方投放一起归零**。
- **规则由平台制定，代理只能执行**：AIPL／DEEPLINK、FAST／GROW、JD GOAL、O-5A、5R **全部是平台自建的人群资产模型**，目的是把投放与数据留在平台内。代理能做的是把模型翻译成可执行动作，**不能改模型**。
- **新消费操盘手（元气森林、花西子、钟薛高、完美日记…）的集体退潮说明一件事**：**流量操盘能力 ≠ 品牌资产**。投放驱动的增长在红利期看起来像品牌力，红利一停就现形。
"""

GATE = """## 二、门禁清单（选本土数字营销服务商前）

- **A. 需求类型**：要媒介代理（买量）／内容与创意／达人与 MCN／平台方法论落地／全域代运营？**这是五种不同的公司，报价与考核方式都不同。**
- **B. 预算与结算方式**：年度框架还是项目制？服务费比例？**代理商的垫资能力与帐期是这个行业的死穴**（省广 2025 年应收帐款单项计提坏帐 3.28 亿元、其他应收款计提 3.19 亿元，就是这个机制的代价）。
- **C. 费用结构**：服务费／返点／达人坑位费与佣金／素材制作费各占多少？**返点是分给你还是被吃掉？能不能看到媒体原始对帐单？**
- **D. 数据与资产归属（最容易被忽略、离场时最贵）**：投放帐户、素材版权、人群包、达人合约签在谁名下？**结束合作时带得走什么？**
- **E. 过去做过什么**：近 12 个月同品类战役？有无翻车（虚假宣传、刷量、达人塌房）？**有无行政处罚记录？**
- **F. 团队与交付**：提案团队与执行团队是不是同一批人？达人资源是自有签约还是二手转包？驻场人数与汇报频率？
- **G. 合规红线**：广告法禁用语清单、功效宣称、平台违规记录；**MCN 合约的违约金与竞业条款**——这一块接案双方都最容易吃亏。
- **H. 验收指标与口径**：以曝光／CPM／CPA／ROI／GMV 中的哪一个结算？**口径由谁定义、数据由谁提供？** 平台模型给的是可执行清单，还是 PPT？
"""

DOCKET = """## 四、对接实测清单（选本土数字营销服务商时问）

- **案例核实**：最近 3 个同品类案例，能不能给甲方对接人？**只给 PPT 不给联系人的，一律降级使用。**
- **资产归属**：投放帐户、素材、人群包、达人合约结束后归谁？**写进合同了吗？**
- **返点与对帐**：返点怎么算？我能不能看到媒体原始对帐单？
- **达人来源**：名单是自有签约还是平台抓取转包？坑位费与佣金怎么报？**达人出事谁担？**
- **方法论兑现**：平台模型（AIPL／5A／FAST）你能出可执行动作清单，还是只有方案 PPT？
- **责任分担**：出现虚假宣传处罚或达人塌房，责任与赔偿怎么分？
- **离场条款**：中途换人，达人合约、帐户与素材怎么处理？
- **成功标准**：这次以什么结算（曝光／CPA／ROI／GMV）？口径谁定义？
"""

RELATED = """## 六、相关

- `48-本土创意与营销服务商` —— 创意热店与全案服务商（华与华、蓝色光标等）。**本档是媒介代理集团与 MCN；要选乙方，两档一起看才够。**
- `46-国际4A与传播集团` —— 国际 4A 的对照组（方法论、收费结构与客户结构都不同）。
- `47-战略咨询` —— 策略层的外部大脑。**先分清你要买的是「策略」还是「执行」，再在这三档之间选。**
- `49-营销书籍与作者`、`50-机构出版物与观点库` —— 本档方法论的原始出处与延伸阅读。
- `references/03-方法论操作手册` —— 平台模型只是 111 个模型中的一类。**别把平台自建模型当通行方法论**（见本档「丁」）。
- `references/06-选流派矩阵与对照表` —— 「该找哪一类服务商」的选型入口。
- `references/04-失败归因总库` —— 流量结构依赖单一 IP、达人连坐、监管处罚等模式的归因（模式 04／05／06）。
"""


def transform(t):
    """回传（新档文字, 错误）"""
    lines = t.split("\n")
    starts = [i for i, l in enumerate(lines) if re.match(r"^##\s+[A-D]\d+\.", l)]
    if not starts:
        return None, "找不到任何 `## X#.` 卡片"
    first = starts[0]
    quotes = [l for l in lines[:first] if l.startswith(">")]   # 原文件头的「可信度标注规则」

    # ── 先按区块切（丢掉 `# A.` 这类组 H1；组前言暂存到 pending，挂在其后第一张卡前）
    blocks, pre, cur, pending = {}, {}, None, []
    for l in lines[first:]:
        if l.startswith("# "):
            cur = None
            continue
        m = re.match(r"^##\s+([A-D])(\d+)\.\s*(.*)$", l)
        if m:
            cur = m.group(1) + m.group(2)
            if cur not in TITLES:
                return None, f"未知卡片代号：{cur}"
            blocks[cur] = []
            if any(x.strip() for x in pending):
                pre[cur] = pending
            pending = []
            continue
        mc = re.match(r"^##\s+([一二三四五])\s*、\s*(.+?)\s*$", l)
        if mc and mc.group(2) in CHABU:
            cur = "CHABU"
            blocks.setdefault(cur, [])
            if any(x.strip() for x in pending):     # 「结尾」段的引言
                blocks[cur] += [x for x in pending if x.strip()] + [""]
                pending = []
            blocks[cur].append(f"### {mc.group(1)}、{mc.group(2)}")
            continue
        if cur is None:
            pending.append(l)          # 组前言（「# B. MCN 机构」后、B1 前那段）
            continue
        blocks[cur].append("#### " + l[4:] if l.startswith("### ") else l)

    missing = [k for k in ORDER if k not in blocks]
    if missing:
        return None, f"缺卡片区块：{missing}"
    if "CHABU" not in blocks:
        return None, "找不到「查不到的部分」五个小节"

    # ── 按 ORDER 重排输出（A7 因此移到丁组开头，序号连续不跳）
    out = []
    for blk in ORDER:
        body = re.sub(r"\n{3,}", "\n\n", "\n".join(blocks[blk])).strip()
        body = re.sub(r"\n-{3,}\s*$", "", body).strip()      # 去掉区块尾部的 ---
        for gk, glabel in GROUPS:
            if gk == blk:
                out += ["", glabel, ""]
        if pre.get(blk):
            out += [x for x in pre[blk] if x.strip()]
            out += [""]
        out += ["", f"### 3.{IDX[blk]} {TITLES[blk]}", "", body, "", "---"]
    head = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()

    chabu_text = re.sub(r"\n{3,}", "\n\n", "\n".join(blocks["CHABU"])).strip()
    parts = re.split(r"(?m)^### ([一二三四五]、)", chabu_text)
    if len(parts) < 3:
        return None, "「查不到的部分」小节切分失败"
    chunks = [parts[1 + i] + parts[2 + i] for i in range(0, len(parts) - 1, 2)]
    lead = parts[0].strip()          # 五小节之前的引言（不能丢）
    chabu = "\n\n".join("### " + c.strip() for c in chunks)
    if lead:
        chabu = lead + "\n\n" + chabu

    new = (H1 + "\n\n" + REDLINE + "\n" + "\n".join(quotes) + "\n\n"
           + OVERVIEW + "\n"
           + GATE + "\n"
           + "## 三、深度拆解\n\n" + head + "\n\n"
           + DOCKET + "\n"
           + "## 五、查不到的部分\n\n" + chabu + "\n\n"
           + RELATED)
    return re.sub(r"\n{3,}", "\n\n", new), None


def verify(old, new):
    def nonhead(s):
        return [l for l in s.split("\n") if l.strip() and not l.lstrip().startswith("#")]
    n = set(nonhead(new))
    miss = [l for l in nonhead(old) if l not in n]
    if miss:
        return f"{len(miss)} 行正文丢失，例：{miss[0][:70]!r}"
    h2 = re.findall(r"(?m)^##\s+(.+)$", new)
    if len(h2) != 6:
        return f"`## ` 应为 6 个，实为 {len(h2)}：{h2}"
    allow = ("行业概览", "门禁清单", "深度拆解", "对接实测清单", "查不到的部分", "相关")
    if not all(any(a in h for a in allow) for h in h2):
        return f"有不在槽位白名单内的标题：{h2}"
    cards = re.findall(r"(?m)^### 3\.\d+ ", new)
    if len(cards) != len(ORDER):
        return f"卡片数应为 {len(ORDER)}，实为 {len(cards)}"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(SRC):
        print(f"❌ 找不到来源档：{SRC}（可能已搬过）")
        sys.exit(1)
    t = open(SRC, encoding="utf-8").read()
    new, err = transform(t)
    if err:
        print(f"❌ 转换失败：{err}")
        sys.exit(1)
    v = verify(t, new)
    if v:
        print(f"❌ 不变式失败：{v}")
        sys.exit(1)

    print(f"✅ 转换通过：{len(ORDER)} 张卡｜{len(t)} 字 → {len(new)} 字")
    if not a.fix:
        print("（体检模式，未写入。加 --fix 执行）")
        sys.exit(0)

    open(DST, "w", encoding="utf-8").write(new)
    os.remove(SRC)
    print(f"✅ 写入 {os.path.relpath(DST, ROOT)}，删除 {os.path.relpath(SRC, ROOT)}")

    hits = 0
    # sorted()：glob 不保证顺序，遍历顺序不同→同一输入产出不同文件→
    # verify_all 的 50 遍哈希压测会随机报漂移，且极难复现。
    for f in sorted(glob.glob(os.path.join(ROOT, "**", "*.md"), recursive=True)):
        if "/.git/" in f or "/.workbuddy/" in f:
            continue
        s0 = open(f, encoding="utf-8").read()
        s = s0.replace("references/06-本土数字营销与MCN.md",
                       "references/cases/51-本土数字营销与MCN.md")
        s = s.replace("06-本土数字营销与MCN", "cases/51-本土数字营销与MCN")
        if s != s0:
            open(f, "w", encoding="utf-8").write(s)
            n = sum(1 for x, y in zip(s0.split("\n"), s.split("\n")) if x != y)
            hits += 1
            print(f"   引用更新：{os.path.relpath(f, ROOT)}（{n} 行）")
    print(f"✅ 引用更新：{hits} 个文件")
    print("接著跑：case_sections.py --fix && file_meta.py --fix")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
