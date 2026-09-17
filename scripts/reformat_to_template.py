#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按格式范本重排 · reformat_to_template.py  （marketing-playbook 后置环节）

用途
----
客户／比赛／招标常常自带**提交格式范本**（章节清单、模板文件）。
本工具把已经生成的方案稿**按范本骨架重排**，同时**保证硬要素一件不丢**（协议 2：合并，不取舍）。

它做三件事：
    ① 解析范本骨架（.md / .txt / .docx 都行 —— docx 按 Heading 样式取章节）
    ② 按映射把源稿章节填进范本对应位置（无映射时自动按标题相似度建议）
    ③ **硬要素核对**：确认重排后没有丢失关键要素，并列出「范本要、但源稿没有」的待补章节

用法
----
    # 1) 先看自动匹配建议（不写档）
    python scripts/reformat_to_template.py --source 方案.md --template 比赛提交清单.docx --dry-run

    # 2) 人工/AI 确认后，写出映射表再重排
    python scripts/reformat_to_template.py --source 方案.md --template 范本.md \\
        --map 映射.json -o 方案-按范本.md --report 要素核对.md

映射表格式（章节标题 → 源稿章节标题列表；可为空 = 该节需新写）
    {
      "一、项目背景": ["一 · 诊断"],
      "二、营销策略": ["二 · 策略", "三 · 定位与口径"],
      "三、执行计划": ["四 · 触达与渠道", "七 · 落地文案与物料"],
      "四、预算": ["九 · 预算明细与盈亏线"],
      "五、风险评估": ["十 · 执行与风控"],
      "六、附录": []
    }

