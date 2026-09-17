#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
案例卡清理 · case_clean.py —— 按「子句」剔除公司背景，保留营销结果

背景（2026-09-16）：SKILL「案例集硬规则」禁止公司背景（创始人／成立年份／股权／融资／营收／财报／估值／人事），
但库里有 2316 处违规。**不能整行删** —— 因为同一行常同时含「财报数字（该删）」与
「营销结果（该留，如销量第一／市占率／播放量）」。故本工具**按子句**处理。

保护（不碰）：
  - 46–51 机构／书籍／出版物类（规则豁免）
  - 行首 `>`（引用／说明）与 `|`（表格）行 —— 避免破坏结构与可信度图例
  - 含「可信度」的行（如「【已核实】财报／官方公告可查」——这里的「财报」是来源类型，非公司背景）
  - 文件前 12 行（标题＋图例）

用法：
    python scripts/case_clean.py --dry-run  references/cases/39-*.md   # 只看会删什么
    python scripts/case_clean.py --apply                                # 全库 01–45 应用
退出码：0 正常；1 未变更（dry-run 无命中时）；2 出错
"""

import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
EXEMPT_SKIP = {49}   # 只豁免 49（营销书籍与作者：作者名/书名就是重点）

# 身份／股权类 —— 与营销无关且无歧义，可安全自动删（--scope identity）
IDENTITY = ["创始人", "创始人", "创办人", "创办人", "成立于", "成立于",
            "股权", "股权", "融资", "融资", "估值", "董事长", "董事长",
            "CEO", "裁员", "裁员", "IPO", "上市首日", "招股书", "招股书",
            # 2026-09-16 补：企业介绍常见写法（用户：能删就删，留名字+title）
            "创立", "创立", "创办", "创办", "前身", "始建", "落户", "落户",
            "港交所", "递交", "递交", "上市申请", "上市申请", "保荐", "保荐",
            "独角兽", "独角兽", "A+H", "轮融资", "轮融资", "亿元融资", "亿美元融资",
            "创始于", "创始于", "发源于", "发源于"]

# 财务类 —— 常与「营销结果」黏在同一行（如「线下渠道收入 X 亿、线上只有 Y 亿」），
# 自动删会把句子改烂 → 预设不动，需逐卡人工改写（--scope finance 才碰，且务必复核）
FINANCE = ["营收", "营收", "财报", "财报", "净利", "净利", "归母", "归母", "扣非",
           "利润", "利润", "毛利率", "净利率", "净利率", "收入", "市值", "市盈率",
           "EPS", "股价", "股价", "负债", "负债", "现金流", "现金流",
           "增发", "增发", "营业额", "营业额"]

FORBID = IDENTITY + FINANCE

# 含这些标记的子句＝「营销结果」→ 即使带财报词也保留（该留的是营销结果）
SAFE_CTX = [   # 语境豁免（2026-09-16）：这些写法里「创始人/融资/营收」不是公司背景
    r"给[^。]{0,10}创始人", r"创始人[^。]{0,10}(补课|扫盲|露脸|出镜|做|团队)",
    r"(客户|对方)[^。]{0,14}融资", r"融资或并购", r"融资[、／/]并购",
    r"(万|亿|\d)[^。]{0,6}营收的客户", r"营收的客户", r"非营销背景",
    r"乙方机构", r"按[^。]{0,8}营收", r"营收规模", r"年?营收约",
    r"(亏损|减值|裁员)[^。]{0,10}(风险|条款|适用|同样)",
    r"创始人[^。]{0,6}(访谈|专访|自述|公开信|直播|内部信)",  # 信源类型，非身世
    r"(已核实|未核实|行业认知)[^】]{0,20}访谈",
]

# 纯金额子句（无营销含义的财报数字，如「酱油 149.34 亿元」）—— 之前因无财务词而漏掉
MONEY = re.compile(r"\d[\d,\.]*\s*(?:亿元|亿元|万亿|万亿|亿美元|亿美元|亿港元|亿日圆|亿日元|亿|万|万)")
# 这些是「营销金额」：预算/投入/定价/客单/折扣等 —— 带这些词的金额要保留
PRICE_CTX = ["预算", "预算", "成本", "客单", "客单", "售价", "售价", "定价", "定价",
             "价格", "价格", "投入", "投放", "花费", "花费", "费用", "费用",
             "补贴", "补贴", "券", "折扣", "单价", "单价", "加盟费", "加盟费", "人力"]

KEEP_MARK = ["销量", "销量", "市占", "市占", "曝光", "播放", "热搜", "热搜", "门店", "门店",
             "复购", "复购", "客流", "下载", "下载", "DAU", "MAU", "用户数", "用户数",
             "粉丝", "粉丝", "客单", "客单", "转化", "转化", "留存", "好评", "好评",
             "榜", "GMV", "排名", "进店", "进店", "到店", "互动", "互动", "点赞", "点赞"]

# 子句分隔：中英文标点（保留分隔符在子句尾，这样删掉子句时分隔符一起消失）
SPLIT = re.compile(r"(?<=[、，；;。])")
# 行首标签前缀（- **结果**： / 1. / **X**： …）—— 清理后要接回去
_M_MARK = re.compile(r"^\s*(?:[-*+]\s*|\d+[.、]\s*)")
_M_LABEL = re.compile(r"^(\*\*[^*\n]{1,40}\*\*)\s*[:：]?\s*")
def _prefix(ln):
    m = _M_MARK.match(ln)
    head = m.group(0) if m else ""
    m2 = _M_LABEL.match(ln[len(head):])
    return head + (m2.group(0) if m2 else "")


def clean_line(ln, forbid=None):
    forbid = forbid if forbid is not None else IDENTITY
    if re.match(r"^#{1,6}\s", ln):          # 标题（品牌名+角度）＝参考对象，绝不动
        return ln, 0
    if ln.lstrip().startswith((">", "|")) or "可信度" in ln:
        return ln, 0
    prefix = _prefix(ln)
    rest = ln[len(prefix):]
    if not rest.strip():
        return ln, 0
    kept, dropped = [], 0
    for part in SPLIT.split(rest):
        has_bg = any(k in part for k in forbid)
        has_mkt = any(k in part for k in KEEP_MARK)
        has_money = bool(MONEY.search(part)) and not any(k in part for k in PRICE_CTX)
        if (has_bg or has_money) and not has_mkt and not any(re.search(rx, part) for rx in SAFE_CTX):
            dropped += 1
        else:
            kept.append(part)
    if not dropped:
        return ln, 0
    out = "".join(kept)
    out = re.sub(r"[、，,；;]{2,}", "、", out)
    out = re.sub(r"[、，,；;]\s*$", "", out)
    out = re.sub(r"^[、，,；;。\s]+", "", out)
    out = re.sub(r"[（(]\s*[)）]", "", out)
    # 括号残缺：删掉子句后若有没配上的「（」，从它截断（连同后面的残留）
    if out.count("（") > out.count("）"):
        out = out[:out.rfind("（")].rstrip("、，；; ")
    while out.count("）") > out.count("（") and "）" in out:
        out = out.replace("）", "", 1)
    while out.count("**") % 2:      # 修补被删掉一半的粗体
        i = out.rfind("**")
        out = out[:i] + out[i+2:]
    if not out.strip():
        return None, dropped          # 整行都是背景 → 整行删
    cand = prefix + out
    if _looks_broken(ln, cand):       # 改烂了 → 回退整行（宁可留著，也不毁句子）
        return ln, 0
    return cand, dropped


DANGLE = ("只有", "但", "而", "即", "且", "也", "均", "以及", "同比", "环比", "环比",
          "其中", "较上年", "较上年", "归母", "归母", "净利", "净利", "收入", "营收", "，", "、")


def _looks_broken(orig, new):
    """清理后若像「残句」就整行回退 —— 财务子句常与营销结果黏在一起，硬删会毁句。"""
    if new.count("（") != new.count("）") or new.count("(") != new.count(")"):
        return True
    if new.count("**") % 2:
        return True
    tail = re.sub(r"^\s*(?:[-*+]|\d+[.、])\s*", "", new).lstrip("*").lstrip()
    if tail.startswith(DANGLE):
        return True
    if re.search(r"[，、；]\s*[。；]", new):
        return True
    strip = lambda s: re.sub(r"[\s*\-|]", "", s)
    # 注：财务子句本来就该被大量删掉，「删得多」不等于「改烂」。
    #     只有当剩下的字**少到不成句**（<12 字）才当残句。结构问题另有括号/粗体/残词三道检查。
    if len(strip(new)) < 12:
        return True
    return False


def process(path, apply, forbid):
    lines = open(path, encoding="utf-8").read().splitlines()
    out, dropped_total, changed = [], 0, 0
    for i, ln in enumerate(lines):
        if i < 12:
            out.append(ln)
            continue
        new, d = clean_line(ln, forbid)
        dropped_total += d
        if new is None:
            changed += 1
            continue
        if new != ln:
            changed += 1
        out.append(new)
    if apply and changed:
        open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
    return dropped_total, changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--scope", default="identity", choices=["identity", "finance", "all"],
                    help="identity=只删身世/股权（安全，预设）；finance=也删财报数字（会改烂句子，需复核）；all=两者")
    a = ap.parse_args()
    if not (a.dry_run or a.apply):
        a.dry_run = True

    files = a.paths or sorted(glob.glob(os.path.join(ROOT, "references", "cases", "*.md")))
    tot_d = tot_c = 0
    for f in files:
        base = os.path.basename(f)
        m = re.match(r"(\d+)", base)
        if not m:
            continue          # 非编号档（README.md 等）不是案例卡，禁止碰
        if int(m.group(1)) in EXEMPT_SKIP:
            continue
        d, c = process(f, a.apply, {"identity": IDENTITY, "finance": FINANCE, "all": FORBID}[a.scope])
        tot_d += d
        tot_c += c
        if d and a.dry_run:
            print(f"  {base}: 将删 {d} 个子句 / 动 {c} 行")
    print("-" * 60)
    print(f"{'APPLY 完成' if a.apply else 'DRY-RUN'}：删除子句 {tot_d}｜修改行 {tot_c}")
    sys.exit(0 if tot_d else 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 出错：{type(e).__name__}: {e}")
        sys.exit(2)
