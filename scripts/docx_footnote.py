#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docx_footnote.py — 給 python-docx 產出的 .docx 加**真正的 Word 脚注**

為什麼需要它（2026-09-17）：
    官方提交规范里有一条硬项：「引用论文/研究报告/书籍需用**脚注**标明」。
    而 python-docx **原生不支持脚注** —— 没有 API、没有样式、没有 part。
    于是交付稿只能把出处塞进表格的一列、再在文末附一张来源清单，
    那是「参考文献表」的写法，不是脚注；评审要核实某个数字得来回翻页。

本模块怎么绕过去：
    python-docx 写完后，直接操作 .docx（本质是个 zip）：
      1) 正文里每个脚注位置，先由调用方渲染成一个**独占一个 run 的占位符**；
      2) 本模块把该 run 换成 `<w:footnoteReference w:id="N"/>`；
      3) 新建 `word/footnotes.xml`（含 separator / continuationSeparator ＋ 每条脚注正文）；
      4) 补 `[Content_Types].xml` 的 Override 与 `word/_rels/document.xml.rels` 的关系项。

    ⚠️ 刻意**不依赖 `FootnoteReference` / `FootnoteText` 样式**：那些样式在 python-docx
       的默认模板里不存在，引用不存在的 rStyle 会被 Word 判为文档损坏或直接忽略。
       所以这里用「直接格式」：上标用 `<w:vertAlign w:val="superscript"/>`，
       脚注正文用小字号 `<w:sz w:val="18"/>`（9pt）。不依赖任何样式 = 不依赖模板。

Markdown 侧的约定（与 build_docx 一致）：
    正文引用：`……大盘约 400 亿元[^1]，……`
    出处定义：单独一行 `[^1]: 弗若斯特沙利文《中国眼部护理白皮书》2025, p.12`
              定义行**不会**出现在正文里（会被抽走）。

用法：
    python scripts/docx_footnote.py 方案.docx --list      # 看这份 docx 里有多少条真脚注
    python scripts/docx_footnote.py 方案.docx --verify    # 校验 OOXML 装配是否完整（退出码非 0＝有问题）