退出码：0 = 成功；1 = 有硬要素丢失（**应修正后重跑**）；2 = 环境/文件问题
"""

import argparse
import difflib
import json
import os
import re
import sys

from _common import OK, NG, WARN, HINT, INFO   # noqa: E402  统一符号，不要在各自文件里重定义

# 硬要素清单（协议 2 要求「一件不丢」的关键项）
KEY_ELEMENTS = {
    "执行摘要": r"TL;DR|执行摘要|执行摘要|核心结论卡|核心结论卡",
    "问题类型（A–H）": r"问题类型|问题类型",
    "卡点重构句（不是X——是Y）": r"不是[^\n]{0,60}(——|—|--)",
    "打法组合": r"\*\*打法\s*\d+|为什么用它|为什么用它",
    "禁用词与口径": r"禁用词|禁用词",
    "KPI 与预警线": r"KPI|预警线|预警线",
    "预算明细": r"预算明细|预算明细|预算表|预算表",
    "行动清单": r"行动清单|行动清单",
    "风险与兜底": r"兜底|风险清单|风险清单|模式\s*\d{1,2}",
    "关键假设": r"关键假设|关键假设|假设|假设",
    "交付自检单": r"自检单|自检单",
}


def read_text(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        try:
            from docx import Document
        except ImportError:
            print(f"{NG} 读取 .docx 需要 python-docx：pip install python-docx")
            sys.exit(2)
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        d = Document(path)
        out = []
        # 按文档**原始顺序**取段落与表格（旧版把表格全部排到末尾 → 清单表跑到最后，顺序全错）
        for child in d.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                txt = Paragraph(child, d).text.strip()
                if not txt:
                    continue
                style = (Paragraph(child, d).style.name or "").lower()
                m = re.search(r"heading\s*(\d)", style)
                out.append(("#" * (int(m.group(1)) + 1) + " " + txt) if m else txt)
            elif tag == "tbl":
                for row in Table(child, d).rows:
                    cells = [c.text.strip() for c in row.cells]
                    if any(cells):
                        out.append("| " + " | ".join(cells) + " |")
        return "\n".join(out)
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


def split_sections(md: str, max_level: int = 3):
    """把 markdown 切成 [(标题, 内容), ...]（标题层级 ≤ max_level）"""
    lines = md.split("\n")
    secs, cur_title, buf = [], None, []
    for ln in lines:
        m = re.match(r"^(#{1,%d})\s+(.*)$" % max_level, ln)
        if m:
            if cur_title is not None:
                secs.append((cur_title, "\n".join(buf).strip()))
            cur_title, buf = m.group(2).strip(), []
        else:
            if cur_title is not None:
                buf.append(ln)
    if cur_title is not None:
        secs.append((cur_title, "\n".join(buf).strip()))
    return secs


_HAS_OPENCC = True
try:  # 可选：繁简归一化，让自动匹配更准
    from opencc import OpenCC
    _T2S = OpenCC("t2s")
    def _fold(s: str) -> str:
        return _T2S.convert(s)
except Exception:
    _HAS_OPENCC = False
    def _fold(s: str) -> str:
        return s


def norm(s: str) -> str:
    """归一化：去繁简差异 + 去标点/序号/空白 → 只留可比对的字"""
    s = _fold(s)
    return re.sub(r"[\s·、，,。：:（）()\[\]【】一二三四五六七八九十\d\.\-—]+", "", s)


def suggest_map(src_titles, tpl_titles, threshold=0.34):
    """自动建议映射：范本章节 → 最相似的源稿章节（可多个）"""
    sug = {}
    for t in tpl_titles:
        scored = sorted(
            ((difflib.SequenceMatcher(None, norm(t), norm(s)).ratio(), s) for s in src_titles),
            reverse=True,
        )
        picked = [s for sc, s in scored if sc >= threshold][:3]
        sug[t] = picked
    return sug


def check_elements(text: str):
    return {name: bool(re.search(pat, text)) for name, pat in KEY_ELEMENTS.items()}


def main():
    ap = argparse.ArgumentParser(description="按格式范本重排（硬要素不丢）")
    ap.add_argument("--source", required=True, help="已生成的方案稿（.md）")
    ap.add_argument("--template", required=True, help="格式范本（.md/.txt/.docx）")
    ap.add_argument("--map", dest="mapfile", help="章节映射 JSON")
    ap.add_argument("-o", "--out", help="输出重排后的 .md")
    ap.add_argument("--report", help="输出要素核对报告 .md")
    ap.add_argument("--dry-run", action="store_true", help="只打印建议映射，不写档")
    a = ap.parse_args()

    src = read_text(a.source)
    tpl = read_text(a.template)
    # 范本的第一个 H1 当「文档标题」，不算章节
    tpl_title = ""
    m = re.match(r"^#\s+(.+)$", tpl.strip().split("\n")[0]) if tpl.strip() else None
    if m:
        tpl_title = m.group(1).strip()
        tpl = "\n".join(tpl.strip().split("\n")[1:])
    src_secs = split_sections(src)
    tpl_secs = split_sections(tpl)
    src_titles = [t for t, _ in src_secs]
    tpl_titles = [t for t, _ in tpl_secs]

    print("=" * 64)
    print("按格式范本重排 · marketing-playbook")
    print(f"  源稿：{a.source}（{len(src_secs)} 个章节）")
    print(f"  范本：{a.template}（{len(tpl_secs)} 个章节）")
    print("=" * 64)
    if not _HAS_OPENCC:
        print(f"{WARN} 未安装 opencc → 自动匹配**不折算繁简**"
              f"（源稿简体、范本繁体时匹配率会偏低）；可 `pip install opencc`，或直接用 --map 指定。")

    # ---------- 映射 ----------
    if a.mapfile and os.path.exists(a.mapfile):
        mapping = json.load(open(a.mapfile, encoding="utf-8"))
        # 兜底：映射键与范本标题在繁简／标点上不一致时，按 norm() 归一后再对一次
        norm_tpl = {norm(t): t for t in tpl_titles}
        mapping = {norm_tpl.get(norm(k), k): v for k, v in mapping.items()}
        print(f"\n{OK} 使用提供的映射表（{len(mapping)} 条）")
    else:
        mapping = suggest_map(src_titles, tpl_titles)
        print(f"\n{WARN} 未提供 --map → 以下是**自动建议**（请人工/AI 确认后写成 JSON 再重排）：")
        for t, ss in mapping.items():
            print(f"   「{t}」  ←  {('、'.join(ss)) if ss else '（无匹配 → 需新写）'}")

    if a.dry_run:
        print(f"\n{HINT} --dry-run：未写档。确认映射后：")
        print(f"    python scripts/reformat_to_template.py --source {a.source} "
              f"--template {a.template} --map 映射.json -o 方案-按范本.md")
        sys.exit(0)

    # ---------- 重排 ----------
    src_map = {t: c for t, c in src_secs}
    out_lines, unfilled, used = [], [], set()
    for t, tpl_body in tpl_secs:
        out_lines.append(f"## {t}\n")
        picked = mapping.get(t, [])
        body_parts = []
        for s in picked:
            if s in src_map:
                # 保留来源小节标题：① 可追溯「这段从哪来」② 保住要素关键词（如「TL;DR」「禁用词」）
                body_parts.append(f"### {s}\n\n{src_map[s]}"); used.add(s)
            else:
                print(f"   {WARN} 映射指向的源稿章节不存在：{s}")
        if body_parts:
            out_lines.append("\n\n".join(body_parts) + "\n")
        else:
            # 范本章节本身有内容（例如说明文字）就保留，否则标待补
            note = "【待补：范本此节需新写内容 —— 来源稿中无对应章节】"
            out_lines.append((tpl_body + "\n\n" if tpl_body else "") + note + "\n")
            unfilled.append(t)
    # 未被用到的源稿章节 → 附录（协议 2：不取舍，多的放附件）
    leftovers = [t for t in src_titles if t not in used]
    if leftovers:
        if len(leftovers) > len(src_titles) * 0.5:
            print(f"\n{WARN} 未被映射的章节达 {len(leftovers)}/{len(src_titles)}（超过一半）"
                  f"—— 请确认映射是否漏了（漏的会被整节塞进附录，读起来会散）")
        out_lines.append("## 附录：范本未涵盖、但原稿有的内容\n")
        out_lines.append(f"> 协议 2「合并，不取舍」：以下章节范本没有对应位，整节移入附录。\n")
        for t in leftovers:
            out_lines.append(f"### {t}\n")
            out_lines.append(src_map.get(t, "") + "\n")

    if tpl_title:
        out_lines.insert(0, f"# {tpl_title}\n")
    out_md = "\n".join(out_lines)

    # ---------- 硬要素核对 ----------
    src_el, out_el = check_elements(src), check_elements(out_md)
    lost = [k for k in KEY_ELEMENTS if src_el[k] and not out_el[k]]
    gained = [k for k in KEY_ELEMENTS if out_el[k] and not src_el[k]]

    print("\n" + "=" * 64)
    print("硬要素核对（协议 2：合并，不取舍）")
    for k in KEY_ELEMENTS:
        if src_el[k] and not out_el[k]:
            print(f"  {NG} 丢失：{k}")
        elif src_el[k]:
            print(f"  {OK} 保留：{k}")
    if unfilled:
        print(f"\n{WARN} 范本有 {len(unfilled)} 节源稿无法填（需新写）：")
        for t in unfilled:
            print(f"   · {t}")
    if leftovers:
        print(f"\n{OK} 源稿有 {len(leftovers)} 节范本没对应位 → 已整节移入附录（未丢）")

    if gained:
        print(f"\n{HINT} 重排后新增的要素（范本要求、源稿原本没有）：{'、'.join(gained)}")
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(out_md)
        print(f"\n{OK} 已写出：{a.out}（{len(out_md.splitlines())} 行）")
    if a.report:
        rep = ["# 格式范本重排 · 要素核对报告", "",
               f"- 源稿：`{a.source}`（{len(src_secs)} 节）",
               f"- 范本：`{a.template}`（{len(tpl_secs)} 节）", "",
               "## 硬要素核对", ""]
        for k in KEY_ELEMENTS:
            mark = NG if (src_el[k] and not out_el[k]) else (OK if src_el[k] else "—")
            rep.append(f"- {mark} {k}")
        rep += ["", "## 范本要、源稿没有（需新写）", ""]
        rep += [f"- {t}" for t in unfilled] or ["- （无）"]
        rep += ["", "## 源稿有、范本没对应位（已移入附录）", ""]
        rep += [f"- {t}" for t in leftovers] or ["- （无）"]
        os.makedirs(os.path.dirname(os.path.abspath(a.report)), exist_ok=True)
        with open(a.report, "w", encoding="utf-8") as f:
            f.write("\n".join(rep))
        print(f"{OK} 已写出核对报告：{a.report}")

    print("=" * 64)
    print(f"{HINT} 下一步：对重排后的 .md 跑唯一出稿入口")
    print(f"    python scripts/run_pipeline.py --rules rules.json --plan {a.out or '方案-按范本.md'} "
          f"-o 方案-按范本.docx --title \"客户名 营销方案\"")
    if lost:
        print(f"\n{NG} 有 {len(lost)} 项硬要素丢失 —— **先补齐再出稿**（协议 2）。")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ 已中断。")
        sys.exit(130)
    except Exception as e:  # pragma: no cover
        print(f"\n{NG} 执行出错：{type(e).__name__}: {e}")
        sys.exit(2)
