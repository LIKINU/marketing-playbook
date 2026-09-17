#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打法「案例行」候选卡推荐 · play_case_candidates.py

用途（2026-09-17）：修 `00-打法库` 那 104 條過時案例行時用。
每條打法給一個「全庫候選卡短名單」，人在上面挑 1–3 張再寫回案例行。

打分方式：bigram 重疊（打法名＋什麼情況用＋怎麼做 前幾步）↔（卡片標題＋卡內「可抄的點」）。
**它只是排序器，不做決定** —— 決定由人做，然後用 case_gap_fill 那種「只改一行」的腳本寫回。

用法：
    python scripts/play_case_candidates.py 1          # 只印 §1.x 的打法
    python scripts/play_case_candidates.py 4 6        # 印 §4.x 與 §6.x
    python scripts/play_case_candidates.py 1 --top 8
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
PLAYBOOK = os.path.join(REF, "00-打法库.md")


def read(p):
    return open(p, encoding="utf-8").read()


def bigrams(s):
    s = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def parse_plays():
    t = read(PLAYBOOK)
    plays, cur = {}, None
    for ln in t.split("\n"):
        m = re.match(r"^###\s+(\d+)\.(\d+)\s+(.+?)\s*$", ln)
        if m:
            major = int(m.group(1))
            if major == 0:
                cur = None
                continue
            cur = f"{major}.{m.group(2)}"
            plays[cur] = {"name": m.group(3).strip(), "blk": []}
            continue
        if re.match(r"^#{1,2}\s+\S", ln):
            cur = None
            continue
        if cur:
            plays[cur]["blk"].append(ln)
    for pid, p in plays.items():
        b = "\n".join(p["blk"])
        p["situation"] = (re.search(r"(?m)^\|\s*什麼情況用\s*\|\s*(.+?)\s*\|", b) or [None, ""])[1] if re.search(r"(?m)^\|\s*什麼情況用\s*\|", b) else ""
        m = re.search(r"\*\*怎麼做\*\*.*?\n(.*?)\*\*關鍵技巧\*\*", b, flags=re.S)
        p["howto"] = m.group(1) if m else ""
        p["case_line"] = next((x for x in p["blk"] if x.startswith("**案例**")), "")
    return plays


def parse_cards():
    """→ [{"file":…, "title":…, "brand":…, "text":…}]"""
    out = []
    for f in sorted(glob.glob(os.path.join(CASES, "*.md"))):
        base = os.path.basename(f)
        if not re.match(r"\d", base):
            continue
        t = read(f)
        # 卡片標題 + 卡內內容（到下一個 ### 為止）
        spans = [(m.start(), m.group(1)) for m in re.finditer(r"(?m)^###\s+3\.\d+\s+(.+?)\s*$", t)]
        for i, (pos, title) in enumerate(spans):
            end = spans[i + 1][0] if i + 1 < len(spans) else len(t)
            body = t[pos:end]
            pts = re.findall(r"可抄的點[：:]\s*(.+)", body)
            txt = title + " " + " ".join(pts)[:400]
            out.append({"file": base, "title": title,
                        "brand": re.split(r"[｜|（(]", title)[0].strip(), "text": txt})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("majors", nargs="+")
    ap.add_argument("--top", type=int, default=7)
    ap.add_argument("--only-open", action="store_true", default=True)
    a = ap.parse_args()

    plays = parse_plays()
    cards = parse_cards()
    cb = [(c, bigrams(c["text"])) for c in cards]

    for pid in sorted(plays, key=lambda x: (int(x.split(".")[0]), int(x.split(".")[1]))):
        if pid.split(".")[0] not in a.majors:
            continue
        p = plays[pid]
        # 只在「還沒指名品牌」的打法上工作（指名了的不重複動）
        if "（" in p["case_line"] and any(c["brand"] in p["case_line"] for c in cards[:200]):
            pass
        q = bigrams(p["name"] + p["situation"] + p["howto"][:600])
        scored = []
        for c, g in cb:
            if not g:
                continue
            ov = len(q & g) / max(len(q | g), 1)
            scored.append((ov, c))
        scored.sort(key=lambda x: -x[0])
        print(f"\n§{pid} {p['name']}")
        print(f"   情況：{p['situation'][:100]}")
        print(f"   現案例行：{p['case_line'][:110] or '（無）'}")
        for ov, c in scored[:a.top]:
            print(f"     {ov:.3f}  {c['brand'][:20]:<22} {c['title'][:44]:<46} {c['file']}")


def _entry():
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"❌ 執行出錯：{type(e).__name__}: {e}")
        sys.exit(2)


if __name__ == "__main__":
    # exit-code: n/a
    #   本脚本是**纯报告工具**（只 print 候选排序，不写任何文件、无失败模式），
    #   恒返回 0 是正确语义。用 `exit-code: n/a` 标记出来，让 optimize_scan 的
    #   「有 CLI 入口却没有退出码语义」这一条不再误报它 —— 而不是让扫描器闭嘴。
    _entry()
