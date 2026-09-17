#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 Word 交付稿 · build_docx.py  （marketing-playbook 第 5 步）

用途：把方案 Markdown 转成带封面、目录、页码、表格样式的 .docx。
      **前置强制**：先跑 selfcheck.py，不通过就拒绝生成 —— 交付物只能由本脚本产出，
      所以「拿不到 .docx」＝ 没完成，AI 绕不过校验。

用法：
    python build_docx.py plan.md -o 方案.docx --title "某品牌校园营销方案"
    python build_docx.py plan.md -o out.docx --title "X" --subtitle "副标题" --date 2026-09-14
    python build_docx.py plan.md -o out.docx --title "X" --skip-check   # 仅内部预览用（会大声警告）

依赖：python-docx（pip install python-docx）
"""

import argparse
import os
import re
import subprocess
import sys

try:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.section import WD_SECTION
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, Cm, RGBColor
except ImportError:
    print("❌ 缺少 python-docx。请先安装：pip install python-docx")
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import docx_footnote as DOCX_FN   # noqa: E402  Word 脚注装配器（python-docx 原生不支持）

CN_FONT = "微软雅黑"
from _common import OK, NG, WARN, HINT, INFO, TRAD_HINT   # noqa: E402  统一符号，不要在各自文件里重定义


# ---------- 字体与页码工具 ----------

def set_run_font(run, size=None, bold=None, color=None, font=CN_FONT):
    run.font.name = font
    r = run._element
    rPr = r.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), font)
    rFonts.set(qn("w:ascii"), font)
    rFonts.set(qn("w:hAnsi"), font)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color:
        run.font.color.rgb = color


def add_page_number_footer(section):
    """在页脚插入「第 X 页」域"""
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r1 = p.add_run("第 ")
    set_run_font(r1, size=9)
    run = p.add_run()
    f1 = OxmlElement("w:fldChar"); f1.set(qn("w:fldCharType"), "begin")
    it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve"); it.text = "PAGE"
    f2 = OxmlElement("w:fldChar"); f2.set(qn("w:fldCharType"), "end")
    run._r.append(f1); run._r.append(it); run._r.append(f2)
    set_run_font(run, size=9)
    r2 = p.add_run(" 页")
    set_run_font(r2, size=9)


def shade(cell, hexcolor="F2F2F2"):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hexcolor)
    tcPr.append(shd)


# ---------- Markdown 解析（够用即可） ----------

def strip_inline(s):
    """去掉行内标记（Word 里不该出现 Markdown 符号）。

    旧版只去 **粗体**，于是 composer 注入的 `cases/xx.md` 反引号、*斜体*、[链接](url)
    会原样留在 .docx 里 —— 客户看到一堆 `` ` ``。这里一次清干净。
    """
    s = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", s)               # ![alt](图片) → alt 文字（Word 无图）
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)                       # **粗体**
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", s)          # *斜体*
    s = re.sub(r"`([^`]+)`", r"\1", s)                            # `行内码`
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)                # [文字](链接)
    s = s.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")  # HTML 换行
    return s


def add_text_runs(p, text, size=10.5, fn=None, bold_all=False, color=None):
    """把一段行内文字渲染成 runs —— 同时处理 `**粗体**` 与 `[^label]` **真实脚注**。

    为什么要独立出这个函数：脚注引用必须**独占一个 run**，才能被 docx_footnote
    准确地换成 `<w:footnoteReference/>`；如果和上下文挤在同一个 run 里，
    就只能靠拆 XML 猜边界，必错。所以这里先按 `[^…]` 切段，每段脚注单独出一个 run。
    """
    for seg in re.split(r"(\[\^[^\]]+\])", text):
        if not seg:
            continue
        m = re.fullmatch(r"\[\^([^\]]+)\]", seg)
        if m and fn is not None:
            fid = fn.fid(m.group(1))
            r = p.add_run(DOCX_FN.placeholder(fid))
            set_run_font(r, size=size, bold=False, color=color)
            continue
        for part in re.split(r"(\*\*.+?\*\*)", seg):
            if not part:
                continue
            if part.startswith("**") and part.endswith("**"):
                r = p.add_run(part[2:-2]); set_run_font(r, size=size, bold=True, color=color)
            else:
                r = p.add_run(part); set_run_font(r, size=size, bold=bold_all, color=color)


def add_paragraph_with_bold(doc, text, size=10.5, style=None, fn=None):
    p = doc.add_paragraph(style=style)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.25
    add_text_runs(p, text, size=size, fn=fn)
    return p


def parse_table_block(block_lines):
    rows = []
    for ln in block_lines:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        # 分隔行：整行只由 - : 空白组成，且至少有一个 "-"（否则全空行会被误删）
        if all(re.match(r"^[-:\s]*$", c) for c in cells) and any("-" in c for c in cells):
            continue
        rows.append(cells)
    return rows


def render_markdown(doc, md_text, fn=None):
    """把 Markdown 渲染进 docx，回传收集到的标题（给目录用）

    `fn` = docx_footnote.FootnoteState；传入即启用**真脚注**渲染。
    """
    headings = []
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()

        # 围栏代码块 ``` … ```（旧版未识别 → 把 ``` 和块内内容当普通文字，甚至把块内 | 行当表格）
        if s.startswith("```"):
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Cm(0.5)
                p.paragraph_format.space_after = Pt(0)
                r = p.add_run(lines[i].rstrip())
                set_run_font(r, size=9, font="Consolas")
                i += 1
            if i < len(lines):
                i += 1  # 跳过结尾 ```
            continue

        # 表格
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[-:\s|]+\|$", lines[i + 1].strip()):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i]); i += 1
            rows = parse_table_block(block)
            if rows:
                ncol = max(len(r) for r in rows)
                if ncol > 6:
                    print(f"{WARN} 表格有 {ncol} 列（>6）—— SKILL 要求表格 ≤5 列，"
                          f"宽表在 Word 会挤成一条竖线；建议改多段文字或拆表。")
                t = doc.add_table(rows=0, cols=ncol)
                t.style = "Table Grid"
                for ri, row in enumerate(rows):
                    cells = t.add_row().cells
                    for ci in range(ncol):
                        val = row[ci] if ci < len(row) else ""
                        cells[ci].text = ""
                        para = cells[ci].paragraphs[0]
                        add_text_runs(para, strip_inline(val), size=9, fn=fn, bold_all=(ri == 0))
                        if ri == 0:
                            shade(cells[ci])
                doc.add_paragraph()
            continue

        # 标题
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            level = len(m.group(1))
            text = strip_inline(m.group(2)).strip()
            text = re.sub(r"\[\^[^\]]+\]", "", text)   # 标题里的脚注标记直接去掉（标题不需要出处）
            if level <= 3:
                h = doc.add_heading(level=min(level, 3))
                r = h.add_run(text)
                set_run_font(r, size={1: 18, 2: 14, 3: 12}.get(level, 11), bold=True,
                             color=RGBColor(0x1F, 0x1F, 0x1F))
                headings.append((level, text))
            else:
                add_paragraph_with_bold(doc, f"■ {text}", size=10.5, fn=fn)
                headings.append((4, text))
            i += 1
            continue

        # 引用
        if s.startswith(">"):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.6)
            # ⚠️ 这里原本是 `p.add_run(strip_inline(...))` —— 绕过了 add_text_runs，
            #    导致**引用块里的 `[^n]` 不会变成脚注**，而是以字面 `[^3]` 留在正文里
            #    （实测：3 条脚注只装配出 2 条）。凡正文内容一律走 add_text_runs。
            add_text_runs(p, strip_inline(s.lstrip("> ").strip()), size=9.5, fn=fn,
                          color=RGBColor(0x60, 0x60, 0x60))
            i += 1
            continue

        # 分隔线
        if re.match(r"^-{3,}$", s):
            i += 1
            continue

        # 列表
        m_list = re.match(r"^(\s*)([-*]|\d+[.、)])\s+(.*)$", ln)
        if m_list:
            indent, marker, text = len(m_list.group(1)), m_list.group(2), m_list.group(3)
            # ⚠️ 2026-09-17 修正：原先把**所有**列表项的标记一律换成「・」，
            #    导致有序列表的编号（1. 2. 3.…）全部丢失 —— 打法/步骤类内容
            #    在 Word 里变成一串没有序号的圆点段落，用户实测反馈「看起来像表格生成坏了」。
            #    修正：有序列表保留原始编号，仅无序列表用「・」。
            if marker[0].isdigit():
                num = re.match(r"\d+", marker).group(0)
                body = num + ". " + text
            else:
                body = "・" + text
            p = add_paragraph_with_bold(doc, body, size=10.5, fn=fn)
            if indent >= 2:   # 嵌套列表：按缩进层级缩进（旧版一律压平）
                p.paragraph_format.left_indent = Cm(0.5 * (indent // 2))
            elif marker[0].isdigit():   # 有序列表：悬挂缩进，数字与正文对齐
                p.paragraph_format.left_indent = Cm(0.55)
                p.paragraph_format.first_line_indent = Cm(-0.55)
            i += 1
            continue

        # 空行
        if not s:
            i += 1
            continue

        # 一般段落
        add_paragraph_with_bold(doc, s, size=10.5, fn=fn)
        i += 1

    return headings


# ---------- 主流程 ----------

def main():
    ap = argparse.ArgumentParser(description="把方案 Markdown 转成 Word 交付稿")
    ap.add_argument("md", help="方案 Markdown 档路径")
    ap.add_argument("-o", "--output", required=True, help="输出 .docx 路径")
    ap.add_argument("--title", required=True, help="封面主标题（项目名）")
    ap.add_argument("--subtitle", default="", help="封面副标题")
    ap.add_argument("--date", default="", help="封面日期")
    ap.add_argument("--author", default="", help="封面署名")
    ap.add_argument("--banned", default="", help="自订禁用词表 JSON")
    ap.add_argument("--rules", default="", help="《任务规则表》JSON —— **没提供会拒绝出稿**（用来强制『先问用户』）")
    ap.add_argument("--no-cover", action="store_true", help="不生成封面（省约 1 页）—— 页数紧张时用")
    ap.add_argument("--no-toc", action="store_true", help="不生成目录（省约 1 页）—— 5 页以内的小文档建议加上")
    ap.add_argument("--skip-check", action="store_true",
                    help="跳过自检（仅内部预览用）。行为同 --force，但语义是『预览』；正式交付请用 --force 并声明未校验")
    ap.add_argument("--force", action="store_true",
                    help="紧急出口（协议 8）：跳过自检强制生成。交付时必须声明「本稿未通过校验」并列出未通过项")
    args = ap.parse_args()

    # ---- 前置：跑 selfcheck ----
    # ── 硬前提：必须先有《任务规则表》＝ 先问过用户要什么结构／量级／字数 ──
    #    2026-09-14 用户指出：AI 常常「不问就开跑」，门禁只覆盖新项目、
    #    覆盖不到「重新生成／改结构」这类任务。所以把「问用户」变成机械前提：
    #    **拿不到规则表 → 出不了稿。**
    if not args.rules and not (args.force or args.skip_check):
        print("=" * 64)
        print(f"{NG} 拒绝出稿：未提供《任务规则表》（--rules）")
        print()
        print("这通常意味著：**你没有先问过用户**这三件事 ——")
        print("   ① 交付结构（**精炼版**：只放能执行的／**完整版**：含现状分析）")
        print("   ② 内容量级（**摘要版** 1–2 页／**标准版**／**完整版**）")
        print("   ③ 有没有字数或页数的硬要求")
        print()
        print("→ 做法：先跑 `gate_check.py` 产出《任务规则表》并请用户确认，再出稿。")
        print("→ 若用户已明确同意跳过，加 `--force`（交付时必须声明未经门禁）。")
        print("=" * 64)
        sys.exit(1)
    if args.rules:
        if not os.path.exists(args.rules):
            print(f"{NG} 找不到《任务规则表》文件：{args.rules}")
            sys.exit(1)
        print(f"{OK} 已提供《任务规则表》：{args.rules}")

    if args.skip_check or args.force:
        print("=" * 64)
        print(f"{WARN} 紧急出口：已跳过交付前自检。")
        print(f"{WARN} 依协议 8，交付时你【必须】：")
        print("       ① 明确声明「本稿未通过交付前校验」")
        print("       ② 列出未校验的项目")
        print("       ③ 不得声称已完成")
        print("       （建议先跑 selfcheck.py 看看到底卡在哪，再决定要不要跳）")
        print("=" * 64)
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        # ① 强制门槛：selfcheck（结构完整性 —— 缺章节、缺自检单、内部文档泄漏）
        checks = [
            ("交付前自检 selfcheck.py",
             [sys.executable, os.path.join(here, "selfcheck.py"), args.md]
             + (["--banned", args.banned] if args.banned else [])),
        ]
        # ② 只报告、不设门槛：depth_check（要素厚薄 —— 用户定调 2026-09-14：只提示不拦）
        advisory = [
            ("深度诊断 depth_check.py",
             [sys.executable, os.path.join(here, "depth_check.py"), args.md]),
        ]
        failed = []
        for name, cmd in checks:
            if not os.path.exists(cmd[1]):
                print(f"{WARN} 找不到 {cmd[1]}，跳过「{name}」（不阻塞出稿，但请留意）\n")
                continue
            print(f"→ 先跑{name} ...\n")
            if subprocess.call(cmd) != 0:
                failed.append(name)
            print()
        if failed:
            print("=" * 64)
            print(f"{NG} 结构校验未通过 → 拒绝生成 .docx。未通过项：{'、'.join(failed)}")
            print("→ 修正后重跑；这是协议 3 的强制点。")
            print("→ 依协议 8：同一项连续 2 次不过就停止重试，把问题摊给用户；")
            print("   或经用户同意用 --force 出稿（交付时必须声明未校验）。")
            print("=" * 64)
            sys.exit(1)

        # 深度诊断：只印报告，**不阻拦出稿**
        for name, cmd in advisory:
            if os.path.exists(cmd[1]):
                print(f"→ 跑{name}（仅诊断，不阻拦出稿）...\n")
                subprocess.call(cmd)
                print()

        print("=" * 64)
        print(f"{OK} 结构校验通过 → 开始生成 Word。（深度诊断仅供参考，不影响出稿）")
        print("=" * 64)

    with open(args.md, "r", encoding="utf-8") as f:
        md = f.read()
    md_body = re.sub(r"^---\n.*?\n---\n", "", md, flags=re.S)

    # ---- 脚注（2026-09-17 新增）----
    #   Markdown 约定：正文写 `……400 亿元[^1]，`，出处单独一行写 `[^1]: 来源, 页码`。
    #   定义行会被抽走（不进正文），引用处在渲染时打成独占 run 的占位符，
    #   存档后由 docx_footnote 装配成**真正的 Word 脚注**（页脚就地显示出处）。
    #   为什么值得专门做：官方提交规范把「引用须用脚注标明」列为硬项，
    #   而 python-docx 原生没有脚注 API —— 不做就只能用表格出处列凑，那是另一种东西。
    md_body, fn_defs = DOCX_FN.extract_definitions(md_body)
    FN = DOCX_FN.FootnoteState(fn_defs)
    _fn_refs = DOCX_FN.count_refs(md_body)

    # 交付稿须简体（SKILL 硬要求）—— 出稿前大声提醒（不阻拦，但必须知道）
    # 判据来自 `_common.TRAD_HINT`（原先各写一份、且两份已漂移：build_docx 少了 6 个字）
    _trad = set(TRAD_HINT)
    _hit = sorted({ch for ch in md_body if ch in _trad})
    if len(_hit) >= 15:
        print(f"{WARN} 交付稿疑似繁体（{len(_hit)} 种繁体字：{'、'.join(_hit[:12])}…）")
        print(f"{WARN} SKILL 要求对外交付稿用**简体**；请先本地化再交付。")

    doc = Document()
    # 页面设定
    for section in doc.sections:
        section.top_margin = Cm(2.5); section.bottom_margin = Cm(2.2)
        section.left_margin = Cm(2.6); section.right_margin = Cm(2.6)
        add_page_number_footer(section)

    # 预设样式字体
    normal = doc.styles["Normal"]
    normal.font.name = CN_FONT
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)

    # ---- 封面（--no-cover 可省约 1 页）----
    if args.no_cover:
        # 不生成封面页：标题直接做首行
        p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(args.title); set_run_font(r, size=17, bold=True)
        meta = " ｜ ".join(x for x in [args.subtitle, args.date] if x)
        if meta:
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(meta); set_run_font(r, size=10, color=RGBColor(0x55, 0x55, 0x55))
    else:
        for _ in range(4):
            doc.add_paragraph()
        p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(args.title); set_run_font(r, size=24, bold=True)
        if args.subtitle:
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(args.subtitle); set_run_font(r, size=14, color=RGBColor(0x44, 0x44, 0x44))
        for _ in range(6):
            doc.add_paragraph()
        if args.date:
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(args.date); set_run_font(r, size=12)
        if args.author:
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(args.author); set_run_font(r, size=12)

    # ---- 目录（--no-toc 可省约 1 页；5 页以内的小文档建议省掉）----
    headings = []
    for ln in md_body.splitlines():
        m = re.match(r"^(#{1,3})\s+(.*)$", ln.strip())
        if m:
            headings.append((len(m.group(1)), strip_inline(m.group(2)).strip()))
    if not args.no_toc:
        doc.add_page_break()
        h = doc.add_heading(level=1); r = h.add_run("目录"); set_run_font(r, size=18, bold=True)
        for lvl, text in headings:
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.5 * (lvl - 1))
            p.paragraph_format.space_after = Pt(2)
            r = p.add_run(text); set_run_font(r, size=10.5 if lvl > 1 else 11.5, bold=(lvl == 1))
        doc.add_page_break()

    # ---- 正文 ----
    doc.add_page_break()
    render_markdown(doc, md_body, FN)

    # ---- 保存 ----
    out = args.output
    if not out.lower().endswith(".docx"):
        out += ".docx"
    _dir = os.path.dirname(os.path.abspath(out))
    os.makedirs(_dir, exist_ok=True)   # 输出目录不存在时自动建立（旧版会直接抛错）
    doc.save(out)

    # ---- 脚注装配（存档后改写 zip：footnotes.xml ＋ 引用 run）----
    if FN.order:
        _items = [(i + 1, FN.text_of(l)) for i, l in enumerate(FN.order)]
        _n = DOCX_FN.install_footnotes(out, _items)
        _miss = [l for l in FN.order if l not in fn_defs]
        # ⚠️ 分母要用「正文引用**处数**」而不是「脚注**条数**」：同一条脚注可以引用多次
        #    （本测试里 2 条脚注共 4 处引用），拿 2 当分母会误报「4/2 处成功」。
        if _fn_refs and _n != _fn_refs:
            _left = 0
            try:
                import zipfile as _zf
                with _zf.ZipFile(out) as _z:
                    _left = len(re.findall(r"\[\^[^\]]+\]",
                                          _z.read("word/document.xml").decode("utf-8")))
            except Exception as _e:
                # ⛔ 不许静默：这段的唯一职责就是「查正文有没有残留标记」，
                #    它自己失败还不出声，等于这层安全网从没装上。
                print(f"{WARN} 残留标记扫描失败（{type(_e).__name__}）—— 请手工确认正文无 [^n] 字面残留")
            print(f"{WARN} 脚注定位：{_n}/{_fn_refs} 处引用成功"
                  + (f"，正文残留 {_left} 处字面 `[^n]` 标记" if _left else "")
                  + " —— 有渲染路径漏了脚注处理，请检查")
        if _miss:
            print(f"{WARN} 有 {len(_miss)} 条引用没给出处（{'、'.join(_miss[:6])}）"
                  f"—— 已写成「（未给出处：…）」供人工补")
    elif _fn_refs:
        print(f"{WARN} 正文有 {_fn_refs} 处脚注引用，但渲染时没抓到 —— 请检查是否写在表格/标题里")

    size_kb = os.path.getsize(out) / 1024
    print(f"{OK} 已生成：{out}（{size_kb:.0f} KB）")
    print(f"   · 封面 + 目录 + 正文 + 页码 + 表格样式")
    if FN.order:
        print(f"   · 脚注 {len(FN.order)} 条（Word 页脚就地显示出处，非文末来源表）")
    print(f"   · 正文共 {len(headings)} 个标题节点")
    print(f"   · 提醒：目录为手工生成，内容有改动时请重新生成本档（Word 不会自动更新）")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{WARN} 已中断（Ctrl+C），未产生输出档。")
        sys.exit(130)
    except Exception as e:
        print(f"\n{NG} 脚本执行出错：{type(e).__name__}: {e}")
        print("→ 依协议 8（卡死处理）：")
        print("   1) 依上面讯息修正后重跑；")
        print("   2) 若属环境问题（缺 python-docx／无写入权限），改用 Markdown 协议出稿，不要卡在这里；")
        print("   3) 或加 --force 跳过校验（交付时须声明未校验）。")
        sys.exit(2)
