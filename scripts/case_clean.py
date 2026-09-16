#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
案例卡清理 · case_clean.py —— 按「子句」剔除公司背景，保留營銷結果

背景（2026-09-16）：SKILL「案例集硬規則」禁止公司背景（創始人／成立年份／股權／融資／營收／財報／估值／人事），
但庫裡有 2316 處違規。**不能整行刪** —— 因為同一行常同時含「財報數字（該刪）」與
「營銷結果（該留，如銷量第一／市佔率／播放量）」。故本工具**按子句**處理。

保護（不碰）：
  - 46–50 機構／書籍／出版物類（規則豁免）
  - 行首 `>`（引用／說明）與 `|`（表格）行 —— 避免破壞結構與可信度圖例
  - 含「可信度」的行（如「【已核實】財報／官方公告可查」——這裡的「財報」是來源類型，非公司背景）
  - 檔案前 12 行（標題＋圖例）

用法：
    python scripts/case_clean.py --dry-run  references/cases/39-*.md   # 只看會刪什麼
    python scripts/case_clean.py --apply                                # 全庫 01–45 應用
退出碼：0 正常；1 未變更（dry-run 無命中時）；2 出錯
"""

import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
EXEMPT_MIN = 46

# 身份／股權類 —— 與營銷無關且無歧義，可安全自動刪（--scope identity）
IDENTITY = ["創始人", "创始人", "創辦人", "创办人", "成立於", "成立于",
            "股權", "股权", "融資", "融资", "估值", "董事長", "董事长",
            "CEO", "裁員", "裁员", "IPO", "上市首日", "招股書", "招股书"]

# 財務類 —— 常與「營銷結果」黏在同一行（如「線下渠道收入 X 億、線上只有 Y 億」），
# 自動刪會把句子改爛 → 預設不動，需逐卡人工改寫（--scope finance 才碰，且務必複核）
FINANCE = ["營收", "营收", "財報", "财报", "淨利", "净利", "歸母", "归母", "扣非",
           "利潤", "利润", "毛利率", "淨利率", "净利率", "收入", "市值", "市盈率",
           "EPS", "股價", "股价", "負債", "负债", "現金流", "现金流",
           "增發", "增发", "營業額", "营业额"]

FORBID = IDENTITY + FINANCE

# 含這些標記的子句＝「營銷結果」→ 即使帶財報詞也保留（該留的是營銷結果）
KEEP_MARK = ["銷量", "销量", "市佔", "市占", "曝光", "播放", "熱搜", "热搜", "門店", "门店",
             "復購", "复购", "客流", "下載", "下载", "DAU", "MAU", "用戶數", "用户数",
             "粉絲", "粉丝", "客單", "客单", "轉化", "转化", "留存", "好評", "好评",
             "榜", "GMV", "排名", "進店", "进店", "到店", "互動", "互动", "點讚", "点赞"]

# 子句分隔：中英文標點（保留分隔符在子句尾，這樣刪掉子句時分隔符一起消失）
SPLIT = re.compile(r"(?<=[、，；;。])")
# 行首標籤前綴（- **結果**： / 1. / **X**： …）—— 清理後要接回去
_M_MARK = re.compile(r"^\s*(?:[-*+]\s*|\d+[.、]\s*)")
_M_LABEL = re.compile(r"^(\*\*[^*\n]{1,40}\*\*)\s*[:：]?\s*")
def _prefix(ln):
    m = _M_MARK.match(ln)
    head = m.group(0) if m else ""
    m2 = _M_LABEL.match(ln[len(head):])
    return head + (m2.group(0) if m2 else "")


def clean_line(ln, forbid=None):
    forbid = forbid if forbid is not None else IDENTITY
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
        if has_bg and not has_mkt:      # 只刪「純背景／財報」子句；帶營銷結果的保留
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
    while out.count("**") % 2:      # 修補被刪掉一半的粗體
        i = out.rfind("**")
        out = out[:i] + out[i+2:]
    out = re.sub(r"\*\*\s*$", "", out)
    if not out.strip():
        return None, dropped          # 整行都是背景 → 整行刪
    cand = prefix + out
    if _looks_broken(ln, cand):       # 改爛了 → 回退整行（寧可留著，也不毀句子）
        return ln, 0
    return cand, dropped


DANGLE = ("只有", "但", "而", "即", "且", "也", "均", "以及", "同比", "環比", "环比",
          "其中", "較上年", "较上年", "歸母", "归母", "淨利", "净利", "收入", "營收", "，", "、")


def _looks_broken(orig, new):
    """清理後若像「殘句」就整行回退 —— 財務子句常與營銷結果黏在一起，硬刪會毀句。"""
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
    if len(strip(orig)) >= 24 and len(strip(new)) < 0.4 * len(strip(orig)):
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
                    help="identity=只刪身世/股權（安全，預設）；finance=也刪財報數字（會改爛句子，需複核）；all=兩者")
    a = ap.parse_args()
    if not (a.dry_run or a.apply):
        a.dry_run = True

    files = a.paths or sorted(glob.glob(os.path.join(ROOT, "references", "cases", "*.md")))
    tot_d = tot_c = 0
    for f in files:
        base = os.path.basename(f)
        m = re.match(r"(\d+)", base)
        if m and int(m.group(1)) >= EXEMPT_MIN:
            continue
        d, c = process(f, a.apply, {"identity": IDENTITY, "finance": FINANCE, "all": FORBID}[a.scope])
        tot_d += d
        tot_c += c
        if d and a.dry_run:
            print(f"  {base}: 將刪 {d} 個子句 / 動 {c} 行")
    print("-" * 60)
    print(f"{'APPLY 完成' if a.apply else 'DRY-RUN'}：刪除子句 {tot_d}｜修改行 {tot_c}")
    sys.exit(0 if tot_d else 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 出錯：{type(e).__name__}: {e}")
        sys.exit(2)
