#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按格式范本重排 · reformat_to_template.py  （marketing-playbook 後置環節）

用途
----
客戶／比賽／招標常常自帶**提交格式范本**（章節清單、模板文件）。
本工具把已經生成的方案稿**按范本骨架重排**，同時**保證硬要素一件不丟**（協議 2：合併，不取捨）。

它做三件事：
    ① 解析范本骨架（.md / .txt / .docx 都行 —— docx 按 Heading 樣式取章節）
    ② 按映射把源稿章節填進范本對應位置（無映射時自動按標題相似度建議）
    ③ **硬要素核對**：確認重排後沒有丟失關鍵要素，並列出「范本要、但源稿沒有」的待補章節

用法
----
    # 1) 先看自動匹配建議（不寫檔）
    python scripts/reformat_to_template.py --source 方案.md --template 比賽提交清單.docx --dry-run

    # 2) 人工/AI 確認後，寫出映射表再重排
    python scripts/reformat_to_template.py --source 方案.md --template 範本.md \\
        --map 映射.json -o 方案-按範本.md --report 要素核對.md

映射表格式（章節標題 → 源稿章節標題列表；可為空 = 該節需新寫）
    {
      "一、項目背景": ["一 · 診斷"],
      "二、營銷策略": ["二 · 策略", "三 · 定位與口徑"],
      "三、執行計劃": ["四 · 觸達與渠道", "七 · 落地文案與物料"],
      "四、預算": ["九 · 預算明細與盈虧線"],
      "五、風險評估": ["十 · 執行與風控"],
      "六、附錄": []
    }

