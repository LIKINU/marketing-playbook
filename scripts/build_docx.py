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

CN_FONT = "微軟雅黑"
OK, NG, WARN = "✅", "❌", "⚠️"


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
    """去掉行內標記，回傳 (純文字, 是否粗體段列表)。這裡做簡單處理：**x** → 粗體"""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", s)


def add_paragraph_with_bold(doc, text, size=10.5, style=None):
    p = doc.add_paragraph(style=style)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.25
    parts = re.split(r"(\*\*.+?\*\*)", text)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            r = p.add_run(part[2:-2]); set_run_font(r, size=size, bold=True)
        else:
            r = p.add_run(part); set_run_font(r, size=size)
    return p


def parse_table_block(block_lines):
    rows = []
    for ln in block_lines:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(re.match(r"^[-:\s]*$", c) for c in cells):
            continue  # 分隔行
        rows.append(cells)
    return rows


def render_markdown(doc, md_text):
    """把 Markdown 渲染進 docx，回傳收集到的標題（給目錄用）"""
    headings = []
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()

        # 表格
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[-:\s|]+\|$", lines[i + 1].strip()):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i]); i += 1
            rows = parse_table_block(block)
            if rows:
                ncol = max(len(r) for r in rows)
                t = doc.add_table(rows=0, cols=ncol)
                t.style = "Table Grid"
                for ri, row in enumerate(rows):
                    cells = t.add_row().cells
                    for ci in range(ncol):
                        val = row[ci] if ci < len(row) else ""
                        cells[ci].text = ""
                        para = cells[ci].paragraphs[0]
                        r = para.add_run(strip_inline(val))
                        set_run_font(r, size=9, bold=(ri == 0))
                        if ri == 0:
                            shade(cells[ci])
                doc.add_paragraph()
            continue

        # 標題
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            level = len(m.group(1))
            text = strip_inline(m.group(2)).strip()
            if level <= 3:
                h = doc.add_heading(level=min(level, 3))
                r = h.add_run(text)
                set_run_font(r, size={1: 18, 2: 14, 3: 12}.get(level, 11), bold=True,
                             color=RGBColor(0x1F, 0x1F, 0x1F))
                headings.append((level, text))
            else:
                add_paragraph_with_bold(doc, f"■ {text}", size=10.5)
                headings.append((4, text))
            i += 1
            continue

        # 引用
        if s.startswith(">"):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.6)
            r = p.add_run(strip_inline(s.lstrip("> ").strip()))
            set_run_font(r, size=9.5, color=RGBColor(0x60, 0x60, 0x60))
            i += 1
            continue

        # 分隔線
        if re.match(r"^-{3,}$", s):
            i += 1
            continue

        # 列表
        if re.match(r"^[-*]\s+", s) or re.match(r"^\d+[.、)]\s+", s):
            text = re.sub(r"^[-*]\s+|^\d+[.、)]\s+", "", s)
            add_paragraph_with_bold(doc, "・" + text, size=10.5)
            i += 1
            continue

        # 空行
        if not s:
            i += 1
            continue

        # 一般段落
        add_paragraph_with_bold(doc, s, size=10.5)
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
    ap.add_argument("--skip-check", action="store_true", help="跳過自檢（僅內部預覽，不建議）")
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

    # ---- 封面 ----
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

    # ---- 目錄（手工生成，不用域，避免打開時空白） ----
    doc.add_page_break()
    h = doc.add_heading(level=1); r = h.add_run("目錄"); set_run_font(r, size=18, bold=True)
    tmp_doc = Document()  # 先掃一遍拿標題
    headings = []
    for ln in md_body.splitlines():
        m = re.match(r"^(#{1,3})\s+(.*)$", ln.strip())
        if m:
            headings.append((len(m.group(1)), strip_inline(m.group(2)).strip()))
    for lvl, text in headings:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.5 * (lvl - 1))
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(text); set_run_font(r, size=10.5 if lvl > 1 else 11.5, bold=(lvl == 1))

    # ---- 正文 ----
    doc.add_page_break()
    render_markdown(doc, md_body)

    # ---- 保存 ----
    out = args.output
    if not out.lower().endswith(".docx"):
        out += ".docx"
    doc.save(out)
    size_kb = os.path.getsize(out) / 1024
    print(f"{OK} 已生成：{out}（{size_kb:.0f} KB）")
    print(f"   · 封面 + 目錄 + 正文 + 頁碼 + 表格樣式")
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