"""
import argparse
import os
import re
import shutil
import sys
import zipfile

NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_FOOTNOTES = ("http://schemas.openxmlformats.org/officeDocument/2006/"
                 "relationships/footnotes")
CT_FOOTNOTES = ("application/vnd.openxmlformats-officedocument."
                "wordprocessingml.footnotes+xml")

# 占位符：用私用區字元包住，正常文本裡不可能出現，且不會被 strip_inline 動到
PH_L = "\ue000FN"
PH_R = "FN\ue001"


def placeholder(fid):
    return f"{PH_L}{fid}{PH_R}"


def extract_definitions(md_text):
    """從 Markdown 裡抽走 `[^label]: 出處` 定義行。

    回傳 (去掉定義行的 markdown, {label: 出處文本})。
    """
    defs = {}
    keep = []
    for ln in md_text.split("\n"):
        m = re.match(r"^\s*\[\^([^\]]+)\]:\s*(.+?)\s*$", ln)
        if m:
            defs[m.group(1)] = m.group(2)
            continue
        keep.append(ln)
    return "\n".join(keep), defs


def count_refs(md_text):
    """數正文裡出現的引用標記（不含定義行）"""
    body, _ = extract_definitions(md_text)
    return len(re.findall(r"\[\^([^\]]+)\](?!:)", body))


# ─────────────────────────────────────────────────────────────
# 渲染側：把一段文字拆成「普通 run / 粗體 run / 腳註 run 佔位」
# ─────────────────────────────────────────────────────────────

class FootnoteState:
    """渲染過程中累積「標籤 → 序號」，序號即 Word 腳注 id。"""

    def __init__(self, defs=None):
        self.defs = defs or {}
        self.order = []          # [label, ...] 按正文出現順序
        self._ids = {}

    def fid(self, label):
        if label not in self._ids:
            self.order.append(label)
            self._ids[label] = len(self.order)      # 1-based；0 留給 continuationSeparator
        return self._ids[label]

    def text_of(self, label):
        t = self.defs.get(label)
        if t is None:
            # 有引用没定义 —— 不静默吞掉：留一句可核对的提示，同时由 selfcheck 侧报告
            return f"（未给出处：{label}）"
        return t


# ─────────────────────────────────────────────────────────────
# OOXML 裝配
# ─────────────────────────────────────────────────────────────

def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def footnote_ref_run(fid, size_half_pt="21"):
    return (f'<w:r><w:rPr><w:vertAlign w:val="superscript"/>'
            f'<w:sz w:val="{size_half_pt}"/></w:rPr>'
            f'<w:footnoteReference w:id="{fid}"/></w:r>')


def build_footnotes_xml(items):
    """items = [(fid, text), ...]，fid 從 1 起。"""
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             f'<w:footnotes xmlns:w="{NS_W}">',
             '<w:footnote w:type="separator" w:id="-1"><w:p><w:pPr>'
             '<w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>'
             '<w:r><w:separator/></w:r></w:p></w:footnote>',
             '<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:pPr>'
             '<w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>'
             '<w:r><w:continuationSeparator/></w:r></w:p></w:footnote>']
    for fid, text in items:
        parts.append(
            f'<w:footnote w:id="{fid}"><w:p>'
            f'<w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>'
            f'<w:r><w:rPr><w:vertAlign w:val="superscript"/><w:sz w:val="18"/></w:rPr>'
            f'<w:footnoteRef/></w:r>'
            f'<w:r><w:rPr><w:sz w:val="18"/></w:rPr>'
            f'<w:t xml:space="preserve"> {_esc(text)}</w:t></w:r>'
            f'</w:p></w:footnote>')
    parts.append('</w:footnotes>')
    return "".join(parts)


RUN_RE = re.compile(r"<w:r(?:\s[^>]*)?>.*?</w:r>", re.S)


def install_footnotes(docx_path, items, verbose=True):
    """把 items=[(fid, text), ...] 裝進 docx_path（就地改寫）。回傳替換掉的位置數。"""
    if not items:
        return 0
    tmp = docx_path + ".tmp"
    replaced = 0
    with zipfile.ZipFile(docx_path, "r") as zin:
        names = zin.namelist()
        data = {n: zin.read(n) for n in names}

    # ① document.xml：占位 run → footnoteReference run
    doc_xml = data["word/document.xml"].decode("utf-8")
    by_id = {fid: txt for fid, txt in items}

    def _sw(m):
        nonlocal replaced
        chunk = m.group(0)
        mm = re.search(re.escape(PH_L) + r"(\d+)" + re.escape(PH_R), chunk)
        if not mm:
            return chunk
        fid = int(mm.group(1))
        if fid not in by_id:
            return chunk
        replaced += 1
        return footnote_ref_run(fid)

    doc_xml = RUN_RE.sub(_sw, doc_xml)
    data["word/document.xml"] = doc_xml.encode("utf-8")

    # ② 新增 footnotes.xml
    data["word/footnotes.xml"] = build_footnotes_xml(items).encode("utf-8")

    # ③ [Content_Types].xml 補 Override
    ct = data["[Content_Types].xml"].decode("utf-8")
    if "/word/footnotes.xml" not in ct:
        ct = ct.replace("</Types>",
                        f'<Override PartName="/word/footnotes.xml" '
                        f'ContentType="{CT_FOOTNOTES}"/></Types>')
        data["[Content_Types].xml"] = ct.encode("utf-8")

    # ④ document.xml.rels 補關係
    rels_name = "word/_rels/document.xml.rels"
    rels = data[rels_name].decode("utf-8")
    if "footnotes.xml" not in rels:
        used = set(re.findall(r'Id="rId(\d+)"', rels))
        n = 1
        while str(n) in used:
            n += 1
        rels = rels.replace("</Relationships>",
                            f'<Relationship Id="rId{n}" Type="{REL_FOOTNOTES}" '
                            f'Target="footnotes.xml"/></Relationships>')
        data[rels_name] = rels.encode("utf-8")

    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in names:
            zout.writestr(n, data[n])
        for extra in ("word/footnotes.xml", "[Content_Types].xml", rels_name):
            if extra not in names:
                zout.writestr(extra, data[extra])
    os.replace(tmp, docx_path)
    if verbose:
        print(f"   · 已注入 {len(items)} 条脚注（{replaced} 处引用定位成功）")
    return replaced


# ─────────────────────────────────────────────────────────────
# 校驗 / 檢視
# ─────────────────────────────────────────────────────────────

def inspect(docx_path):
    """回傳 {has_part, has_ct, has_rel, refs, texts, placeholder_left}"""
    out = {"has_part": False, "has_ct": False, "has_rel": False,
           "refs": 0, "texts": [], "placeholder_left": 0}
    with zipfile.ZipFile(docx_path, "r") as z:
        names = z.namelist()
        out["has_part"] = "word/footnotes.xml" in names
        doc = z.read("word/document.xml").decode("utf-8")
        out["refs"] = len(re.findall(r"<w:footnoteReference\b", doc))
        out["placeholder_left"] = len(re.findall(re.escape(PH_L), doc))
        ct = z.read("[Content_Types].xml").decode("utf-8")
        out["has_ct"] = "footnotes+xml" in ct
        try:
            rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
            out["has_rel"] = "footnotes.xml" in rels
        except KeyError:
            # 缺 rels ＝ 装配必不完整，不能在 verify 里静默成 False 就完事
            out["rels_missing"] = True
        if out["has_part"]:
            fx = z.read("word/footnotes.xml").decode("utf-8")
            out["texts"] = re.findall(r"<w:footnote w:id=\"(\d+)\">(.*?)</w:footnote>",
                                      fx, re.S)
    return out


def main():
    ap = argparse.ArgumentParser(description="檢視／校驗 .docx 里的 Word 脚注装配")
    ap.add_argument("docx")
    ap.add_argument("--list", action="store_true", help="列出每條脚注")
    ap.add_argument("--verify", action="store_true", help="校驗 OOXML 装配完整性")
    a = ap.parse_args()
    if not os.path.exists(a.docx):
        print(f"❌ 找不到 {a.docx}")
        sys.exit(2)
    r = inspect(a.docx)
    print(f"檔案：{os.path.basename(a.docx)}")
    print(f"  footnotes.xml part ：{'✅' if r['has_part'] else '❌'}")
    print(f"  Content_Types 聲明 ：{'✅' if r['has_ct'] else '❌'}")
    print(f"  document.rels 關係 ：{'✅' if r['has_rel'] else '❌'}")
    print(f"  正文引用數         ：{r['refs']}")
    print(f"  殘留佔位符         ：{r['placeholder_left']}"
          + ("　⚠️ 有未替換的佔位符＝裝配沒走完" if r['placeholder_left'] else ""))
    if a.list:
        for fid, body in r["texts"]:
            txt = " ".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", body, re.S))
            print(f"    [{fid}] {txt[:110]}")
    ok = (r["has_part"] and r["has_ct"] and r["has_rel"]
          and r["placeholder_left"] == 0
          and (r["refs"] > 0 or not r["has_part"]))
    print("  → " + ("✅ 裝配完整" if ok else "❌ 裝配不完整"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"{WARN} 已中断。")
        sys.exit(130)
    except Exception as e:
        # 协议 8：脚本挂了要能降级继续，不能让执行 AI 卡在裸 traceback 上。
        print(f"{NG} 執行出錯：{type(e).__name__}: {e}")
        print(f"{HINT} 依協議 8：修正後重跑；環境問題就改用 Markdown 協議手工完成，不要卡在這裡。")
        sys.exit(2)