退出碼：0 = 成功；1 = 有硬要素丟失（**應修正後重跑**）；2 = 環境/檔案問題
"""

import argparse
import difflib
import json
import os
import re
import sys

OK, NG, WARN, HINT = "✅", "❌", "⚠️", "→"

# 硬要素清單（協議 2 要求「一件不丟」的關鍵項）
KEY_ELEMENTS = {
    "執行摘要": r"TL;DR|執行摘要|执行摘要|核心結論卡|核心结论卡",
    "問題類型（A–H）": r"問題類型|问题类型",
    "卡點重構句（不是X——是Y）": r"不是[^\n]{0,60}(——|—|--)",
    "打法組合": r"\*\*打法\s*\d+|為什麼用它|为什么用它",
    "禁用詞與口徑": r"禁用詞|禁用词",
    "KPI 與預警線": r"KPI|預警線|预警线",
    "預算明細": r"預算明細|预算明细|預算表|预算表",
    "行動清單": r"行動清單|行动清单",
    "風險與兜底": r"兜底|風險清單|风险清单|模式\s*\d{1,2}",
    "關鍵假設": r"關鍵假設|关键假设|假設|假设",
    "交付自檢單": r"自檢單|自检单",
}


def read_text(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        try:
            from docx import Document
        except ImportError:
            print(f"{NG} 讀取 .docx 需要 python-docx：pip install python-docx")
            sys.exit(2)
        d = Document(path)
        out = []
        for p in d.paragraphs:
            txt = p.text.strip()
            if not txt:
                continue
            style = (p.style.name or "").lower()
            m = re.search(r"heading\s*(\d)", style)
            if m:
                out.append("#" * (int(m.group(1)) + 1) + " " + txt)
            else:
                out.append(txt)
        # 表格也取出來（范本里的清單常在表格）
        for t in d.tables:
            for row in t.rows:
                cells = [c.text.strip() for c in row.cells]
                if any(cells):
                    out.append("| " + " | ".join(cells) + " |")
        return "\n".join(out)
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


def split_sections(md: str, max_level: int = 3):
    """把 markdown 切成 [(標題, 內容), ...]（標題層級 ≤ max_level）"""
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


try:  # 可選：繁簡歸一化，讓自動匹配更準（沒有 opencc 就跳過）
    from opencc import OpenCC
    _S2T = None
    _T2S = OpenCC("t2s")
    def _fold(s: str) -> str:
        return _T2S.convert(s)
except Exception:
    def _fold(s: str) -> str:
        return s


def norm(s: str) -> str:
    """歸一化：去繁簡差異 + 去標點/序號/空白 → 只留可比對的字"""
    s = _fold(s)
    return re.sub(r"[\s·、，,。：:（）()\[\]【】一二三四五六七八九十\d\.\-—]+", "", s)


def suggest_map(src_titles, tpl_titles, threshold=0.34):
    """自動建議映射：范本章節 → 最相似的源稿章節（可多個）"""
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
    ap.add_argument("--map", dest="mapfile", help="章節映射 JSON")
    ap.add_argument("-o", "--out", help="輸出重排後的 .md")
    ap.add_argument("--report", help="輸出要素核對報告 .md")
    ap.add_argument("--dry-run", action="store_true", help="只打印建議映射，不寫檔")
    a = ap.parse_args()

    src = read_text(a.source)
    tpl = read_text(a.template)
    # 范本的第一個 H1 當「文檔標題」，不算章節
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
    print(f"  源稿：{a.source}（{len(src_secs)} 個章節）")
    print(f"  范本：{a.template}（{len(tpl_secs)} 個章節）")
    print("=" * 64)

    # ---------- 映射 ----------
    if a.mapfile and os.path.exists(a.mapfile):
        mapping = json.load(open(a.mapfile, encoding="utf-8"))
        print(f"\n{OK} 使用提供的映射表（{len(mapping)} 條）")
    else:
        mapping = suggest_map(src_titles, tpl_titles)
        print(f"\n{WARN} 未提供 --map → 以下是**自動建議**（請人工/AI 確認後寫成 JSON 再重排）：")
        for t, ss in mapping.items():
            print(f"   「{t}」  ←  {('、'.join(ss)) if ss else '（無匹配 → 需新寫）'}")

    if a.dry_run:
        print(f"\n{HINT} --dry-run：未寫檔。確認映射後：")
        print(f"    python scripts/reformat_to_template.py --source {a.source} "
              f"--template {a.template} --map 映射.json -o 方案-按範本.md")
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
                # 保留來源小節標題：① 可追溯「這段從哪來」② 保住要素關鍵詞（如「TL;DR」「禁用詞」）
                body_parts.append(f"### {s}\n\n{src_map[s]}"); used.add(s)
            else:
                print(f"   {WARN} 映射指向的源稿章節不存在：{s}")
        if body_parts:
            out_lines.append("\n\n".join(body_parts) + "\n")
        else:
            # 范本章節本身有內容（例如說明文字）就保留，否則標待補
            note = "【待補：範本此節需新寫內容 —— 來源稿中無對應章節】"
            out_lines.append((tpl_body + "\n\n" if tpl_body else "") + note + "\n")
            unfilled.append(t)
    # 未被用到的源稿章節 → 附錄（協議 2：不取捨，多的放附件）
    leftovers = [t for t in src_titles if t not in used]
    if leftovers:
        if len(leftovers) > len(src_titles) * 0.5:
            print(f"\n{WARN} 未被映射的章節達 {len(leftovers)}/{len(src_titles)}（超過一半）"
                  f"—— 請確認映射是否漏了（漏的會被整節塞進附錄，讀起來會散）")
        out_lines.append("## 附錄：範本未涵蓋、但原稿有的內容\n")
        out_lines.append(f"> 協議 2「合併，不取捨」：以下章節範本沒有對應位，整節移入附錄。\n")
        for t in leftovers:
            out_lines.append(f"### {t}\n")
            out_lines.append(src_map.get(t, "") + "\n")

    if tpl_title:
        out_lines.insert(0, f"# {tpl_title}\n")
    out_md = "\n".join(out_lines)

    # ---------- 硬要素核對 ----------
    src_el, out_el = check_elements(src), check_elements(out_md)
    lost = [k for k in KEY_ELEMENTS if src_el[k] and not out_el[k]]
    gained = [k for k in KEY_ELEMENTS if out_el[k] and not src_el[k]]

    print("\n" + "=" * 64)
    print("硬要素核對（協議 2：合併，不取捨）")
    for k in KEY_ELEMENTS:
        if src_el[k] and not out_el[k]:
            print(f"  {NG} 丟失：{k}")
        elif src_el[k]:
            print(f"  {OK} 保留：{k}")
    if unfilled:
        print(f"\n{WARN} 範本有 {len(unfilled)} 節源稿無法填（需新寫）：")
        for t in unfilled:
            print(f"   · {t}")
    if leftovers:
        print(f"\n{OK} 源稿有 {len(leftovers)} 節範本沒對應位 → 已整節移入附錄（未丟）")

    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(out_md)
        print(f"\n{OK} 已寫出：{a.out}（{len(out_md.splitlines())} 行）")
    if a.report:
        rep = ["# 格式范本重排 · 要素核對報告", "",
               f"- 源稿：`{a.source}`（{len(src_secs)} 節）",
               f"- 范本：`{a.template}`（{len(tpl_secs)} 節）", "",
               "## 硬要素核對", ""]
        for k in KEY_ELEMENTS:
            mark = NG if (src_el[k] and not out_el[k]) else (OK if src_el[k] else "—")
            rep.append(f"- {mark} {k}")
        rep += ["", "## 範本要、源稿沒有（需新寫）", ""]
        rep += [f"- {t}" for t in unfilled] or ["- （無）"]
        rep += ["", "## 源稿有、範本沒對應位（已移入附錄）", ""]
        rep += [f"- {t}" for t in leftovers] or ["- （無）"]
        with open(a.report, "w", encoding="utf-8") as f:
            f.write("\n".join(rep))
        print(f"{OK} 已寫出核對報告：{a.report}")

    print("=" * 64)
    print(f"{HINT} 下一步：對重排後的 .md 跑唯一出稿入口")
    print(f"    python scripts/run_pipeline.py --rules rules.json --plan {a.out or '方案-按範本.md'} "
          f"-o 方案-按範本.docx --title \"客戶名 營銷方案\"")
    if lost:
        print(f"\n{NG} 有 {len(lost)} 項硬要素丟失 —— **先補齊再出稿**（協議 2）。")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ 已中斷。")
        sys.exit(130)
    except Exception as e:  # pragma: no cover
        print(f"\n{NG} 執行出錯：{type(e).__name__}: {e}")
        sys.exit(2)
