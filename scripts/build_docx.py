#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 Word 交付稿 · build_docx.py  （marketing-playbook 第 5 步）

用途：把方案 Markdown 轉成帶封面、目錄、頁碼、表格樣式的 .docx。
      **前置強制**：先跑 selfcheck.py，不通過就拒絕生成 —— 交付物只能由本腳本產出，
      所以「拿不到 .docx」＝ 沒完成，AI 繞不過校驗。

用法：
    python build_docx.py plan.md -o 方案.docx --title "某品牌校園營銷方案"
    python build_docx.py plan.md -o out.docx --title "X" --subtitle "副標題" --date 2026-09-14
    python build_docx.py plan.md -o out.docx --title "X" --skip-check   # 僅內部預覽用（會大聲警告）

依賴：python-docx（pip install python-docx）
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
    print("❌ 缺少 python-docx。請先安裝：pip install python-docx")
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import docx_footnote as DOCX_FN   # noqa: E402  Word 腳註裝配器（python-docx 原生不支援）

CN_FONT = "微軟雅黑"
from _common import OK, NG, WARN, HINT, INFO   # noqa: E402  统一符号，不要在各自文件里重定义


# ---------- 字體與頁碼工具 ----------

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
    """在頁腳插入「第 X 頁」域"""
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
    r2 = p.add_run(" 頁")
    set_run_font(r2, size=9)


def shade(cell, hexcolor="F2F2F2"):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hexcolor)
    tcPr.append(shd)


# ---------- Markdown 解析（夠用即可） ----------

def strip_inline(s):
    """去掉行內標記（Word 裡不該出現 Markdown 符號）。

    舊版只去 **粗體**，於是 composer 注入的 `cases/xx.md` 反引號、*斜體*、[連結](url)
    會原樣留在 .docx 裡 —— 客戶看到一堆 `` ` ``。這裡一次清乾淨。
    """
    s = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", s)               # ![alt](圖片) → alt 文字（Word 無圖）
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)                       # **粗體**
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", s)          # *斜體*
    s = re.sub(r"`([^`]+)`", r"\1", s)                            # `行內碼`
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)                # [文字](連結)
    s = s.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")  # HTML 換行
    return s


def add_text_runs(p, text, size=10.5, fn=None, bold_all=False, color=None):
    """把一段行內文字渲染成 runs —— 同時處理 `**粗體**` 與 `[^label]` **真實腳註**。

    為什麼要獨立出這個函式：腳註引用必須**獨占一個 run**，才能被 docx_footnote
    準確地換成 `<w:footnoteReference/>`；如果和上下文擠在同一個 run 裡，
    就只能靠拆 XML 猜邊界，必錯。所以這裡先按 `[^…]` 切段，每段腳註單獨出一個 run。
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
        # 分隔行：整行只由 - : 空白組成，且至少有一個 "-"（否則全空行會被誤刪）
        if all(re.match(r"^[-:\s]*$", c) for c in cells) and any("-" in c for c in cells):
            continue
        rows.append(cells)
    return rows


def render_markdown(doc, md_text, fn=None):
    """把 Markdown 渲染進 docx，回傳收集到的標題（給目錄用）

    `fn` = docx_footnote.FootnoteState；傳入即啟用**真腳註**渲染。
    """
    headings = []
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()

        # 圍欄程式碼塊 ``` … ```（舊版未識別 → 把 ``` 和塊內內容當普通文字，甚至把塊內 | 行當表格）
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
                i += 1  # 跳過結尾 ```
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
                          f"寬表在 Word 會擠成一條豎線；建議改多段文字或拆表。")
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

        # 標題
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            level = len(m.group(1))
            text = strip_inline(m.group(2)).strip()
            text = re.sub(r"\[\^[^\]]+\]", "", text)   # 標題裡的腳註標記直接去掉（標題不需要出處）
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
            # ⚠️ 這裡原本是 `p.add_run(strip_inline(...))` —— 繞過了 add_text_runs，
            #    導致**引用塊裡的 `[^n]` 不會變成腳註**，而是以字面 `[^3]` 留在正文裡
            #    （實測：3 條腳註只裝配出 2 條）。凡正文內容一律走 add_text_runs。
            add_text_runs(p, strip_inline(s.lstrip("> ").strip()), size=9.5, fn=fn,
                          color=RGBColor(0x60, 0x60, 0x60))
            i += 1
            continue

        # 分隔線
        if re.match(r"^-{3,}$", s):
            i += 1
            continue

        # 列表
        m_list = re.match(r"^(\s*)([-*]|\d+[.、)])\s+(.*)$", ln)
        if m_list:
            indent, marker, text = len(m_list.group(1)), m_list.group(2), m_list.group(3)
            # ⚠️ 2026-09-17 修正：原先把**所有**列表項的標記一律換成「・」，
            #    導致有序列表的編號（1. 2. 3.…）全部丟失 —— 打法/步驟類內容
            #    在 Word 裡變成一串沒有序號的圓點段落，用戶實測反饋「看起來像表格生成壞了」。
            #    修正：有序列表保留原始編號，僅無序列表用「・」。
            if marker[0].isdigit():
                num = re.match(r"\d+", marker).group(0)
                body = num + ". " + text
            else:
                body = "・" + text
            p = add_paragraph_with_bold(doc, body, size=10.5, fn=fn)
            if indent >= 2:   # 嵌套列表：按縮進層級縮排（舊版一律壓平）
                p.paragraph_format.left_indent = Cm(0.5 * (indent // 2))
            elif marker[0].isdigit():   # 有序列表：懸掛縮排，數字與正文對齊
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
    ap = argparse.ArgumentParser(description="把方案 Markdown 轉成 Word 交付稿")
    ap.add_argument("md", help="方案 Markdown 檔路徑")
    ap.add_argument("-o", "--output", required=True, help="輸出 .docx 路徑")
    ap.add_argument("--title", required=True, help="封面主標題（項目名）")
    ap.add_argument("--subtitle", default="", help="封面副標題")
    ap.add_argument("--date", default="", help="封面日期")
    ap.add_argument("--author", default="", help="封面署名")
    ap.add_argument("--banned", default="", help="自訂禁用詞表 JSON")
    ap.add_argument("--rules", default="", help="《任務規則表》JSON —— **沒提供會拒絕出稿**（用來強制『先問用戶』）")
    ap.add_argument("--no-cover", action="store_true", help="不生成封面（省約 1 頁）—— 頁數緊張時用")
    ap.add_argument("--no-toc", action="store_true", help="不生成目錄（省約 1 頁）—— 5 頁以內的小文檔建議加上")
    ap.add_argument("--skip-check", action="store_true",
                    help="跳過自檢（僅內部預覽用）。行為同 --force，但語義是『預覽』；正式交付請用 --force 並聲明未校驗")
    ap.add_argument("--force", action="store_true",
                    help="緊急出口（協議 8）：跳過自檢強制生成。交付時必須聲明「本稿未通過校驗」並列出未通過項")
    args = ap.parse_args()

    # ---- 前置：跑 selfcheck ----
    # ── 硬前提：必須先有《任務規則表》＝ 先問過用戶要什麼結構／量級／字數 ──
    #    2026-09-14 用戶指出：AI 常常「不問就開跑」，門禁只覆蓋新項目、
    #    覆蓋不到「重新生成／改結構」這類任務。所以把「問用戶」變成機械前提：
    #    **拿不到規則表 → 出不了稿。**
    if not args.rules and not (args.force or args.skip_check):
        print("=" * 64)
        print(f"{NG} 拒絕出稿：未提供《任務規則表》（--rules）")
        print()
        print("這通常意味著：**你沒有先問過用戶**這三件事 ——")
        print("   ① 交付結構（**精煉版**：只放能執行的／**完整版**：含現狀分析）")
        print("   ② 內容量級（**摘要版** 1–2 頁／**標準版**／**完整版**）")
        print("   ③ 有沒有字數或頁數的硬要求")
        print()
        print("→ 做法：先跑 `gate_check.py` 產出《任務規則表》並請用戶確認，再出稿。")
        print("→ 若用戶已明確同意跳過，加 `--force`（交付時必須聲明未經門禁）。")
        print("=" * 64)
        sys.exit(1)
    if args.rules:
        if not os.path.exists(args.rules):
            print(f"{NG} 找不到《任務規則表》檔案：{args.rules}")
            sys.exit(1)
        print(f"{OK} 已提供《任務規則表》：{args.rules}")

    if args.skip_check or args.force:
        print("=" * 64)
        print(f"{WARN} 緊急出口：已跳過交付前自檢。")
        print(f"{WARN} 依協議 8，交付時你【必須】：")
        print("       ① 明確聲明「本稿未通過交付前校驗」")
        print("       ② 列出未校驗的項目")
        print("       ③ 不得聲稱已完成")
        print("       （建議先跑 selfcheck.py 看看到底卡在哪，再決定要不要跳）")
        print("=" * 64)
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        # ① 強制門檻：selfcheck（結構完整性 —— 缺章節、缺自檢單、內部文檔洩漏）
        checks = [
            ("交付前自檢 selfcheck.py",
             [sys.executable, os.path.join(here, "selfcheck.py"), args.md]
             + (["--banned", args.banned] if args.banned else [])),
        ]
        # ② 只報告、不設門檻：depth_check（要素厚薄 —— 用戶定調 2026-09-14：只提示不攔）
        advisory = [
            ("深度診斷 depth_check.py",
             [sys.executable, os.path.join(here, "depth_check.py"), args.md]),
        ]
        failed = []
        for name, cmd in checks:
            if not os.path.exists(cmd[1]):
                print(f"{WARN} 找不到 {cmd[1]}，跳過「{name}」（不阻塞出稿，但請留意）\n")
                continue
            print(f"→ 先跑{name} ...\n")
            if subprocess.call(cmd) != 0:
                failed.append(name)
            print()
        if failed:
            print("=" * 64)
            print(f"{NG} 結構校驗未通過 → 拒絕生成 .docx。未通過項：{'、'.join(failed)}")
            print("→ 修正後重跑；這是協議 3 的強制點。")
            print("→ 依協議 8：同一項連續 2 次不過就停止重試，把問題攤給用戶；")
            print("   或經用戶同意用 --force 出稿（交付時必須聲明未校驗）。")
            print("=" * 64)
            sys.exit(1)

        # 深度診斷：只印報告，**不阻攔出稿**
        for name, cmd in advisory:
            if os.path.exists(cmd[1]):
                print(f"→ 跑{name}（僅診斷，不阻攔出稿）...\n")
                subprocess.call(cmd)
                print()

        print("=" * 64)
        print(f"{OK} 結構校驗通過 → 開始生成 Word。（深度診斷僅供參考，不影響出稿）")
        print("=" * 64)

    with open(args.md, "r", encoding="utf-8") as f:
        md = f.read()
    md_body = re.sub(r"^---\n.*?\n---\n", "", md, flags=re.S)

    # ---- 腳註（2026-09-17 新增）----
    #   Markdown 約定：正文寫 `……400 億元[^1]，`，出處單獨一行寫 `[^1]: 來源, 頁碼`。
    #   定義行會被抽走（不進正文），引用處在渲染時打成獨占 run 的佔位符，
    #   存檔後由 docx_footnote 裝配成**真正的 Word 腳註**（頁腳就地顯示出處）。
    #   為什麼值得專門做：官方提交規範把「引用須用腳註標明」列為硬項，
    #   而 python-docx 原生沒有腳註 API —— 不做就只能用表格出處列湊，那是另一種東西。
    md_body, fn_defs = DOCX_FN.extract_definitions(md_body)
    FN = DOCX_FN.FootnoteState(fn_defs)
    _fn_refs = DOCX_FN.count_refs(md_body)

    # 交付稿須簡體（SKILL 硬要求）—— 出稿前大聲提醒（不阻攔，但必須知道）
    _trad = set("們個這說對產麼無為與於還進來過學經銷廣價範實樣觀點圍優質讓覺聲話術確認據應該務專態勢將團隊費責機構營運畫計劃達標類數據網絡歷總轉發構則議權")
    _hit = sorted({ch for ch in md_body if ch in _trad})
    if len(_hit) >= 15:
        print(f"{WARN} 交付稿疑似繁體（{len(_hit)} 種繁體字：{'、'.join(_hit[:12])}…）")
        print(f"{WARN} SKILL 要求對外交付稿用**簡體**；請先本地化再交付。")

    doc = Document()
    # 頁面設定
    for section in doc.sections:
        section.top_margin = Cm(2.5); section.bottom_margin = Cm(2.2)
        section.left_margin = Cm(2.6); section.right_margin = Cm(2.6)
        add_page_number_footer(section)

    # 預設樣式字體
    normal = doc.styles["Normal"]
    normal.font.name = CN_FONT
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)

    # ---- 封面（--no-cover 可省約 1 頁）----
    if args.no_cover:
        # 不生成封面頁：標題直接做首行
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

    # ---- 目錄（--no-toc 可省約 1 頁；5 頁以內的小文檔建議省掉）----
    headings = []
    for ln in md_body.splitlines():
        m = re.match(r"^(#{1,3})\s+(.*)$", ln.strip())
        if m:
            headings.append((len(m.group(1)), strip_inline(m.group(2)).strip()))
    if not args.no_toc:
        doc.add_page_break()
        h = doc.add_heading(level=1); r = h.add_run("目錄"); set_run_font(r, size=18, bold=True)
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
    os.makedirs(_dir, exist_ok=True)   # 輸出目錄不存在時自動建立（舊版會直接拋錯）
    doc.save(out)

    # ---- 腳註裝配（存檔後改寫 zip：footnotes.xml ＋ 引用 run）----
    if FN.order:
        _items = [(i + 1, FN.text_of(l)) for i, l in enumerate(FN.order)]
        _n = DOCX_FN.install_footnotes(out, _items)
        _miss = [l for l in FN.order if l not in fn_defs]
        # ⚠️ 分母要用「正文引用**處數**」而不是「腳註**條數**」：同一條腳註可以引用多次
        #    （本測試裡 2 條腳註共 4 處引用），拿 2 當分母會誤報「4/2 處成功」。
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
            print(f"{WARN} 腳註定位：{_n}/{_fn_refs} 處引用成功"
                  + (f"，正文殘留 {_left} 處字面 `[^n]` 標記" if _left else "")
                  + " —— 有渲染路徑漏了腳註處理，請檢查")
        if _miss:
            print(f"{WARN} 有 {len(_miss)} 條引用沒給出處（{'、'.join(_miss[:6])}）"
                  f"—— 已寫成「（未给出处：…）」供人工補")
    elif _fn_refs:
        print(f"{WARN} 正文有 {_fn_refs} 處腳註引用，但渲染時沒抓到 —— 請檢查是否寫在表格/標題裡")

    size_kb = os.path.getsize(out) / 1024
    print(f"{OK} 已生成：{out}（{size_kb:.0f} KB）")
    print(f"   · 封面 + 目錄 + 正文 + 頁碼 + 表格樣式")
    if FN.order:
        print(f"   · 腳註 {len(FN.order)} 條（Word 頁腳就地顯示出處，非文末來源表）")
    print(f"   · 正文共 {len(headings)} 個標題節點")
    print(f"   · 提醒：目錄為手工生成，內容有改動時請重新生成本檔（Word 不會自動更新）")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{WARN} 已中斷（Ctrl+C），未產生輸出檔。")
        sys.exit(130)
    except Exception as e:
        print(f"\n{NG} 腳本執行出錯：{type(e).__name__}: {e}")
        print("→ 依協議 8（卡死處理）：")
        print("   1) 依上面訊息修正後重跑；")
        print("   2) 若屬環境問題（缺 python-docx／無寫入權限），改用 Markdown 協議出稿，不要卡在這裡；")
        print("   3) 或加 --force 跳過校驗（交付時須聲明未校驗）。")
        sys.exit(2)
